"""
Technical Indicators with Explanations and Recommendations
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime

try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False


class IndicatorAnalyzer:
    """Technical indicator analyzer with explanations"""
    
    INDICATOR_INFO = {
        'RSI': {
            'name': 'RSI (Relative Strength Index)',
            'description': 'Measures the strength and speed of price changes. Shows whether the asset is overbought or oversold.',
            'range': (0, 100),
            'recommendations': {
                'oversold': (0, 30, 'Buy', 'The asset is oversold. Possible upward correction. Consider buying.'),
                'neutral_low': (30, 50, 'Neutral', 'The asset is in the lower part of the range. Potential growth.'),
                'neutral_high': (50, 70, 'Neutral', 'The asset is in the upper part of the range. Possible correction.'),
                'overbought': (70, 100, 'Sell', 'The asset is overbought. Possible downward correction. Consider selling.')
            }
        },
        'MACD': {
            'name': 'MACD (Moving Average Convergence Divergence)',
            'description': 'Shows the relationship between two moving averages of price. Helps identify trends and reversal points.',
            'range': None,
            'recommendations': {
                'bullish': ('positive', 'Buy', 'MACD is above zero and rising. Bullish trend. Consider buying.'),
                'bearish': ('negative', 'Sell', 'MACD is below zero and falling. Bearish trend. Consider selling.'),
                'crossover_up': ('crossover_up', 'Buy', 'MACD crossed the signal line upward. Bullish signal.'),
                'crossover_down': ('crossover_down', 'Sell', 'MACD crossed the signal line downward. Bearish signal.')
            }
        },
        'BB': {
            'name': 'Bollinger Bands',
            'description': 'Indicates volatility and potential support/resistance levels.',
            'range': None,
            'recommendations': {
                'lower_touch': ('lower', 'Buy', 'Price touched the lower band. Possible rebound upward.'),
                'upper_touch': ('upper', 'Sell', 'Price touched the upper band. Possible pullback downward.'),
                'middle': ('middle', 'Neutral', 'Price is in the middle of the band. Trend continues.')
            }
        },
        'EMA': {
            'name': 'EMA (Exponential Moving Average)',
            'description': 'Exponential moving average, more sensitive to recent prices.',
            'range': None,
            'recommendations': {
                'above': ('above', 'Buy', 'Price is above EMA. Uptrend.'),
                'below': ('below', 'Sell', 'Price is below EMA. Downtrend.')
            }
        },
        'ADX': {
            'name': 'ADX (Average Directional Index)',
            'description': 'Measures the strength of a trend, but not its direction.',
            'range': (0, 100),
            'recommendations': {
                'strong': (25, 100, 'Strong trend', 'ADX is above 25. Strong trend. Follow the trend.'),
                'weak': (0, 25, 'Weak trend', 'ADX is below 25. Weak or sideways trend. Be careful.')
            }
        }
    }

    
    def __init__(self):
        pass
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> Tuple[float, Dict]:
        """Calculate RSI indicator"""
        if len(prices) < period + 1:
            return 0.0, {'value': 0.0, 'status': 'insufficient_data', 'recommendation': 'Недостаточно данных'}
        
        if TALIB_AVAILABLE:
            rsi = talib.RSI(np.array(prices), timeperiod=period)[-1]
        else:
            # Simple RSI calculation
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            
            avg_gain = np.mean(gains[-period:])
            avg_loss = np.mean(losses[-period:])
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
        
        # Get recommendation
        info = self.INDICATOR_INFO['RSI']
        recommendation = None
        status = 'neutral'
        
        for key, (low, high, action, desc) in info['recommendations'].items():
            if low <= rsi <= high:
                recommendation = {'action': action, 'description': desc, 'value': rsi}
                status = key
                break
        
        return rsi, {
            'value': round(rsi, 2),
            'status': status,
            'recommendation': recommendation,
            'info': info
        }
    
    def calculate_macd(self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float, Dict]:
        """Calculate MACD indicator"""
        if len(prices) < slow + signal:
            return 0.0, 0.0, 0.0, {'value': 0.0, 'status': 'insufficient_data', 'recommendation': 'Insufficient data'}
        
        if TALIB_AVAILABLE:
            macd, signal_line, histogram = talib.MACD(np.array(prices), fastperiod=fast, slowperiod=slow, signalperiod=signal)
            
            macd_line = list(macd)
            signal_line = list(signal_line)
            hist_list = list(histogram)

            macd_val = macd_line[-1]
            signal_val = signal_line[-1]
            hist_val = hist_list[-1]
        else:
            # Simple MACD calculation
            ema_fast = self._ema(prices, fast)
            ema_slow = self._ema(prices, slow)
            macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
            signal_line = self._ema(macd_line, signal)
            
            macd_val = macd_line[-1] if macd_line else 0.0
            signal_val = signal_line[-1] if signal_line else 0.0
            hist_val = macd_val - signal_val
        
        # Get recommendation
        info = self.INDICATOR_INFO['MACD']
        recommendation = None
        status = 'neutral'
        
        if macd_val > 0 and macd_val > signal_val:
            recommendation = {'action': 'Buy', 'description': info['recommendations']['bullish'][2], 'value': macd_val}
            status = 'bullish'
        elif macd_val < 0 and macd_val < signal_val:
            recommendation = {'action': 'Sell', 'description': info['recommendations']['bearish'][2], 'value': macd_val}
            status = 'bearish'
        elif hist_val > 0 and len(macd_line) > 1 and macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]:
            recommendation = {'action': 'Buy', 'description': info['recommendations']['crossover_up'][2], 'value': macd_val}
            status = 'crossover_up'
        elif hist_val < 0 and len(macd_line) > 1 and macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]:
            recommendation = {'action': 'Sell', 'description': info['recommendations']['crossover_down'][2], 'value': macd_val}
            status = 'crossover_down'
        
        return macd_val, signal_val, hist_val, {
            'macd': round(macd_val, 2),
            'signal': round(signal_val, 2),
            'histogram': round(hist_val, 2),
            'status': status,
            'recommendation': recommendation,
            'info': info
        }
    
    def calculate_bollinger_bands(self, prices: List[float], period: int = 20, std_dev: int = 2) -> Tuple[float, float, float, Dict]:
        """Calculate Bollinger Bands"""
        if len(prices) < period:
            return 0.0, 0.0, 0.0, {'value': 0.0, 'status': 'insufficient_data', 'recommendation': 'Insufficient data'}
        
        if TALIB_AVAILABLE:
            upper, middle, lower = talib.BBANDS(np.array(prices), timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev)
            upper_val = upper[-1]
            middle_val = middle[-1]
            lower_val = lower[-1]
        else:
            # Simple BB calculation
            sma = np.mean(prices[-period:])
            std = np.std(prices[-period:])
            middle_val = sma
            upper_val = sma + (std * std_dev)
            lower_val = sma - (std * std_dev)
        
        current_price = prices[-1]
        
        # Get recommendation
        info = self.INDICATOR_INFO['BB']
        recommendation = None
        status = 'middle'
        
        if current_price <= lower_val * 1.01:  # Within 1% of lower band
            recommendation = {'action': 'Buy', 'description': info['recommendations']['lower_touch'][2], 'value': current_price}
            status = 'lower_touch'
        elif current_price >= upper_val * 0.99:  # Within 1% of upper band
            recommendation = {'action': 'Sell', 'description': info['recommendations']['upper_touch'][2], 'value': current_price}
            status = 'upper_touch'
        else:
            recommendation = {'action': 'Neutral', 'description': info['recommendations']['middle'][2], 'value': current_price}
            status = 'middle'
        
        return upper_val, middle_val, lower_val, {
            'upper': round(upper_val, 2),
            'middle': round(middle_val, 2),
            'lower': round(lower_val, 2),
            'current_price': round(current_price, 2),
            'status': status,
            'recommendation': recommendation,
            'info': info
        }
    
    def calculate_ema(self, prices: List[float], period: int = 20) -> Tuple[float, Dict]:
        """Calculate EMA"""
        if len(prices) < period:
            return 0.0, {'value': 0.0, 'status': 'insufficient_data', 'recommendation': 'Недостаточно данных'}
        
        ema_val = self._ema(prices, period)[-1] if self._ema(prices, period) else prices[-1]
        current_price = prices[-1]
        
        # Get recommendation
        info = self.INDICATOR_INFO['EMA']
        recommendation = None
        status = 'neutral'
        
        if current_price > ema_val:
            recommendation = {'action': 'Buy', 'description': info['recommendations']['above'][2], 'value': ema_val}
            status = 'above'
        else:
            recommendation = {'action': 'Sell', 'description': info['recommendations']['below'][2], 'value': ema_val}
            status = 'below'
        
        return ema_val, {
            'value': round(ema_val, 2),
            'current_price': round(current_price, 2),
            'status': status,
            'recommendation': recommendation,
            'info': info
        }
    
    def calculate_adx(self, high: List[float], low: List[float], close: List[float], period: int = 14) -> Tuple[float, Dict]:
        """Calculate ADX"""
        if len(high) < period * 2 or len(low) < period * 2 or len(close) < period * 2:
            return 0.0, {'value': 0.0, 'status': 'insufficient_data', 'recommendation': 'Insufficient data'}
        
        if TALIB_AVAILABLE:
            adx = talib.ADX(np.array(high), np.array(low), np.array(close), timeperiod=period)[-1]
        else:
            # Simple ADX approximation
            adx = 25.0  # Default neutral value
        
        # Get recommendation
        info = self.INDICATOR_INFO['ADX']
        recommendation = None
        status = 'weak'
        
        if adx >= 25:
            recommendation = {'action': 'Strong trend', 'description': info['recommendations']['strong'][2], 'value': adx}
            status = 'strong'
        else:
            recommendation = {'action': 'Weak trend', 'description': info['recommendations']['weak'][2], 'value': adx}
            status = 'weak'
        
        return adx, {
            'value': round(adx, 2),
            'status': status,
            'recommendation': recommendation,
            'info': info
        }
    
    def _ema(self, prices: List[float], period: int) -> List[float]:
        """Calculate Exponential Moving Average"""
        if not prices or period <= 0:
            return []
        
        multiplier = 2 / (period + 1)
        ema = [prices[0]]
        
        for price in prices[1:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        
        return ema
    
    def analyze_all(self, candles: List[Dict]) -> Dict:
        """Calculate all indicators"""
        if not candles or len(candles) < 20:
            return {'error': 'Insufficient data for analysis'}
        
        prices = [c['close'] for c in candles]
        high = [c['high'] for c in candles]
        low = [c['low'] for c in candles]
        close = [c['close'] for c in candles]
        
        results = {}
        
        # RSI
        rsi, rsi_info = self.calculate_rsi(prices)
        results['RSI'] = rsi_info
        
        # MACD
        macd, signal, hist, macd_info = self.calculate_macd(prices)
        results['MACD'] = macd_info
        
        # Bollinger Bands
        bb_upper, bb_middle, bb_lower, bb_info = self.calculate_bollinger_bands(prices)
        results['BB'] = bb_info
        
        # EMA
        ema, ema_info = self.calculate_ema(prices)
        results['EMA'] = ema_info
        
        # ADX
        adx, adx_info = self.calculate_adx(high, low, close)
        results['ADX'] = adx_info
        
        # Overall recommendation
        recommendations = [r for r in [rsi_info.get('recommendation'), macd_info.get('recommendation'), bb_info.get('recommendation'), ema_info.get('recommendation')] if r]
        
        buy_signals = sum(1 for r in recommendations if r and isinstance(r, dict) and r.get('action') == 'Buy')
        sell_signals = sum(1 for r in recommendations if r and isinstance(r, dict) and r.get('action') == 'Sell')
        
        overall_action = 'Neutral'
        if buy_signals >= 3:
            overall_action = 'Buy'
        elif sell_signals >= 3:
            overall_action = 'Sell'
        elif buy_signals > sell_signals:
            overall_action = 'Consider buying'
        elif sell_signals > buy_signals:
            overall_action = 'Consider selling'
        
        results['overall'] = {
            'action': overall_action,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'total_indicators': len(recommendations)
        }
        
        return results

