"""
Machine Learning Models for Time Series Analysis
"""
import numpy as np
import pandas as pd
import logging
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

DEBUG = False

try:
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logging.warning("scikit-learn not available, ML features will be limited")

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logging.warning("PyTorch not available, neural network features will be limited")


class LSTMPredictor:
    """LSTM model for time series prediction"""
    
    def __init__(self, sequence_length: int = 60, hidden_size: int = 50, num_layers: int = 2):
        self.sequence_length = sequence_length
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.scaler = MinMaxScaler() if SKLEARN_AVAILABLE else None
        self.model = None
        self.device = torch.device('cuda' if TORCH_AVAILABLE and torch.cuda.is_available() else 'cpu')
        self.logger = logging.getLogger("ml_models")
    
    def prepare_data(self, prices: List[float]) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare data for LSTM"""
        if not TORCH_AVAILABLE or not SKLEARN_AVAILABLE:
            return np.array([]), np.array([])
        
        if len(prices) < self.sequence_length + 1:
            return np.array([]), np.array([])
        
        # Normalize
        prices_array = np.array(prices).reshape(-1, 1)
        if DEBUG:
            print("prepare_data: prices_array.shape =", prices_array.shape, "sample =", prices_array[:5].flatten().tolist())
    
        scaled = self.scaler.fit_transform(prices_array)
        if DEBUG:
            print("prepare_data: scaled.shape =", scaled.shape, "scaled[:5] =", scaled[:5].flatten().tolist())
    
        
        X, y = [], []
        for i in range(self.sequence_length, len(scaled)):
            X.append(scaled[i-self.sequence_length:i, 0])
            y.append(scaled[i, 0])
        
        X = np.array(X)
        y = np.array(y)
        if DEBUG:
            print("prepare_data: X.shape =", X.shape, "y.shape =", y.shape)  # <- ключ
        return X, y
    
    def build_model(self, input_size: int = 1):
        """Build LSTM model"""
        if not TORCH_AVAILABLE:
            return None
        
        class LSTMModel(nn.Module):
            def __init__(self, input_size, hidden_size, num_layers):
                super().__init__()
                self.hidden_size = hidden_size
                self.num_layers = num_layers
                self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
                self.fc = nn.Linear(hidden_size, 1)
            
            def forward(self, x):
                h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
                c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
                out, _ = self.lstm(x, (h0, c0))
                out = self.fc(out[:, -1, :])
                return out
        
        return LSTMModel(input_size, self.hidden_size, self.num_layers).to(self.device)
    
    def train(self, prices: List[float], epochs: int = 50):
        """Train LSTM model"""
        if not TORCH_AVAILABLE or not SKLEARN_AVAILABLE:
            return False
        
        X, y = self.prepare_data(prices)
        if DEBUG:
            print("train: after prepare_data - X.ndim, X.shape:", X.ndim, X.shape)
        if len(X) == 0:
            return False

        if DEBUG:
            print("train: X[0].shape:", X[0].shape if len(X)>0 else None, "X[0] sample:", X[0][:5] if len(X)>0 else None)
        
        self.model = self.build_model()
        if self.model is None:
            return False
        
        X_tensor = torch.FloatTensor(X).unsqueeze(-1).to(self.device)
        y_tensor = torch.FloatTensor(y).unsqueeze(-1).to(self.device)
        if DEBUG:
            print("train: X_tensor.shape =", X_tensor.shape, "y_tensor.shape =", y_tensor.shape)

        
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        
        self.model.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            outputs = self.model(X_tensor)
            loss = criterion(outputs, y_tensor)
            loss.backward()
            optimizer.step()
            
            if (epoch + 1) % 10 == 0:
                self.logger.debug(f"Epoch [{epoch+1}/{epochs}], Loss: {loss.item():.4f}")
        
        return True
    
    def predict(self, prices: List[float], days: int = 7) -> List[float]:
        """Predict future prices"""
        if not TORCH_AVAILABLE or not SKLEARN_AVAILABLE or self.model is None:
            return []
        
        if len(prices) < self.sequence_length:
            return []
        
        self.model.eval()
        predictions = []
        current_sequence = prices[-self.sequence_length:]
        
        # Normalize
        if DEBUG:
            print("predict: current_sequence shape:", np.array(current_sequence).shape)
        prices_array = np.array(current_sequence).reshape(-1, 1)
        scaled = self.scaler.transform(prices_array)
        if DEBUG:
            print("predict: scaled.shape =", scaled.shape, "scaled[:3] =", scaled[:3].flatten().tolist())

        
        with torch.no_grad():
            for _ in range(days):
                window = scaled[-self.sequence_length:]
                if DEBUG:
                    print("predict: window.shape (before torch) =", window.shape) 
                X = torch.FloatTensor(window).unsqueeze(0).to(self.device)
                if DEBUG:
                    print("predict: X.shape (tensor) =", X.shape) 
                
                pred = self.model(X)
                pred_value = pred.cpu().numpy()[0, 0]
                
                # Denormalize
                pred_denorm = self.scaler.inverse_transform([[pred_value]])[0, 0]
                predictions.append(pred_denorm)
                
                # Update sequence
                scaled = np.append(scaled, [[pred_value]], axis=0)
        
        return predictions


class SimpleMovingAveragePredictor:
    """Simple moving average based predictor (fallback when ML is not available)"""
    
    def __init__(self, window: int = 20):
        self.window = window
    
    def predict(self, prices: List[float], days: int = 7) -> List[float]:
        """Predict using moving average"""
        if len(prices) < self.window:
            return [prices[-1]] * days if prices else []
        
        ma = np.mean(prices[-self.window:])
        trend = (prices[-1] - prices[-self.window]) / self.window if len(prices) > self.window else 0
        
        predictions = []
        for i in range(1, days + 1):
            predictions.append(ma + trend * i)
        
        return predictions


class MLPredictor:
    """Main ML predictor interface"""
    
    def __init__(self):
        self.lstm = LSTMPredictor()
        self.sma = SimpleMovingAveragePredictor()
        self.logger = logging.getLogger("ml_models")
    
    def predict(self, candles: List[Dict], days: int = 7, use_lstm: bool = True) -> Tuple[List[float], float]:
        """
        Predict future prices
        Returns: (predictions, confidence)
        """
        if not candles or len(candles) < 60:
            return [], 0.0
        
        prices = [c['close'] for c in candles]
        
        if use_lstm and TORCH_AVAILABLE and SKLEARN_AVAILABLE:
            try:
                # Train model
                if self.lstm.train(prices, epochs=30):
                    predictions = self.lstm.predict(prices, days=days)
                    if predictions:
                        # Calculate confidence based on recent volatility
                        recent_std = np.std(prices[-20:]) if len(prices) >= 20 else np.std(prices)
                        mean_price = np.mean(prices[-20:]) if len(prices) >= 20 else np.mean(prices)
                        confidence = max(0.0, min(1.0, 1.0 - (recent_std / mean_price) if mean_price > 0 else 0.5))
                        return predictions, confidence
            except Exception as e:
                self.logger.error(f"LSTM prediction error: {e}")
        
        # Fallback to SMA
        predictions = self.sma.predict(prices, days=days)
        confidence = 0.6  # Lower confidence for simple methods
        return predictions, confidence

