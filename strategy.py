"""
Strategy engine — pure functions, no I/O (unit-testable).

Only components with credible academic evidence, at weekly frequency:
- Regime filter: index vs 10-month SMA (Faber 2007) x CBR key rate level/direction.
  Lesson of 2024-25: with the key rate at 16-21% cash/money-market dominated
  Russian equities for two straight years; an advisor must see the rate.
- Time-series momentum 12-1 and 3m (Moskowitz-Ooi-Pedersen 2012; for Russia
  the 3-month variant is stronger: Teplova-Mikova 2014).
- Cross-sectional momentum scaled by volatility (Barroso & Santa-Clara 2015).
- Low-volatility / dividend tilt (Blitz & van Vliet 2007).
- Sentiment as a VETO on buying only, never a standalone signal
  (Lopez-Lira & Tang 2023).
- Hysteresis between entry/hold thresholds for low turnover
  (transaction costs: Novy-Marx & Velikov 2016).
"""
from typing import Dict, List, Optional

import numpy as np

TRADING_DAYS_YEAR = 252
TRADING_DAYS_MONTH = 21


# ---------------- regime & allocation ----------------

def sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return float(np.mean(values[-window:]))


def regime(index_monthly_closes: List[float], cbr_rate: float,
           cbr_rate_3m_ago: float, high_rate_level: float = 12.0) -> Dict:
    """Market regime: index trend (10-month SMA) x key rate friendliness."""
    sma10 = sma(index_monthly_closes, 10)
    last = index_monthly_closes[-1] if index_monthly_closes else None
    trend_up = bool(sma10 and last and last > sma10)

    rate_falling = cbr_rate is not None and cbr_rate_3m_ago is not None and cbr_rate < cbr_rate_3m_ago
    rate_low = cbr_rate is not None and cbr_rate < high_rate_level
    rate_friendly = rate_low or rate_falling

    cell = {
        (True, True): 'risk_on',
        (True, False): 'trend_up_rate_hostile',
        (False, True): 'trend_down_rate_friendly',
        (False, False): 'risk_off',
    }[(trend_up, rate_friendly)]

    return {
        'trend_up': trend_up,
        'index_last': last,
        'index_sma10m': round(sma10, 2) if sma10 else None,
        'cbr_rate': cbr_rate,
        'cbr_rate_3m_ago': cbr_rate_3m_ago,
        'rate_falling': rate_falling,
        'rate_friendly': rate_friendly,
        'risk_on': cell == 'risk_on',
        'cell': cell,
    }


def allocation(reg: Dict) -> Dict[str, float]:
    """Target asset-class weights for the regime cell."""
    table = {
        'risk_on':                 {'equities': 0.60, 'bonds': 0.20, 'money_market': 0.10, 'gold': 0.10},
        'trend_up_rate_hostile':   {'equities': 0.35, 'bonds': 0.25, 'money_market': 0.30, 'gold': 0.10},
        'trend_down_rate_friendly': {'equities': 0.25, 'bonds': 0.40, 'money_market': 0.25, 'gold': 0.10},
        'risk_off':                {'equities': 0.10, 'bonds': 0.30, 'money_market': 0.50, 'gold': 0.10},
    }
    return table[reg['cell']]


# ---------------- per-asset components ----------------

def tsmom(prices: List[float]) -> Dict[str, Optional[float]]:
    """Time-series momentum: 12-1 (skip last month) and 3-month returns."""
    n = len(prices)
    out = {'m12_1': None, 'm3': None}
    if n > TRADING_DAYS_YEAR:
        p_start = prices[-TRADING_DAYS_YEAR]
        p_end = prices[-TRADING_DAYS_MONTH]
        if p_start > 0:
            out['m12_1'] = p_end / p_start - 1.0
    if n > 3 * TRADING_DAYS_MONTH:
        p_start = prices[-3 * TRADING_DAYS_MONTH]
        if p_start > 0:
            out['m3'] = prices[-1] / p_start - 1.0
    return out


def ann_vol(prices: List[float]) -> Optional[float]:
    """Annualized volatility of daily returns"""
    if len(prices) < 30:
        return None
    arr = np.asarray(prices, dtype=float)
    rets = np.diff(arr) / arr[:-1]
    return float(np.std(rets) * np.sqrt(TRADING_DAYS_YEAR))


