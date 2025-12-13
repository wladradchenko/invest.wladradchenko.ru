"""
Main Application - MOEX Investment Analyzer
"""
import aiohttp
from aiohttp import web
import gettext
import asyncio
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import aiohttp_jinja2
import jinja2
from tqdm import tqdm

from database import Database
from moex_api import MOEXClient
from ml_models import MLPredictor
from text_models import TextAnalyser
from indicators import IndicatorAnalyzer
from cache import CacheManager
from parsers import ReviewsParser

"""
pybabel extract -F babel.cfg -o messages.pot .
pybabel init -i messages.pot -d translations -l ru
pybabel update -i messages.pot -d translations -l ru
pybabel compile -d translations
"""


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("app")


class InvestmentAnalyzer:
    """Main application class"""

    def __init__(self):
        self.db = Database()
        print("Loading neural models before start")
        self.text_predictor = TextAnalyser()
        self.ml_predictor = MLPredictor()
        self.indicator_analyzer = IndicatorAnalyzer()
        self.cache = CacheManager()
        self.reviews_parser = ReviewsParser()

    async def init(self):
        """Initialize application"""
        await self.db.init_db()
        self.cache.clear_expired()  # Clean old cache on startup
        logger.info("Application initialized")

    async def cleanup(self):
        """Cleanup resources"""
        logger.info("Application cleaned up")

    async def get_security_data(self, secid: str, days: int = 60) -> Dict:
        """Get security data with indicators and predictions"""
        try:
            # Get candles from database or API
            candles = await self.db.get_candles(secid, days=days)

            if not candles or len(candles) < 20:
                # Fetch from MOEX API
                async with MOEXClient(cache_manager=self.cache) as client:
                    # Get board and market for this security (check DB first, then API)
                    board_market = await client.get_security_board_market(secid, db=self.db)
                    if not board_market:
                        return {'error': 'Не удалось определить режим торговли для бумаги'}

                    board = board_market.get('board', 'TQBR')
                    market = board_market.get('market', 'shares')
                    engine = board_market.get('engine', 'stock')

                    # Save to DB for future use
                    await self.db.save_security_board_market(secid, board, market, engine)

                    new_candles = await client.get_candles(
                        secid,
                        board=board,
                        market=market,
                        days=days,
                        interval=24
                    )
                    if new_candles:
                        await self.db.insert_candles(new_candles)
                        candles = new_candles

            if not candles:
                return {'error': 'Не удалось получить данные'}

            # Get security info
            security = await self.db.get_security(secid)
            if not security:
                async with MOEXClient(cache_manager=self.cache) as client:
                    # Get board and market for this security (check DB first, then API)
                    board_market = await client.get_security_board_market(secid, db=self.db)
                    if board_market:
                        board = board_market.get('board', 'TQBR')
                        market = board_market.get('market', 'shares')
                        engine = board_market.get('engine', 'stock')
                        info = await client.get_security_info(secid, board=board, market=market)
                    else:
                        # Fallback to default
                        board = 'TQBR'
                        market = 'shares'
                        engine = 'stock'
                        info = await client.get_security_info(secid)

                    if info:
                        await self.db.insert_security({
                            'secid': secid,
                            'secname': info.get('SECNAME', secid),
                            'isin': info.get('ISIN'),
                            'prevprice': float(info.get('PREVPRICE', 0)) if info.get('PREVPRICE') else None,
                            'currencyid': info.get('CURRENCYID', 'RUB'),
                            'sectype': info.get('SECTYPE'),
                            'lotsize': int(info.get('LOTSIZE', 1)) if info.get('LOTSIZE') else 1,
                            'prevdate': datetime.now().date().isoformat(),
                            'board': board,
                            'market': market,
                            'engine': engine
                        })
                        security = await self.db.get_security(secid)

            # Calculate indicators
            indicators = self.indicator_analyzer.analyze_all(candles)

            # ML predictions
            predictions, confidence = self.ml_predictor.predict(
                candles, days=7)

            # Save predictions
            if predictions:
                for i, pred_price in enumerate(predictions):
                    pred_date = (datetime.now() +
                                 timedelta(days=i+1)).date().isoformat()
                    await self.db.save_prediction(
                        secid, pred_date, pred_price, confidence, 'LSTM'
                    )

            return {
                'security': security,
                'candles': candles[-60:],  # Last 60 candles for better charts
                'indicators': indicators,
                'predictions': [
                    {
                        'date': (datetime.now() + timedelta(days=i+1)).date().isoformat(),
                        'price': round(price, 2)
                    }
                    for i, price in enumerate(predictions)
                ],
                'confidence': round(confidence, 2) if confidence else 0.0
            }
        except Exception as e:
            logger.error(f"Error getting security data: {e}")
            return {'error': str(e)}

    async def get_indexes(self) -> List[Dict]:
        """Get available indexes"""
        try:
            async with MOEXClient(cache_manager=self.cache) as client:
                indexes = await client.get_indexes()
                # Filter current month indexes
                current_month = datetime.now().month
                current_year = datetime.now().year
                filtered = []
                for idx in indexes:
                    till_date = idx.get('till')
                    if till_date:
                        try:
                            dt = datetime.strptime(till_date, '%Y-%m-%d')
                            if dt.month == current_month and dt.year == current_year:
                                filtered.append(idx)
                        except:
                            pass
                return filtered[:50]  # Limit to 50
        except Exception as e:
            logger.error(f"Error getting indexes: {e}")
            return []

    async def get_index_securities(self, indexid: str) -> List[Dict]:
        """Get securities in an index"""
        try:
            async with MOEXClient(cache_manager=self.cache) as client:
                securities = await client.get_index_securities(indexid, limit=100)
                return securities
        except Exception as e:
            logger.error(f"Error getting index securities: {e}")
            return []

    async def should_parse_reviews(self, secid: str):
        try:
            secid_upper = secid.upper()

            # Check if we need to parse (not parsed today)
            _, should_parse = await self.db.should_parse_reviews(secid_upper)
            return should_parse
        except Exception as e:
            logger.error(f"Error getting reviews for {secid}: {e}")
            return True

    async def get_reviews(self, secid: str) -> List[Dict]:
        """Get reviews for a security. Parses if not parsed today."""
        try:
            secid_upper = secid.upper()

            # Check if we need to parse (not parsed today)
            last_parsed, should_parse = await self.db.should_parse_reviews(secid_upper)

            if should_parse:
                logger.info(f"Parsing reviews for {secid_upper}")
                # Parse reviews from all sources
                reviews = await self.reviews_parser.parse_reviews(secid_upper, last_parsed)
                analysis_reviews = []
                for review in tqdm(reviews, desc=f"Analysis review of {secid_upper}"):
                    analysis = await self.text_predictor(text=review.get("text"), img_path=review.get("img"))
                    if analysis is not None:
                        analysis_reviews.append({**review, **analysis})

                # Save to database
                if analysis_reviews:
                    await self.db.insert_reviews(secid_upper, reviews)
                    logger.info(f"Saved {len(reviews)} reviews for {secid_upper}")
                if not analysis_reviews and reviews:
                    await self.db.update_date_reviews(secid_upper)
                    logger.info(f"Not interest reviews, but updated date for {secid_upper}")

            # Get reviews from database (for current week)
            db_reviews = await self.db.get_reviews(secid_upper, days=7)

            # Convert to format without source
            result = [
                {
                    'text': review.get('review_text', ''),
                    'date': review.get('review_date', '')
                }
                for review in db_reviews
            ]

            return result
        except Exception as e:
            logger.error(f"Error getting reviews for {secid}: {e}")
            return []


