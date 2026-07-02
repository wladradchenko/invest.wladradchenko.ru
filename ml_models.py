"""
Machine Learning Models for Time Series Analysis

Chronos-Bolt (amazon/chronos-bolt-small) gives zero-shot quantile forecasts.
Honest framing: the output is a ZONE of probable prices (q10/q50/q90),
not a point prediction — daily returns are close to a random walk and no
model reliably beats that; the zone width is the honest uncertainty.
"""
import numpy as np
import logging
from typing import List, Dict, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logging.warning("PyTorch not available, neural network features will be limited")

try:
    from chronos import BaseChronosPipeline
    CHRONOS_AVAILABLE = TORCH_AVAILABLE
except ImportError:
    CHRONOS_AVAILABLE = False
    logging.warning("chronos-forecasting not available, falling back to SMA predictor")


class ChronosPredictor:
    """Zero-shot quantile forecaster on top of Chronos-Bolt (48M params, CPU-friendly)"""

    MODEL_ID = "amazon/chronos-bolt-small"
    MIN_CONTEXT = 30          # too little history -> refuse instead of guessing
    QUANTILES = [0.1, 0.5, 0.9]

    def __init__(self):
        self.logger = logging.getLogger("ml_models")
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._pipeline = BaseChronosPipeline.from_pretrained(
                self.MODEL_ID,
                device_map=device,
                torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            )
            self.logger.info(f"Chronos-Bolt loaded on {device}")
        return self._pipeline

    def predict(self, prices: List[float], days: int = 7) -> Optional[Dict[str, List[float]]]:
        """Returns {'low': [...], 'median': [...], 'high': [...]} of length `days`"""
        if not CHRONOS_AVAILABLE or len(prices) < self.MIN_CONTEXT:
            return None
        try:
            pipeline = self._load()
            context = torch.tensor(prices, dtype=torch.float32)
            quantiles, _ = pipeline.predict_quantiles(
                context,
                prediction_length=days,
                quantile_levels=self.QUANTILES,
            )
            q = quantiles[0].cpu().numpy()  # shape: [days, 3]
            return {
                'low': [float(v) for v in q[:, 0]],
                'median': [float(v) for v in q[:, 1]],
                'high': [float(v) for v in q[:, 2]],
            }
        except Exception as e:
            self.logger.error(f"Chronos prediction error: {e}")
            return None


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
        self.chronos = ChronosPredictor()
        self.sma = SimpleMovingAveragePredictor()
        self.logger = logging.getLogger("ml_models")

    def predict(self, candles: List[Dict], days: int = 7) -> Tuple[Dict[str, List[float]], float, str]:
        """
        Predict future price zone.
        Returns: (forecast {'low','median','high'}, confidence, model_type)

        Confidence is derived from the relative width of the q10-q90 zone:
        narrow zone -> the model considers outcomes concentrated. It is an
        uncertainty measure, not a promise of accuracy.
        """
        if not candles or len(candles) < 30:
            return {}, 0.0, 'none'

        prices = [c['close'] for c in candles]

        forecast = self.chronos.predict(prices, days=days)
        if forecast:
            widths = [
                (h - l) / m
                for l, m, h in zip(forecast['low'], forecast['median'], forecast['high'])
                if m > 0
            ]
            mean_width = float(np.mean(widths)) if widths else 1.0
            confidence = max(0.0, min(1.0, 1.0 - mean_width))
            return forecast, confidence, 'chronos_bolt'

        # Fallback: SMA point forecast, zone unknown
        median = self.sma.predict(prices, days=days)
        forecast = {'low': median, 'median': median, 'high': median}
        return forecast, 0.3, 'sma'
