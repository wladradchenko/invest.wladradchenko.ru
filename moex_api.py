"""
MOEX API Client
"""
import aiohttp
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from cache import CacheManager


class MOEXClient:
    """MOEX ISS API client"""

    BASE_URL = "https://iss.moex.com/iss"

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.logger = logging.getLogger("moex")
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = cache_manager

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def query(self, method: str, use_cache: bool = True, cache_ttl_hours: int = 24, **kwargs) -> Optional[Dict]:
        """Query MOEX ISS API with caching"""
        url = f"{self.BASE_URL}/{method}.json"

        # Try cache first
        if use_cache and self.cache:
            cached_data = self.cache.get(
                url, kwargs, ttl_hours=cache_ttl_hours)
            if cached_data is not None:
                self.logger.debug(f"Cache hit: {method}")
                return cached_data

        # Fetch from API
        try:
            async with self.session.get(url, params=kwargs, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    # Cache the result
                    if use_cache and self.cache:
                        self.cache.set(url, data, kwargs)
                    return data
                else:
                    self.logger.error(f"MOEX API error: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error querying MOEX API: {e}")
            return None

    @staticmethod
    def flatten(data: Dict, blockname: str) -> List[Dict]:
        """Flatten MOEX API response"""
        if not data or blockname not in data:
            return []

        block = data[blockname]
        if 'columns' not in block or 'data' not in block:
            return []

        columns = block['columns']
        return [{columns[i]: row[i] for i in range(len(columns))} for row in block['data']]

    async def get_securities(self, board: str = "TQBR", market: str = "shares") -> List[Dict]:
        """Get list of securities"""
        data = await self.query(f"engines/stock/markets/{market}/boards/{board}/securities")
        if data:
            return self.flatten(data, "securities")
        return []

    async def get_security_info(self, secid: str, board: str = "TQBR", market: str = "shares") -> Optional[Dict]:
        """Get security information"""
        data = await self.query(f"engines/stock/markets/{market}/boards/{board}/securities/{secid}")
        if data:
            securities = self.flatten(data, "securities")
            return securities[0] if securities else None
        return None

    async def get_candles(self, secid: str, board: str = "TQBR", market: str = "shares",
                          interval: int = 24, days: int = 30) -> List[Dict]:
        """
        Get candles for security
        interval: 1 (1 min), 10 (10 min), 60 (1 hour), 24 (1 day), 7 (1 week), 31 (1 month)
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        data = await self.query(
            f"engines/stock/markets/{market}/boards/{board}/securities/{secid}/candles",
            interval=interval,
            from_=start_date.strftime("%Y-%m-%d"),
            till=end_date.strftime("%Y-%m-%d")
        )

        if data:
            candles = self.flatten(data, "candles")
            # Convert to our format
            result = []
            for candle in candles:
                try:
                    begin_str = candle.get('begin', '')
                    if begin_str:
                        # Handle different date formats
                        begin_str = begin_str.replace('Z', '+00:00')
                        if '+' not in begin_str and 'T' in begin_str:
                            begin_str += '+00:00'
                        candle_time = datetime.fromisoformat(begin_str)
                    else:
                        candle_time = datetime.now()

                    result.append({
                        'secid': secid,
                        'open': float(candle.get('open', 0)) if candle.get('open') else 0.0,
                        'close': float(candle.get('close', 0)) if candle.get('close') else 0.0,
                        'low': float(candle.get('low', 0)) if candle.get('low') else 0.0,
                        'high': float(candle.get('high', 0)) if candle.get('high') else 0.0,
                        'volume': int(candle.get('volume', 0)) if candle.get('volume') else 0,
                        'time': candle_time
                    })
                except Exception as e:
                    self.logger.error(
                        f"Error parsing candle: {e}, candle: {candle}")
                    continue
            return result
        return []

    async def get_indexes(self) -> List[Dict]:
        """Get list of indexes (cached for 7 days)"""
        data = await self.query("statistics/engines/stock/markets/index/analytics",
                                use_cache=True, cache_ttl_hours=168)  # 7 days
        if data:
            return self.flatten(data, "indices")
        return []

    async def get_index_securities(self, indexid: str, limit: int = 100) -> List[Dict]:
        """Get securities in an index (cached for 7 days)"""
        data = await self.query(
            f"statistics/engines/stock/markets/index/analytics/{indexid}",
            use_cache=True,
            cache_ttl_hours=168,  # 7 days
            limit=limit
        )
        if data:
            return self.flatten(data, "analytics")
        return []

    async def get_last_price(self, secid: str, board: str = None, market: str = None) -> Optional[float]:
        """Get last price for security"""
        # If board/market not provided, get them automatically
        if not board or not market:
            board_market = await self.get_security_board_market(secid)
            if board_market:
                board = board_market.get('board', 'TQBR')
                market = board_market.get('market', 'shares')
            else:
                # Fallback to defaults
                board = board or 'TQBR'
                market = market or 'shares'

        data = await self.query(f"engines/stock/markets/{market}/boards/{board}/securities/{secid}")
        if data:
            securities = self.flatten(data, "securities")
            if securities:
                prevprice = securities[0].get('PREVPRICE')
                if prevprice:
                    return float(prevprice)
        return None

    # Справочники
    async def get_security_types(self) -> List[Dict]:
        """Get security types"""
        data = await self.query("securitytypes")
        if data:
            return self.flatten(data, "securitytypes")
        return []

    async def get_security_groups(self, trade_engine: str = "stock") -> List[Dict]:
        """Get security groups"""
        data = await self.query("securitygroups", trade_engine=trade_engine)
        if data:
            return self.flatten(data, "securitygroups")
        return []

    async def get_engines(self) -> List[Dict]:
        """Get trading engines"""
        data = await self.query("engines")
        if data:
            return self.flatten(data, "engines")
        return []

    async def get_markets(self, engine: str = "stock") -> List[Dict]:
        """Get markets for engine"""
        data = await self.query(f"engines/{engine}/markets")
        if data:
            return self.flatten(data, "markets")
        return []

    async def get_boards(self, engine: str = "stock", market: str = "shares") -> List[Dict]:
        """Get boards for market"""
        data = await self.query(f"engines/{engine}/markets/{market}/boards")
        if data:
            return self.flatten(data, "boards")
        return []

    # Дивиденды
    async def get_dividends(self, secid: str) -> List[Dict]:
        """Get dividends for security"""
        data = await self.query(f"securities/{secid}/dividends")
        if data:
            return self.flatten(data, "dividends")
        return []

    # Купоны
    async def get_coupons(self, secid: str) -> List[Dict]:
        """Get coupons for bond"""
        data = await self.query(f"securities/{secid}/bondization", iss_meta="off")
        if data:
            coupons = self.flatten(data, "coupons")
            return coupons
        return []

    # Новости
    async def get_news(self, lang: str = "ru", limit: int = 10) -> List[Dict]:
        """Get exchange news"""
        data = await self.query("news", lang=lang, limit=limit)
        if data:
            return self.flatten(data, "news")
        return []

    async def get_events(self, lang: str = "ru", limit: int = 10) -> List[Dict]:
        """Get exchange events"""
        data = await self.query("events", lang=lang, limit=limit)
        if data:
            return self.flatten(data, "events")
        return []

    # История доходностей
    async def get_yields(self, secid: str, engine: str = "stock", market: str = "bonds",
                         from_date: str = None, till_date: str = None) -> List[Dict]:
        """Get yield history for bond"""
        if not from_date:
            from_date = (datetime.now() - timedelta(days=365)
                         ).strftime("%Y-%m-%d")
        if not till_date:
            till_date = datetime.now().strftime("%Y-%m-%d")

        data = await self.query(
            f"history/engines/{engine}/markets/{market}/yields/{secid}",
            from_=from_date,
            till=till_date
        )
        if data:
            return self.flatten(data, "history")
        return []

    # Спецификация инструмента
    async def get_security_specification(self, secid: str) -> Dict:
        """Get full security specification"""
        data = await self.query(f"securities/{secid}")
        if data:
            description = self.flatten(data, "description")
            boards = self.flatten(data, "boards")
            return {
                'description': description[0] if description else {},
                'boards': boards
            }
        return {}

    async def get_security_board_market(self, secid: str, db=None) -> Optional[Dict]:
        """
        Get primary board and market for security
        Returns: {'board': 'TQBR', 'market': 'shares', 'engine': 'stock'} or None

        First checks database, then API with long-term cache (1 year)
        """
        # First try to get from database
        if db:
            db_result = await db.get_security_board_market(secid)
            if db_result:
                return db_result

        # If not in DB, fetch from API with long-term cache (1 year = 8760 hours)
        # Data changes rarely, so we cache for a long time
        data = await self.query(f"securities/{secid}", use_cache=True, cache_ttl_hours=8760)
        if not data:
            return None

        boards = self.flatten(data, "boards")
        if not boards:
            return None

        # Find primary traded board (is_primary=1, is_traded=1, engine=stock)
        primary_board = None
        for board in boards:
            is_primary = board.get('is_primary') in [1, '1', True]
            is_traded = board.get('is_traded') in [1, '1', True]
            engine = board.get('engine', '').lower()

            if is_primary and is_traded and engine == 'stock':
                primary_board = board
                break

        # If no primary, find any traded board on stock engine
        if not primary_board:
            for board in boards:
                is_traded = board.get('is_traded') in [1, '1', True]
                engine = board.get('engine', '').lower()

                if is_traded and engine == 'stock':
                    primary_board = board
                    break

        if not primary_board:
            return None

        boardid = primary_board.get('boardid')
        market = primary_board.get('market')

        if not boardid or not market:
            return None

        result = {
            'board': boardid,
            'market': market,
            'engine': primary_board.get('engine', 'stock')
        }

        # Save to database if provided
        if db:
            await db.save_security_board_market(secid, boardid, market, result['engine'])

        return result

    # История по сессиям
    async def get_history_by_sessions(self, secid: str, engine: str = "stock",
                                      market: str = "shares", board: str = "TQBR",
                                      from_date: str = None, till_date: str = None) -> List[Dict]:
        """Get history by trading sessions"""
        if not from_date:
            from_date = (datetime.now() - timedelta(days=30)
                         ).strftime("%Y-%m-%d")
        if not till_date:
            till_date = datetime.now().strftime("%Y-%m-%d")

        data = await self.query(
            f"history/engines/{engine}/markets/{market}/boards/{board}/securities/{secid}/sessions",
            from_=from_date,
            till=till_date
        )
        if data:
            return self.flatten(data, "history")
        return []

    # Поиск бумаг
    async def search_securities(self, query: str, lang: str = "ru") -> List[Dict]:
        """Search securities by query"""
        data = await self.query("securities", q=query, lang=lang)
        if data:
            return self.flatten(data, "securities")
        return []

    # Индексы в которые входит бумага
    async def get_security_indices(self, secid: str) -> List[Dict]:
        """Get indices that include this security"""
        data = await self.query(f"securities/{secid}/indices")
        if data:
            return self.flatten(data, "indices")
        return []

    # Аналитические показатели индекса
    async def get_index_analytics(self, indexid: str, date: str = None) -> List[Dict]:
        """Get index analytics for date"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        data = await self.query(
            f"statistics/engines/stock/markets/index/analytics/{indexid}",
            date=date
        )
        if data:
            return self.flatten(data, "analytics")
        return []
