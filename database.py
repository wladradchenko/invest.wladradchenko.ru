"""
SQLite Database Accessor
"""
import aiosqlite
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
import json


class Database:
    """SQLite database accessor"""

    def __init__(self, db_path: str = "moex_data.db"):
        self.db_path = db_path
        self.logger = logging.getLogger("database")

    async def init_db(self):
        """Initialize database tables"""
        async with aiosqlite.connect(self.db_path) as db:
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
                    confidence REAL,
                    model_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(secid, prediction_date, model_type)
                )
            """)

            # Create indexes for performance
            await db.execute("CREATE INDEX IF NOT EXISTS idx_candles_secid_time ON candles(secid, candle_time)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_securities_secid ON securities(secid)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ml_predictions_secid ON ml_predictions(secid, prediction_date)")

            await db.commit()
            self.logger.info("Database initialized")

    async def insert_candles(self, candles: List[Dict[str, Any]]):
        """Insert candles into database"""
        async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
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
        """Save board and market for security"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE securities 
                SET board = ?, market = ?, engine = ?, updated_at = CURRENT_TIMESTAMP
                WHERE secid = ?
            """, (board, market, engine, secid))
            await db.commit()

    async def get_security(self, secid: str) -> Optional[Dict[str, Any]]:
        """Get security by secid"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM securities WHERE secid = ?
            """, (secid,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_prediction(self, secid: str, prediction_date: str,
                              predicted_price: float, confidence: float, model_type: str):
        """Save ML prediction"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO ml_predictions
                (secid, prediction_date, predicted_price, confidence, model_type)
                VALUES (?, ?, ?, ?, ?)
            """, (secid, prediction_date, predicted_price, confidence, model_type))
            await db.commit()

    async def get_predictions(self, secid: str, days: int = 7) -> List[Dict[str, Any]]:
        """Get ML predictions for a security"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM ml_predictions
                WHERE secid = ? AND prediction_date >= date('now', '-' || ? || ' days')
                ORDER BY prediction_date ASC
            """, (secid, days)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
