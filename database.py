"""
SQLite Database Accessor
"""
import os
import aiosqlite
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
import hashlib


class Database:
    """SQLite database accessor"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.getenv("DB_PATH", "moex_data.db")
        self.logger = logging.getLogger("database")

    @asynccontextmanager
    async def _connect(self):
        """Connection with pragmas required for safe multi-process access
        (quart web app + celery worker share the same file)."""
        db = await aiosqlite.connect(self.db_path)
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA synchronous=NORMAL")
            yield db
        finally:
            await db.close()

    async def init_db(self):
        """Initialize database tables"""
        async with self._connect() as db:
            # Candles table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    secid TEXT NOT NULL,
                    candle_open REAL NOT NULL,
                    candle_close REAL NOT NULL,
                    candle_low REAL NOT NULL,
                    candle_high REAL NOT NULL,
                    candle_volume INTEGER NOT NULL,
                    candle_time TIMESTAMP NOT NULL,
                    UNIQUE(secid, candle_time)
                )
            """)

            # Securities table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS securities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    secid TEXT UNIQUE NOT NULL,
                    secname TEXT,
                    isin TEXT,
                    prevprice REAL,
                    currencyid TEXT,
                    sectype TEXT,
                    lotsize INTEGER,
                    prevdate DATE,
                    board TEXT,
                    market TEXT,
                    engine TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Add board, market, engine columns if they don't exist (for existing databases)
            try:
                await db.execute("ALTER TABLE securities ADD COLUMN board TEXT")
            except:
                pass
            try:
                await db.execute("ALTER TABLE securities ADD COLUMN market TEXT")
            except:
                pass
            try:
                await db.execute("ALTER TABLE securities ADD COLUMN engine TEXT")
            except:
                pass

            # Indexes table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS indexes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    indexid TEXT UNIQUE NOT NULL,
                    shortname TEXT,
                    from_date DATE,
                    till_date DATE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ML predictions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ml_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    secid TEXT NOT NULL,
                    prediction_date DATE NOT NULL,
                    predicted_price REAL,
                    low_price REAL,
                    high_price REAL,
                    confidence REAL,
                    model_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(secid, prediction_date, model_type)
                )
            """)

            # Quantile zone columns for existing databases
            try:
                await db.execute("ALTER TABLE ml_predictions ADD COLUMN low_price REAL")
            except:
                pass
            try:
                await db.execute("ALTER TABLE ml_predictions ADD COLUMN high_price REAL")
            except:
                pass

            # Reviews table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    secid TEXT NOT NULL,
                    review_text_ru TEXT NOT NULL,
                    review_text_en TEXT NOT NULL,
                    review_img TEXT,
                    review_date DATE NOT NULL,
                    review_hash TEXT,
                    positive FLOAT DEFAULT 0, 
                    neutral FLOAT DEFAULT 0, 
                    negative FLOAT DEFAULT 0, 
                    anger FLOAT DEFAULT 0, 
                    anticipation FLOAT DEFAULT 0, 
                    disgust FLOAT DEFAULT 0, 
                    fear FLOAT DEFAULT 0, 
                    joy FLOAT DEFAULT 0, 
                    sadness FLOAT DEFAULT 0, 
                    surprise FLOAT DEFAULT 0, 
                    trust FLOAT DEFAULT 0,
                    source TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(secid, review_hash)
                )
            """)

            # Parse log: when each security's reviews were parsed last.
            # Kept separately from reviews so securities with zero reviews
            # are not re-parsed on every visit.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS parse_log (
                    secid TEXT PRIMARY KEY,
                    last_parsed_at TIMESTAMP NOT NULL
                )
            """)
            # One-time migration from the old per-review timestamps
            await db.execute("""
                INSERT INTO parse_log (secid, last_parsed_at)
                SELECT secid, MAX(last_parsed_at) FROM reviews GROUP BY secid
                ON CONFLICT(secid) DO NOTHING
            """)

            # Advisor: weekly/midweek reports
            await db.execute("""
                CREATE TABLE IF NOT EXISTS weekly_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week_start TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'weekly',   -- weekly | midweek
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ok',     -- ok | partial | failed
                    regime_json TEXT,
                    allocation_json TEXT,
                    evaluation_json TEXT,                  -- evaluation of the PREVIOUS report
                    alarms_json TEXT,                      -- midweek alarms
                    UNIQUE(week_start, kind)               -- idempotency: retry = upsert
                )
            """)

            # Advisor: per-asset recommendations of a weekly report
            await db.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id INTEGER NOT NULL REFERENCES weekly_reports(id),
                    secid TEXT NOT NULL,
                    asset_class TEXT NOT NULL,             -- equity | bond | money_market | gold
                    action TEXT NOT NULL,                  -- BUY | HOLD | SELL | AVOID
                    components_json TEXT NOT NULL,         -- all scores + reasons
                    price_at_reco REAL,
                    horizon_days INTEGER DEFAULT 7,
                    forecast_low REAL,
                    forecast_median REAL,
                    forecast_high REAL,
                    evaluated_at TEXT,
                    price_at_eval REAL,
                    realized_return REAL,
                    hit INTEGER,
                    in_zone INTEGER,                       -- actual close inside q10-q90 zone
                    UNIQUE(report_id, secid)
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_reco_report ON recommendations(report_id)")

            # Create indexes for performance
            await db.execute("CREATE INDEX IF NOT EXISTS idx_candles_secid_time ON candles(secid, candle_time)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_securities_secid ON securities(secid)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ml_predictions_secid ON ml_predictions(secid, prediction_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_reviews_secid_date ON reviews(secid, review_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_reviews_last_parsed ON reviews(secid, last_parsed_at)")

            await db.commit()
            self.logger.info("Database initialized")

    async def insert_candles(self, candles: List[Dict[str, Any]]):
        """Insert candles into database"""
        async with self._connect() as db:
            for candle in candles:
                try:
                    # Convert datetime to string if needed
                    candle_time = candle['time']
                    if isinstance(candle_time, datetime):
                        candle_time = candle_time.isoformat()

                    await db.execute("""
                        INSERT OR IGNORE INTO candles 
                        (secid, candle_open, candle_close, candle_low, candle_high, candle_volume, candle_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        candle['secid'],
                        candle['open'],
                        candle['close'],
                        candle['low'],
                        candle['high'],
                        candle['volume'],
                        candle_time
                    ))
                except Exception as e:
                    self.logger.error(f"Error inserting candle: {e}")
            await db.commit()

    async def get_candles(self, secid: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get candles for a security"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT secid, candle_open, candle_close, candle_low, candle_high, 
                       candle_volume, candle_time
                FROM candles
                WHERE secid = ? AND candle_time >= datetime('now', '-' || ? || ' days')
                ORDER BY candle_time ASC
            """, (secid, days)) as cursor:
                rows = await cursor.fetchall()
                result = []
                for row in rows:
                    row_dict = dict(row)
                    # Convert time string to datetime if needed
                    if isinstance(row_dict.get('candle_time'), str):
                        try:
                            row_dict['time'] = datetime.fromisoformat(
                                row_dict['candle_time'].replace('Z', '+00:00'))
                        except:
                            row_dict['time'] = datetime.fromisoformat(
                                row_dict['candle_time'])
                    else:
                        row_dict['time'] = row_dict.get('candle_time')
                    # Rename keys to match expected format
                    row_dict['open'] = row_dict.pop('candle_open')
                    row_dict['close'] = row_dict.pop('candle_close')
                    row_dict['low'] = row_dict.pop('candle_low')
                    row_dict['high'] = row_dict.pop('candle_high')
                    row_dict['volume'] = row_dict.pop('candle_volume')
                    result.append(row_dict)
                return result

    async def insert_security(self, security: Dict[str, Any]):
        """Insert or update security"""
        async with self._connect() as db:
            await db.execute("""
                INSERT OR REPLACE INTO securities 
                (secid, secname, isin, prevprice, currencyid, sectype, lotsize, prevdate, 
                 board, market, engine, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                security.get('secid'),
                security.get('secname'),
                security.get('isin'),
                security.get('prevprice'),
                security.get('currencyid', 'RUB'),
                security.get('sectype'),
                security.get('lotsize'),
                security.get('prevdate'),
                security.get('board'),
                security.get('market'),
                security.get('engine', 'stock')
            ))
            await db.commit()

    async def get_security_board_market(self, secid: str) -> Optional[Dict[str, Any]]:
        """Get board and market from database"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT board, market, engine FROM securities WHERE secid = ?
            """, (secid,)) as cursor:
                row = await cursor.fetchone()
                if row and row['board'] and row['market']:
                    return {
                        'board': row['board'],
                        'market': row['market'],
                        'engine': row['engine'] or 'stock'
                    }
                return None

    async def save_security_board_market(self, secid: str, board: str, market: str, engine: str = 'stock'):
        """Save board and market for security (upsert: the security row
        may not exist yet when this is called first)."""
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO securities (secid, board, market, engine, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(secid) DO UPDATE SET
                    board = excluded.board,
                    market = excluded.market,
                    engine = excluded.engine,
                    updated_at = CURRENT_TIMESTAMP
            """, (secid, board, market, engine))
            await db.commit()

    async def get_security(self, secid: str) -> Optional[Dict[str, Any]]:
        """Get security by secid"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM securities WHERE secid = ?
            """, (secid,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_prediction(self, secid: str, prediction_date: str,
                              predicted_price: float, confidence: float, model_type: str,
                              low_price: float = None, high_price: float = None):
        """Save ML prediction (median + optional q10/q90 zone)"""
        async with self._connect() as db:
            await db.execute("""
                INSERT OR REPLACE INTO ml_predictions
                (secid, prediction_date, predicted_price, low_price, high_price, confidence, model_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (secid, prediction_date, predicted_price, low_price, high_price, confidence, model_type))
            await db.commit()

    async def get_predictions(self, secid: str, days: int = 7) -> List[Dict[str, Any]]:
        """Get ML predictions for a security"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM ml_predictions
                WHERE secid = ? AND prediction_date >= date('now', '-' || ? || ' days')
                ORDER BY prediction_date ASC
            """, (secid, days)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def should_parse_reviews(self, secid: str) -> tuple:
        """Check if reviews should be parsed (not parsed today).
        Timestamps in parse_log are written by Python in local time,
        so the comparison with the local date is consistent."""
        async with self._connect() as db:
            async with db.execute("""
                SELECT last_parsed_at FROM parse_log WHERE secid = ?
            """, (secid,)) as cursor:
                row = await cursor.fetchone()
                if not row or not row[0]:
                    return None, True
                last_parsed = datetime.fromisoformat(row[0])
                today = datetime.now().date()
                return last_parsed.date(), last_parsed.date() < today

    async def insert_reviews(self, secid: str, reviews: List[Dict[str, Any]]):
        """Insert reviews into database"""
        async with self._connect() as db:
            for review in reviews:
                try:
                    review_text_ru = review.get('text', '').strip()
                    review_text_en = review.get('text_en', '').strip()
                    if not review_text_ru:
                        continue

                    review_img = review.get('img', '').strip() if review.get('img') else ''
                    review_date = review.get('date')
                    if isinstance(review_date, datetime):
                        review_date_str = review_date.date().isoformat()
                    elif isinstance(review_date, str):
                        review_date_str = review_date
                    else:
                        review_date_str = datetime.now().date().isoformat()
                    
                    # Create hash for uniqueness check
                    review_hash = hashlib.md5(f"{secid}:{review_text_ru}:{review_date_str}".encode('utf-8')).hexdigest()

                    await db.execute("""
                        INSERT OR IGNORE INTO reviews 
                        (secid, review_text_ru, review_text_en, review_img, review_date, review_hash, positive, neutral, negative, anger, anticipation, disgust, fear, joy, sadness, surprise, trust, source, last_parsed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        secid,
                        review_text_ru,
                        review_text_en,
                        review_img,
                        review_date_str,
                        review_hash,
                        review.get('positive', 0),
                        review.get('neutral', 0),
                        review.get('negative', 0),
                        review.get('anger', 0),
                        review.get('anticipation', 0),
                        review.get('disgust', 0),
                        review.get('fear', 0),
                        review.get('joy', 0),
                        review.get('sadness', 0),
                        review.get('surprise', 0),
                        review.get('trust', 0),
                        review.get('source', '')
                    ))
                except Exception as e:
                    self.logger.error(f"Error inserting review: {e}")
            await self._touch_parse_log(db, secid)
            await db.commit()

    @staticmethod
    async def _touch_parse_log(db, secid: str):
        await db.execute("""
            INSERT INTO parse_log (secid, last_parsed_at) VALUES (?, ?)
            ON CONFLICT(secid) DO UPDATE SET last_parsed_at = excluded.last_parsed_at
        """, (secid, datetime.now().isoformat()))

    async def update_date_reviews(self, secid: str):
        """Mark security as parsed now (works even when it has no reviews)"""
        async with self._connect() as db:
            await self._touch_parse_log(db, secid)
            await db.commit()

    async def get_reviews(self, secid: str, days: int = 7) -> List[Dict[str, Any]]:
        """Get reviews for a security from the last N days"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT *
                FROM reviews
                WHERE secid = ? AND review_date >= date('now', '-' || ? || ' days')
                ORDER BY review_date DESC
            """, (secid, days)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_mean_sentiment(self, secid: str, days: int = 14) -> Dict[str, Any]:
        """Mean positive/negative over recent reviews (for the sentiment veto)"""
        async with self._connect() as db:
            async with db.execute("""
                SELECT AVG(positive), AVG(negative), COUNT(*)
                FROM reviews
                WHERE secid = ? AND review_date >= date('now', '-' || ? || ' days')
            """, (secid, days)) as cursor:
                row = await cursor.fetchone()
                return {
                    'positive': row[0] or 0.0,
                    'negative': row[1] or 0.0,
                    'n': row[2] or 0,
                }

    # ---------------- Advisor: candles helpers ----------------

    async def get_last_candle_date(self, secid: str) -> Optional[str]:
        """Date (YYYY-MM-DD) of the newest stored candle, for incremental sync"""
        async with self._connect() as db:
            async with db.execute("""
                SELECT MAX(candle_time) FROM candles WHERE secid = ?
            """, (secid,)) as cursor:
                row = await cursor.fetchone()
                return row[0][:10] if row and row[0] else None

    async def get_closes(self, secid: str, days: int = 450) -> List[float]:
        """Close prices ascending for the last N days"""
        async with self._connect() as db:
            async with db.execute("""
                SELECT candle_close FROM candles
                WHERE secid = ? AND candle_time >= datetime('now', '-' || ? || ' days')
                ORDER BY candle_time ASC
            """, (secid, days)) as cursor:
                rows = await cursor.fetchall()
                return [r[0] for r in rows]

    async def get_latest_close(self, secid: str) -> Optional[Dict[str, Any]]:
        async with self._connect() as db:
            async with db.execute("""
                SELECT candle_close, candle_time FROM candles
                WHERE secid = ? ORDER BY candle_time DESC LIMIT 1
            """, (secid,)) as cursor:
                row = await cursor.fetchone()
                return {'close': row[0], 'time': row[1]} if row else None

    # ---------------- Advisor: reports & recommendations ----------------

    async def save_weekly_report(self, report: Dict[str, Any]) -> int:
        """Upsert report by (week_start, kind); returns report id"""
        async with self._connect() as db:
            await db.execute("""
                INSERT INTO weekly_reports
                (week_start, kind, created_at, status, regime_json, allocation_json,
                 evaluation_json, alarms_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(week_start, kind) DO UPDATE SET
                    created_at = excluded.created_at,
                    status = excluded.status,
                    regime_json = excluded.regime_json,
                    allocation_json = excluded.allocation_json,
                    evaluation_json = excluded.evaluation_json,
                    alarms_json = excluded.alarms_json
            """, (
                report['week_start'],
                report.get('kind', 'weekly'),
                report.get('created_at', datetime.now().isoformat()),
                report.get('status', 'ok'),
                json.dumps(report.get('regime'), ensure_ascii=False) if report.get('regime') is not None else None,
                json.dumps(report.get('allocation'), ensure_ascii=False) if report.get('allocation') is not None else None,
                json.dumps(report.get('evaluation'), ensure_ascii=False) if report.get('evaluation') is not None else None,
                json.dumps(report.get('alarms'), ensure_ascii=False) if report.get('alarms') is not None else None,
            ))
            async with db.execute("""
                SELECT id FROM weekly_reports WHERE week_start = ? AND kind = ?
            """, (report['week_start'], report.get('kind', 'weekly'))) as cursor:
                row = await cursor.fetchone()
            await db.commit()
            return row[0]

    async def save_recommendations(self, report_id: int, recommendations: List[Dict[str, Any]]):
        async with self._connect() as db:
            # A rerun may have a changed universe: drop rows for assets
            # that are no longer part of this report
            secids = [r['secid'] for r in recommendations]
            placeholders = ','.join('?' * len(secids))
            await db.execute(f"""
                DELETE FROM recommendations
                WHERE report_id = ? AND secid NOT IN ({placeholders})
            """, (report_id, *secids))
            for reco in recommendations:
                await db.execute("""
                    INSERT INTO recommendations
                    (report_id, secid, asset_class, action, components_json, price_at_reco,
                     horizon_days, forecast_low, forecast_median, forecast_high)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(report_id, secid) DO UPDATE SET
                        asset_class = excluded.asset_class,
                        action = excluded.action,
                        components_json = excluded.components_json,
                        price_at_reco = excluded.price_at_reco,
                        horizon_days = excluded.horizon_days,
                        forecast_low = excluded.forecast_low,
                        forecast_median = excluded.forecast_median,
                        forecast_high = excluded.forecast_high
                """, (
                    report_id,
                    reco['secid'],
                    reco.get('asset_class', 'equity'),
                    reco['action'],
                    json.dumps(reco.get('components', {}), ensure_ascii=False),
                    reco.get('price_at_reco'),
                    reco.get('horizon_days', 7),
                    reco.get('forecast_low'),
                    reco.get('forecast_median'),
                    reco.get('forecast_high'),
                ))
            await db.commit()

    @staticmethod
    def _report_row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        report = dict(row)
        for field in ('regime_json', 'allocation_json', 'evaluation_json', 'alarms_json'):
            key = field.replace('_json', '')
            raw = report.pop(field, None)
            report[key] = json.loads(raw) if raw else None
        return report

    async def get_reports(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Reports newest-first with recommendation counts"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT r.*,
                       (SELECT COUNT(*) FROM recommendations WHERE report_id = r.id) AS n_recommendations,
                       (SELECT COUNT(*) FROM recommendations WHERE report_id = r.id AND action = 'BUY') AS n_buy,
                       (SELECT COUNT(*) FROM recommendations WHERE report_id = r.id AND action = 'SELL') AS n_sell
                FROM weekly_reports r
                ORDER BY r.week_start DESC, r.kind DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)) as cursor:
                rows = await cursor.fetchall()
                return [self._report_row_to_dict(row) for row in rows]

    async def get_report(self, report_id: int) -> Optional[Dict[str, Any]]:
        """Report with its recommendations"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM weekly_reports WHERE id = ?
            """, (report_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                report = self._report_row_to_dict(row)
            async with db.execute("""
                SELECT * FROM recommendations WHERE report_id = ?
                ORDER BY asset_class, action, secid
            """, (report_id,)) as cursor:
                recos = []
                for r in await cursor.fetchall():
                    reco = dict(r)
                    raw = reco.pop('components_json', None)
                    reco['components'] = json.loads(raw) if raw else {}
                    recos.append(reco)
                report['recommendations'] = recos
            return report

    async def get_latest_weekly_report(self) -> Optional[Dict[str, Any]]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT id FROM weekly_reports WHERE kind = 'weekly'
                ORDER BY week_start DESC LIMIT 1
            """) as cursor:
                row = await cursor.fetchone()
        return await self.get_report(row['id']) if row else None

    async def get_unevaluated_weekly_report(self, before_week: str) -> Optional[Dict[str, Any]]:
        """Latest weekly report started before `before_week` that still has
        unevaluated recommendations"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT DISTINCT r.id, r.week_start FROM weekly_reports r
                JOIN recommendations x ON x.report_id = r.id AND x.evaluated_at IS NULL
                WHERE r.kind = 'weekly' AND r.week_start < ?
                ORDER BY r.week_start DESC LIMIT 1
            """, (before_week,)) as cursor:
                row = await cursor.fetchone()
        return await self.get_report(row['id']) if row else None

    async def mark_recommendation_evaluated(self, reco_id: int, price_at_eval: float,
                                            realized_return: float, hit: Optional[int],
                                            in_zone: Optional[int]):
        async with self._connect() as db:
            await db.execute("""
                UPDATE recommendations
                SET evaluated_at = ?, price_at_eval = ?, realized_return = ?, hit = ?, in_zone = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), price_at_eval, realized_return, hit, in_zone, reco_id))
            await db.commit()

    async def set_report_evaluation(self, report_id: int, evaluation: Dict[str, Any]):
        async with self._connect() as db:
            await db.execute("""
                UPDATE weekly_reports SET evaluation_json = ? WHERE id = ?
            """, (json.dumps(evaluation, ensure_ascii=False), report_id))
            await db.commit()