def xsec_rank(scores: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
    """Percentile rank (0..1) across the universe; None stays None."""
    valid = {k: v for k, v in scores.items() if v is not None}
    if not valid:
        return {k: None for k in scores}
    ordered = sorted(valid.values())
    n = len(ordered)
    result = {}
    for k, v in scores.items():
        if v is None:
            result[k] = None
        else:
            rank = sum(1 for x in ordered if x <= v)
            result[k] = round((rank - 1) / (n - 1), 4) if n > 1 else 0.5
    return result


def vol_scaled_momentum(m3: Optional[float], vol: Optional[float]) -> Optional[float]:
    """Momentum scaled by volatility (Barroso & Santa-Clara 2015)"""
    if m3 is None or vol is None or vol <= 0:
        return None
    return m3 / vol


def lowvol_div_tilt(vol_pct: Optional[float], div_yield: Optional[float]) -> float:
    """0..1 tilt: reward low volatility (inverted percentile) and dividends.
    div_yield is a fraction (0.10 = 10%), capped at 15% contribution-wise."""
    vol_part = (1.0 - vol_pct) if vol_pct is not None else 0.5
    div_part = min((div_yield or 0.0) / 0.15, 1.0)
    return round(0.6 * vol_part + 0.4 * div_part, 4)


def sentiment_score(mean_positive: float, mean_negative: float, n_posts: int,
                    min_posts: int = 5) -> Optional[float]:
    """-1..1; None when there is not enough data to say anything."""
    if n_posts < min_posts:
        return None
    return round(float(mean_positive - mean_negative), 4)


# ---------------- combining into an action ----------------

def combine(components: Dict, reg: Dict, prev_action: Optional[str],
            buy_threshold: float = 0.70, hold_threshold: float = 0.55,
            sentiment_veto_threshold: float = -0.3) -> Dict:
    """
    -> {'action': BUY|HOLD|SELL|AVOID, 'composite': float, 'vetoed': bool}

    composite = 0.45 * cross-sectional momentum percentile
              + 0.30 * trend agreement (3m and 12-1 signs)
              + 0.25 * low-vol/dividend tilt
    risk-off regime scales the score by 0.7 (harder to justify a BUY).
    Negative sentiment can only veto a BUY, never create one.
    Hysteresis: an existing BUY survives above hold_threshold.
    """
    if components.get('data_missing'):
        return {'action': 'AVOID', 'composite': 0.0, 'vetoed': False}

    mom_pct = components.get('xsec_pct')
    m3 = components.get('m3')
    m12 = components.get('m12_1')
    tilt = components.get('tilt', 0.5)

    mom_score = mom_pct if mom_pct is not None else 0.5
    if m3 is not None and m3 > 0 and (m12 is None or m12 > 0):
        trend_score = 1.0
    elif m3 is not None and m3 > 0:
        trend_score = 0.5
    else:
        trend_score = 0.0

    composite = 0.45 * mom_score + 0.30 * trend_score + 0.25 * tilt
    if not reg.get('risk_on'):
        composite *= 0.7

    vetoed = False
    sent = components.get('sentiment')
    if sent is not None and sent < sentiment_veto_threshold and composite >= hold_threshold:
        composite = hold_threshold - 0.01
        vetoed = True

    composite = round(composite, 4)

    threshold = hold_threshold if prev_action == 'BUY' else buy_threshold
    if composite >= threshold:
        action = 'BUY'
    elif composite <= 0.30:
        action = 'SELL'
    else:
        action = 'HOLD'

    return {'action': action, 'composite': composite, 'vetoed': vetoed}


# ---------------- self-evaluation ----------------

def evaluate_hit(action: str, realized_return: Optional[float]) -> Optional[int]:
    """BUY hits when the price rose, SELL/AVOID when it fell.
    HOLD is excluded from the hit-rate."""
    if realized_return is None:
        return None
    if action == 'BUY':
        return int(realized_return > 0)
    if action in ('SELL', 'AVOID'):
        return int(realized_return < 0)
    return None


def component_report(evaluated: List[Dict], benchmark_return: Optional[float]) -> Dict:
    """
    Error analysis by strategy component.
    evaluated: [{action, components: dict, realized_return, hit}, ...]

    For each component, split recommendations into a bullish and a bearish
    bucket by its predicate and compare median realized returns — this shows
    WHICH component was wrong this week.
    """
    predicates = {
        'tsmom_3m': lambda c: (c.get('m3') or 0) > 0,
        'tsmom_12_1': lambda c: (c.get('m12_1') or 0) > 0,
        'xsec_momentum': lambda c: (c.get('xsec_pct') or 0) >= 0.8,
        'lowvol_div_tilt': lambda c: (c.get('tilt') or 0) >= 0.7,
        'sentiment_veto': lambda c: bool(c.get('vetoed')),
    }

    rows = [e for e in evaluated if e.get('realized_return') is not None]

    def bucket_stats(items: List[Dict]) -> Dict:
        rets = [i['realized_return'] for i in items]
        hits = [i['hit'] for i in items if i.get('hit') is not None]
        return {
            'n': len(items),
            'median_return': round(float(np.median(rets)), 4) if rets else None,
            'hit_rate': round(float(np.mean(hits)), 4) if hits else None,
        }

    components = {}
    for name, predicate in predicates.items():
        bullish = [r for r in rows if predicate(r.get('components', {}))]
        bearish = [r for r in rows if not predicate(r.get('components', {}))]
        components[name] = {
            'bullish': bucket_stats(bullish),
            'bearish': bucket_stats(bearish),
        }

    by_action = {}
    for action in ('BUY', 'HOLD', 'SELL', 'AVOID'):
        items = [r for r in rows if r.get('action') == action]
        if items:
            by_action[action] = bucket_stats(items)

    all_hits = [r['hit'] for r in rows if r.get('hit') is not None]
    zone_rows = [r for r in rows if r.get('in_zone') is not None]
    return {
        'n_evaluated': len(rows),
        'overall_hit_rate': round(float(np.mean(all_hits)), 4) if all_hits else None,
        'benchmark_return': round(benchmark_return, 4) if benchmark_return is not None else None,
        'by_action': by_action,
        'by_component': components,
        'forecast_zone_coverage': (
            round(float(np.mean([r['in_zone'] for r in zone_rows])), 4)
            if zone_rows else None
        ),
    }
