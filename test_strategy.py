"""
Unit tests for strategy.py (pure functions, synthetic series)
Run: venv/bin/python -m pytest test_strategy.py -q  (or python test_strategy.py)
"""
import numpy as np

import strategy


def test_tsmom_signs():
    up = list(np.linspace(100, 200, 300))
    down = list(np.linspace(200, 100, 300))
    m_up = strategy.tsmom(up)
    m_down = strategy.tsmom(down)
    assert m_up['m3'] > 0 and m_up['m12_1'] > 0
    assert m_down['m3'] < 0 and m_down['m12_1'] < 0


def test_tsmom_insufficient_data():
    m = strategy.tsmom([100.0] * 40)
    assert m['m12_1'] is None
    assert m['m3'] is None


def test_regime_10m_sma_flip():
    growing = list(np.linspace(100, 200, 24))
    falling = list(np.linspace(200, 100, 24))
    reg_up = strategy.regime(growing, cbr_rate=8.0, cbr_rate_3m_ago=8.0)
    reg_down = strategy.regime(falling, cbr_rate=8.0, cbr_rate_3m_ago=8.0)
    assert reg_up['trend_up'] and reg_up['risk_on']
    assert not reg_down['trend_up'] and not reg_down['risk_on']


def test_regime_high_rate_blocks_risk_on():
    growing = list(np.linspace(100, 200, 24))
    # Rate 21% and rising: hostile even in an uptrend (Russia 2024)
    reg = strategy.regime(growing, cbr_rate=21.0, cbr_rate_3m_ago=19.0)
    assert reg['trend_up'] and not reg['rate_friendly']
    assert reg['cell'] == 'trend_up_rate_hostile'
    # Rate 16% but falling from 21% (2025-26 cutting cycle): friendly again
    reg2 = strategy.regime(growing, cbr_rate=16.0, cbr_rate_3m_ago=21.0)
    assert reg2['rate_friendly'] and reg2['risk_on']


def test_allocation_shifts_to_cash_when_risk_off():
    growing = list(np.linspace(100, 200, 24))
    falling = list(np.linspace(200, 100, 24))
    alloc_on = strategy.allocation(strategy.regime(growing, 8.0, 8.0))
    alloc_off = strategy.allocation(strategy.regime(falling, 21.0, 19.0))
    assert alloc_on['equities'] > alloc_off['equities']
    assert alloc_off['money_market'] > alloc_on['money_market']
    assert abs(sum(alloc_on.values()) - 1.0) < 1e-9
    assert abs(sum(alloc_off.values()) - 1.0) < 1e-9


def test_xsec_rank_order_and_none():
    scores = {'A': 0.5, 'B': -0.1, 'C': 0.9, 'D': None}
    ranks = strategy.xsec_rank(scores)
    assert ranks['C'] > ranks['A'] > ranks['B']
    assert ranks['D'] is None
    assert ranks['C'] == 1.0 and ranks['B'] == 0.0


def test_vol_scaled_momentum():
    # Same momentum, lower vol -> higher score
    assert strategy.vol_scaled_momentum(0.10, 0.20) > strategy.vol_scaled_momentum(0.10, 0.60)
    assert strategy.vol_scaled_momentum(None, 0.2) is None
    assert strategy.vol_scaled_momentum(0.1, 0.0) is None


def test_hysteresis():
    reg = {'risk_on': True}
    comp = {'xsec_pct': 0.75, 'm3': 0.05, 'm12_1': 0.10, 'tilt': 0.2}
    # composite = 0.45*0.75 + 0.30*1.0 + 0.25*0.2 = 0.6875 -> below entry 0.70
    fresh = strategy.combine(comp, reg, prev_action=None)
    held = strategy.combine(comp, reg, prev_action='BUY')
    assert fresh['action'] == 'HOLD'
    assert held['action'] == 'BUY'  # hysteresis keeps existing position


def test_sentiment_veto_blocks_buy_only():
    reg = {'risk_on': True}
    comp = {'xsec_pct': 0.95, 'm3': 0.2, 'm12_1': 0.3, 'tilt': 0.9, 'sentiment': -0.6}
    res = strategy.combine(comp, reg, prev_action=None)
    assert res['vetoed'] and res['action'] != 'BUY'
    # Positive sentiment must not create a BUY out of a weak asset
    weak = {'xsec_pct': 0.1, 'm3': -0.2, 'm12_1': -0.3, 'tilt': 0.2, 'sentiment': 0.9}
    res2 = strategy.combine(weak, reg, prev_action=None)
    assert res2['action'] == 'SELL'


def test_risk_off_dampens_composite():
    comp = {'xsec_pct': 0.95, 'm3': 0.2, 'm12_1': 0.3, 'tilt': 0.9}
    on = strategy.combine(comp, {'risk_on': True}, None)
    off = strategy.combine(comp, {'risk_on': False}, None)
    assert on['action'] == 'BUY'
    assert off['composite'] < on['composite']


def test_data_missing_is_avoid():
    res = strategy.combine({'data_missing': True}, {'risk_on': True}, None)
    assert res['action'] == 'AVOID'


def test_evaluate_hit():
    assert strategy.evaluate_hit('BUY', 0.05) == 1
    assert strategy.evaluate_hit('BUY', -0.05) == 0
    assert strategy.evaluate_hit('SELL', -0.05) == 1
    assert strategy.evaluate_hit('HOLD', 0.05) is None
    assert strategy.evaluate_hit('BUY', None) is None


def test_component_report():
    evaluated = [
        {'action': 'BUY', 'components': {'m3': 0.1, 'xsec_pct': 0.9, 'tilt': 0.8},
         'realized_return': 0.03, 'hit': 1, 'in_zone': 1},
        {'action': 'BUY', 'components': {'m3': 0.2, 'xsec_pct': 0.85, 'tilt': 0.4},
         'realized_return': -0.02, 'hit': 0, 'in_zone': 0},
        {'action': 'SELL', 'components': {'m3': -0.1, 'xsec_pct': 0.1, 'tilt': 0.3},
         'realized_return': -0.04, 'hit': 1, 'in_zone': 1},
    ]
    report = strategy.component_report(evaluated, benchmark_return=-0.01)
    assert report['n_evaluated'] == 3
    assert report['overall_hit_rate'] == round(2 / 3, 4)
    assert report['by_component']['tsmom_3m']['bullish']['n'] == 2
    assert report['by_component']['tsmom_3m']['bearish']['median_return'] == -0.04
    assert report['forecast_zone_coverage'] == round(2 / 3, 4)
    assert report['benchmark_return'] == -0.01


if __name__ == '__main__':
    import sys
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failures else 0)
