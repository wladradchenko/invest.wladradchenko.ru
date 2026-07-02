"""
Application settings: config.toml + environment overrides
"""
import os
import sys
import toml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.toml")

# Celery scrubs the cwd from sys.path at task time; pin the project dir so
# lazy imports inside tasks (database, text_models, ...) keep working
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DEFAULTS = {
    "advisor": {
        # Universe
        "index": "IMOEX",
        "bonds": [  # OFZ across durations (secid on TQOB)
            "SU26238RMFS4",  # long (2041)
            "SU26239RMFS2",  # medium (2031)
            "SU26232RMFS7",  # short (2027)
        ],
        "money_market": "LQDT",
        "gold": "GLDRUB_TOM",
        "gold_fallback": "GOLD",  # ETF on TQTF if CETS candles are unavailable
        # Strategy thresholds
        "buy_threshold": 0.70,
        "hold_threshold": 0.55,   # hysteresis: keep last week's BUY above this
        "sentiment_veto_threshold": -0.3,
        "sentiment_min_posts": 5,
        "max_reviews_per_job": 300,
        "high_rate_level": 12.0,  # CBR key rate above this = cash is king
        # Schedule (Europe/Moscow)
        "weekly_day": "sat",
        "weekly_hour": 8,
        "midweek_day": "thu",
        "midweek_hour": 16,
        # Alarm: midweek check flags recommendations that moved against us
        # by more than this fraction since the weekly report
        "alarm_move": 0.05,
    },
}


def load_config() -> dict:
    config = {}
    if os.path.exists(CONFIG_PATH):
        try:
            config = toml.load(CONFIG_PATH)
        except Exception:
            config = {}
    merged = {}
    for section, defaults in DEFAULTS.items():
        merged[section] = {**defaults, **config.get(section, {})}
    # Pass through any extra sections untouched
    for section, values in config.items():
        if section not in merged:
            merged[section] = values
    return merged


CONFIG = load_config()

# Load .env (honcho does this itself; this covers direct `python app.py` runs)
_env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "moex_data.db"))