# Global app instance
analyzer = InvestmentAnalyzer()


def setup_i18n(app, locale='en'):
    translations = gettext.translation(
        'messages', localedir='translations', languages=[locale], fallback=True
    )
    app['translator'] = translations
    return translations.gettext


async def set_lang(request):
    lang = request.match_info['lang']
    resp = web.HTTPFound("/")
    resp.set_cookie("lang", lang)
    return resp


@aiohttp_jinja2.template('index.html')
async def index_handler(request: web.Request) -> web.Response:
    """Main page handler"""
    locale = request.cookies.get("lang", "en")
    _ = setup_i18n(request.app, locale)
    return {"_": _, "lang": locale}


async def api_portfolio_calculate_handler(request: web.Request) -> web.Response:
    """Calculate portfolio returns"""
    try:
        data = await request.json()
        capital = float(data.get('capital', 0))
        # List of {secid, weight, price}
        securities = data.get('securities', [])

        if capital <= 0 or not securities:
            return web.json_response({'error': 'Invalid input'}, status=400)

        # Calculate portfolio
        total_weight = sum(s.get('weight', 0) for s in securities)
        if total_weight == 0:
            return web.json_response({'error': 'Total weight must be > 0'}, status=400)

        portfolio_value = 0
        portfolio_yield = 0

        for sec in securities:
            weight = sec.get('weight', 0) / total_weight
            price = sec.get('price', 0)
            allocation = capital * weight
            shares = allocation / price if price > 0 else 0

            # Get security data for yield calculation
            secid = sec.get('secid')
            if secid:
                sec_data = await analyzer.get_security_data(secid, days=30)
                # Simple yield calculation (can be improved)
                if sec_data and sec_data.get('indicators'):
                    # Use some indicator or prediction for yield estimate
                    pass

            portfolio_value += shares * price

        # Calculate expected yield based on predictions if available
        total_predicted_yield = 0
        for sec in securities:
            secid = sec.get('secid')
            if secid:
                try:
                    sec_data = await analyzer.get_security_data(secid, days=30)
                    if sec_data and sec_data.get('predictions'):
                        # Use average prediction change
                        predictions = sec_data.get('predictions', [])
                        if predictions:
                            current_price = sec.get('price', 0)
                            avg_prediction = sum(
                                p.get('price', current_price) for p in predictions) / len(predictions)
                            if current_price > 0:
                                sec_yield = (
                                    (avg_prediction - current_price) / current_price) * 100
                                weight = sec.get('weight', 0) / total_weight
                                total_predicted_yield += sec_yield * weight
                except:
                    pass

        # Use predicted yield if available, otherwise simple calculation
        if total_predicted_yield != 0:
            portfolio_yield = total_predicted_yield
        else:
            portfolio_yield = ((portfolio_value - capital) /
                               capital * 100) if capital > 0 else 0

        return web.json_response({
            'capital': capital,
            'portfolio_value': round(portfolio_value, 2),
            'expected_yield': round(portfolio_yield, 2),
            'securities': securities
        })
    except Exception as e:
        logger.error(f"Error calculating portfolio: {e}")
        return web.json_response({'error': str(e)}, status=500)


def serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, np.generic):  # np.float64, np.int64
        return obj.item()

    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [serialize(i) for i in obj]

    if isinstance(obj, tuple):
        return [serialize(i) for i in obj]

    return obj


async def api_security_handler(request: web.Request) -> web.Response:
    """API endpoint for security data"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    days = int(request.query.get('days', 60))
    data = await analyzer.get_security_data(secid, days=days)
    data = serialize(data)
    return web.json_response(data)


async def api_indexes_handler(request: web.Request) -> web.Response:
    """API endpoint for indexes"""
    indexes = await analyzer.get_indexes()
    return web.json_response(indexes)


async def api_index_securities_handler(request: web.Request) -> web.Response:
    """API endpoint for index securities"""
    indexid = request.match_info.get('indexid', '')
    if not indexid:
        return web.json_response({'error': 'indexid required'}, status=400)

    securities = await analyzer.get_index_securities(indexid)
    return web.json_response(securities)


async def search_securities_handler(request: web.Request) -> web.Response:
    """Search securities"""
    query = request.query.get('q', '').upper()
    if not query or len(query) < 2:
        return web.json_response([])

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            all_securities = await client.get_securities()
            # Simple search by SECID or SECNAME
            results = [
                s for s in all_securities
                if query in s.get('SECID', '').upper() or query in s.get('SECNAME', '').upper()
            ][:20]  # Limit to 20 results
            return web.json_response(results)
    except Exception as e:
        logger.error(f"Error searching securities: {e}")
        return web.json_response([])


async def api_dividends_handler(request: web.Request) -> web.Response:
    """API endpoint for dividends"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            dividends = await client.get_dividends(secid)
            return web.json_response(serialize(dividends))
    except Exception as e:
        logger.error(f"Error getting dividends: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def api_coupons_handler(request: web.Request) -> web.Response:
    """API endpoint for coupons"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            coupons = await client.get_coupons(secid)
            return web.json_response(serialize(coupons))
    except Exception as e:
        logger.error(f"Error getting coupons: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def api_yields_handler(request: web.Request) -> web.Response:
    """API endpoint for yields"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    from_date = request.query.get('from')
    till_date = request.query.get('till')

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            yields = await client.get_yields(secid, from_date=from_date, till_date=till_date)
            return web.json_response(serialize(yields))
    except Exception as e:
        logger.error(f"Error getting yields: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def api_news_handler(request: web.Request) -> web.Response:
    """API endpoint for news"""
    limit = int(request.query.get('limit', 10))
    lang = request.query.get('lang', 'ru')

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            news = await client.get_news(lang=lang, limit=limit)
            return web.json_response(serialize(news))
    except Exception as e:
        logger.error(f"Error getting news: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def api_specification_handler(request: web.Request) -> web.Response:
    """API endpoint for security specification"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            spec = await client.get_security_specification(secid)
            return web.json_response(serialize(spec))
    except Exception as e:
        logger.error(f"Error getting specification: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def api_history_sessions_handler(request: web.Request) -> web.Response:
    """API endpoint for history by sessions"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    from_date = request.query.get('from')
    till_date = request.query.get('till')
    engine = request.query.get('engine', 'stock')
    market = request.query.get('market', 'shares')
    board = request.query.get('board', 'TQBR')

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            history = await client.get_history_by_sessions(
                secid, engine=engine, market=market, board=board,
                from_date=from_date, till_date=till_date
            )
            return web.json_response(serialize(history))
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def api_reviews_handler(request: web.Request) -> web.Response:
    """API endpoint for reviews"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    try:
        reviews = await analyzer.get_reviews(secid)
        text = json.dumps(reviews, ensure_ascii=False)
        return web.Response(text=text, content_type="application/json", charset="utf-8")
    except Exception as e:
        logger.error(f"Error getting reviews: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def api_should_parse_reviews_handler(request: web.Request) -> web.Response:
    """API endpoint for should parse reviews"""
    secid = request.match_info.get('secid', '').upper()
    if not secid:
        return web.json_response({'error': 'secid required'}, status=400)

    try:
        should_parse = await analyzer.should_parse_reviews(secid)
        return web.json_response({'should_parse': should_parse}, status=200)
    except Exception as e:
        logger.error(f"Error getting reviews: {e}")
        return web.json_response({'error': str(e)}, status=500)


def create_app() -> web.Application:
    """Create and configure application"""
    app = web.Application()
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('static/html'))

    # Routes
    app.router.add_get('/', index_handler)
    app.router.add_get('/lang/{lang}', set_lang)
    app.router.add_get('/api/indexes', api_indexes_handler)
    app.router.add_get('/api/index/{indexid}/securities', api_index_securities_handler)
    app.router.add_get('/api/security/{secid}', api_security_handler)
    app.router.add_get('/api/security/{secid}/dividends', api_dividends_handler)
    app.router.add_get('/api/security/{secid}/coupons', api_coupons_handler)
    app.router.add_get('/api/security/{secid}/yields', api_yields_handler)
    app.router.add_get('/api/security/{secid}/specification', api_specification_handler)
    app.router.add_get('/api/security/{secid}/history/sessions', api_history_sessions_handler)
    app.router.add_get('/api/security/{secid}/reviews', api_reviews_handler)
    app.router.add_get('/api/security/{secid}/reviews/meta', api_should_parse_reviews_handler)
    app.router.add_get('/api/news', api_news_handler)
    app.router.add_get('/api/search', search_securities_handler)
    app.router.add_post('/api/portfolio/calculate', api_portfolio_calculate_handler)

    # Static files
    app.router.add_static('/static/', path='static/', name='static')

    # Startup and cleanup
    async def on_startup(app):
        await analyzer.init()

    async def on_cleanup(app):
        await analyzer.cleanup()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


if __name__ == '__main__':
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=8080)
