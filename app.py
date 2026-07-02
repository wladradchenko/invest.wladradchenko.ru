"""
Main Application - MOEX Investment Analyzer (Quart web process)

The web process is intentionally light: no heavy neural models are loaded
here. Review parsing/analysis and the weekly advisor run in the celery
worker (see tasks.py / advisor.py); job state is shared through redis.
"""
import json
import gettext
import logging
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import redis.asyncio as aioredis
from quart import Quart, Response, jsonify, redirect, render_template, request, send_from_directory

from cache import CacheManager
from celery_app import app as celery
from database import Database
from indicators import IndicatorAnalyzer
from jobstore import JobStore, new_job
from ml_models import MLPredictor
from moex_api import MOEXClient
from settings import CONFIG, REDIS_URL

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
    """Data access + light analytics for the web process"""

    def __init__(self):
        self.db = Database()
        self.ml_predictor = MLPredictor()
        self.indicator_analyzer = IndicatorAnalyzer()
        self.cache = CacheManager()

    async def init(self):
        await self.db.init_db()
        self.cache.clear_expired()
        logger.info("Application initialized")

    async def get_security_data(self, secid: str, days: int = 60) -> Dict:
        """Get security data with indicators and forecast zone"""
        try:
            # Get candles from database or API
            candles = await self.db.get_candles(secid, days=days)

            if not candles or len(candles) < 20:
                # Fetch from MOEX API
                async with MOEXClient(cache_manager=self.cache) as client:
                    board_market = await client.get_security_board_market(secid, db=self.db)
                    if not board_market:
                        return {'error': 'Не удалось определить режим торговли для бумаги'}

                    board = board_market.get('board', 'TQBR')
                    market = board_market.get('market', 'shares')
                    engine = board_market.get('engine', 'stock')

                    new_candles = await client.get_candles(
                        secid,
                        board=board,
                        market=market,
                        engine=engine,
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
                    board_market = await client.get_security_board_market(secid, db=self.db)
                    if board_market:
                        board = board_market.get('board', 'TQBR')
                        market = board_market.get('market', 'shares')
                        engine = board_market.get('engine', 'stock')
                        info = await client.get_security_info(secid, board=board, market=market)
                    else:
                        board, market, engine = 'TQBR', 'shares', 'stock'
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

            # Quantile price zone (Chronos-Bolt; SMA fallback)
            forecast, confidence, model_type = self.ml_predictor.predict(
                candles, days=7)
            medians = forecast.get('median', [])

            # Save predictions
            for i, pred_price in enumerate(medians):
                pred_date = (datetime.now() +
                             timedelta(days=i+1)).date().isoformat()
                await self.db.save_prediction(
                    secid, pred_date, pred_price, confidence, model_type,
                    low_price=forecast['low'][i], high_price=forecast['high'][i]
                )

            return {
                'security': security,
                'candles': candles[-60:],  # Last 60 candles for better charts
                'indicators': indicators,
                'predictions': [
                    {
                        'date': (datetime.now() + timedelta(days=i+1)).date().isoformat(),
                        'price': round(price, 2),
                        'low': round(forecast['low'][i], 2),
                        'high': round(forecast['high'][i], 2)
                    }
                    for i, price in enumerate(medians)
                ],
                'confidence': round(confidence, 2) if confidence else 0.0,
                'model_type': model_type
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
                        except Exception:
                            pass
                return filtered[:50]  # Limit to 50
        except Exception as e:
            logger.error(f"Error getting indexes: {e}")
            return []

    async def get_index_securities(self, indexid: str) -> List[Dict]:
        """Get securities in an index"""
        try:
            async with MOEXClient(cache_manager=self.cache) as client:
                return await client.get_index_securities(indexid, limit=100)
        except Exception as e:
            logger.error(f"Error getting index securities: {e}")
            return []

    async def get_reviews(self, secid: str) -> List[Dict]:
        """Get reviews for a security from database only (no parsing)"""
        try:
            db_reviews = await self.db.get_reviews(secid.upper(), days=7)

            result = []
            for review in db_reviews:
                img_path = review.get('review_img', '')
                img_path = img_path.replace('\\', '/')
                if '/media' in img_path:
                    img_path = img_path[img_path.index('/media'):]
                else:
                    img_path = ''

                result.append({
                    'text': review.get('review_text_ru', ''),
                    'text_en': review.get('review_text_en', ''),
                    'img': img_path,
                    'date': review.get('review_date', ''),
                    'positive': review.get('positive', 0),
                    'neutral': review.get('neutral', 0),
                    'negative': review.get('negative', 0),
                    'anger': review.get('anger', 0),
                    'anticipation': review.get('anticipation', 0),
                    'disgust': review.get('disgust', 0),
                    'fear': review.get('fear', 0),
                    'joy': review.get('joy', 0),
                    'sadness': review.get('sadness', 0),
                    'surprise': review.get('surprise', 0),
                    'trust': review.get('trust', 0),
                })

            return result
        except Exception as e:
            logger.error(f"Error getting reviews for {secid}: {e}")
            return []


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


def json_response(data, status: int = 200) -> Response:
    return Response(
        json.dumps(serialize(data), ensure_ascii=False),
        status=status,
        content_type="application/json; charset=utf-8",
    )


analyzer = InvestmentAnalyzer()
app = Quart(
    __name__,
    static_folder='static',
    static_url_path='/static',
    template_folder='static/html',
)
job_store: JobStore = None


def setup_i18n(locale='en'):
    translations = gettext.translation(
        'messages', localedir='translations', languages=[locale], fallback=True
    )
    return translations.gettext


@app.before_serving
async def on_startup():
    global job_store
    await analyzer.init()
    job_store = JobStore(aioredis.from_url(REDIS_URL))


@app.route('/')
async def index_handler():
    locale = request.cookies.get("lang", "en")
    _ = setup_i18n(locale)
    return await render_template('index.html', _=_, lang=locale)


@app.route('/lang/<lang>')
async def set_lang(lang):
    resp = redirect("/")
    resp.set_cookie("lang", lang)
    return resp


@app.route('/media/<path:filename>')
async def media_handler(filename):
    return await send_from_directory('media', filename)


@app.route('/api/indexes')
async def api_indexes_handler():
    return json_response(await analyzer.get_indexes())


@app.route('/api/index/<indexid>/securities')
async def api_index_securities_handler(indexid):
    return json_response(await analyzer.get_index_securities(indexid))


@app.route('/api/security/<secid>')
async def api_security_handler(secid):
    days = int(request.args.get('days', 60))
    data = await analyzer.get_security_data(secid.upper(), days=days)
    return json_response(data)


@app.route('/api/security/<secid>/dividends')
async def api_dividends_handler(secid):
    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            return json_response(await client.get_dividends(secid.upper()))
    except Exception as e:
        logger.error(f"Error getting dividends: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/security/<secid>/coupons')
async def api_coupons_handler(secid):
    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            return json_response(await client.get_coupons(secid.upper()))
    except Exception as e:
        logger.error(f"Error getting coupons: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/security/<secid>/yields')
async def api_yields_handler(secid):
    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            yields = await client.get_yields(
                secid.upper(),
                from_date=request.args.get('from'),
                till_date=request.args.get('till'),
            )
            return json_response(yields)
    except Exception as e:
        logger.error(f"Error getting yields: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/security/<secid>/specification')
async def api_specification_handler(secid):
    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            return json_response(await client.get_security_specification(secid.upper()))
    except Exception as e:
        logger.error(f"Error getting specification: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/security/<secid>/history/sessions')
async def api_history_sessions_handler(secid):
    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            history = await client.get_history_by_sessions(
                secid.upper(),
                engine=request.args.get('engine', 'stock'),
                market=request.args.get('market', 'shares'),
                board=request.args.get('board', 'TQBR'),
                from_date=request.args.get('from'),
                till_date=request.args.get('till'),
            )
            return json_response(history)
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/news')
async def api_news_handler():
    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            news = await client.get_news(
                lang=request.args.get('lang', 'ru'),
                limit=int(request.args.get('limit', 10)),
            )
            return json_response(news)
    except Exception as e:
        logger.error(f"Error getting news: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/search')
async def search_securities_handler():
    query = request.args.get('q', '').upper()
    if not query or len(query) < 2:
        return json_response([])

    try:
        async with MOEXClient(cache_manager=analyzer.cache) as client:
            all_securities = await client.get_securities()
            results = [
                s for s in all_securities
                if query in s.get('SECID', '').upper() or query in s.get('SECNAME', '').upper()
            ][:20]
            return json_response(results)
    except Exception as e:
        logger.error(f"Error searching securities: {e}")
        return json_response([])


@app.route('/api/portfolio/calculate', methods=['POST'])
async def api_portfolio_calculate_handler():
    """Calculate portfolio returns"""
    try:
        data = await request.get_json()
        capital = float(data.get('capital', 0))
        securities = data.get('securities', [])  # List of {secid, weight, price}

        if capital <= 0 or not securities:
            return json_response({'error': 'Invalid input'}, status=400)

        total_weight = sum(s.get('weight', 0) for s in securities)
        if total_weight == 0:
            return json_response({'error': 'Total weight must be > 0'}, status=400)

        portfolio_value = 0.0
        total_predicted_yield = 0.0
        has_forecast = False

        for sec in securities:
            weight = sec.get('weight', 0) / total_weight
            price = sec.get('price', 0)
            allocation = capital * weight
            shares = allocation / price if price > 0 else 0
            portfolio_value += shares * price

            secid = sec.get('secid')
            if not secid or price <= 0:
                continue
            try:
                sec_data = await analyzer.get_security_data(secid, days=120)
                predictions = (sec_data or {}).get('predictions') or []
                if predictions:
                    avg_prediction = sum(
                        p.get('price', price) for p in predictions) / len(predictions)
                    sec_yield = ((avg_prediction - price) / price) * 100
                    total_predicted_yield += sec_yield * weight
                    has_forecast = True
            except Exception as e:
                logger.error(f"Error forecasting {secid}: {e}")

        return json_response({
            'capital': capital,
            'portfolio_value': round(portfolio_value, 2),
            'expected_yield': round(total_predicted_yield, 2) if has_forecast else 0.0,
            # 'forecast' = derived from model predictions; 'none' = no data, 0 is honest
            'yield_source': 'forecast' if has_forecast else 'none',
            'securities': securities
        })
    except Exception as e:
        logger.error(f"Error calculating portfolio: {e}")
        return json_response({'error': str(e)}, status=500)


# ---------------- Review parsing jobs (executed by celery worker) ----------------

@app.route('/api/security/<secid>/reviews')
async def api_reviews_handler(secid):
    try:
        return json_response(await analyzer.get_reviews(secid.upper()))
    except Exception as e:
        logger.error(f"Error getting reviews: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/security/<secid>/reviews/meta')
async def api_should_parse_reviews_handler(secid):
    try:
        _, should_parse = await analyzer.db.should_parse_reviews(secid.upper())
        return json_response({'should_parse': should_parse})
    except Exception as e:
        logger.error(f"Error getting reviews meta: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/security/<secid>/reviews/progress')
async def api_reviews_progress_handler(secid):
    try:
        progress = await job_store.aget_progress(secid.upper())
        if not progress:
            progress = {'total': 0, 'current': 0, 'status': 'idle', 'error': None}
        return json_response(progress)
    except Exception as e:
        logger.error(f"Error getting progress: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/security/<secid>/reviews/start', methods=['POST'])
async def api_reviews_start_parsing_handler(secid):
    try:
        secid_upper = secid.upper()
        user_id = request.remote_addr or "anonymous"

        # Reuse a running job for the same security+user; a "queued" job is
        # re-sent to celery — its message may have been lost on worker restart
        # (the task itself is idempotent: should_parse gates a double run)
        job = await job_store.afind_active_job(secid_upper, user_id)
        if not job:
            job = new_job(secid_upper, user_id)
            await job_store.asave_job(job)
            await job_store.r.set(
                f"progress:{secid_upper}",
                json.dumps({'total': 0, 'current': 0, 'status': 'queued',
                            'error': None, 'job_id': job['id']}),
            )
        if job.get('status') == 'queued':
            celery.send_task("tasks.parse_reviews",
                             args=[secid_upper, user_id, job['id']])
            logger.info(f"Enqueued job {job['id']} for {secid_upper} by {user_id}")

        return json_response({
            'status': job.get('status', 'queued'),
            'job_id': job.get('id'),
            'secid': job.get('secid'),
            'progress': job.get('progress', {}),
        })
    except Exception as e:
        logger.error(f"Error starting parsing: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/reviews/jobs')
async def api_reviews_jobs_handler():
    try:
        user_id = request.remote_addr or "anonymous"
        jobs = await job_store.aget_user_jobs(user_id)
        return json_response({'jobs': jobs})
    except Exception as e:
        logger.error(f"Error getting jobs: {e}")
        return json_response({'error': str(e)}, status=500)


@app.route('/api/reviews/jobs/<job_id>/cancel', methods=['POST'])
async def api_reviews_cancel_job_handler(job_id):
    try:
        user_id = request.remote_addr or "anonymous"
        ok = await job_store.arequest_cancel(job_id, user_id=user_id)
        if not ok:
            return json_response({'error': 'job not found or not owned by user'}, status=404)
        return json_response({'status': 'cancel_requested'})
    except Exception as e:
        logger.error(f"Error cancelling job: {e}")
        return json_response({'error': str(e)}, status=500)


# ---------------- Advisor: weekly summary reports ----------------

@app.route('/summary')
async def summary_list_handler():
    locale = request.cookies.get("lang", "en")
    _ = setup_i18n(locale)
    reports = await analyzer.db.get_reports(limit=20)
    return await render_template('summary.html', _=_, lang=locale,
                                 reports=reports, report=None)


@app.route('/summary/<int:report_id>')
async def summary_detail_handler(report_id):
    locale = request.cookies.get("lang", "en")
    _ = setup_i18n(locale)
    report = await analyzer.db.get_report(report_id)
    if not report:
        return redirect('/summary')
    reports = await analyzer.db.get_reports(limit=20)
    return await render_template('summary.html', _=_, lang=locale,
                                 reports=reports, report=report,
                                 report_json=json.dumps(serialize(report), ensure_ascii=False))


@app.route('/api/reports/<int:report_id>/export')
async def api_report_export_handler(report_id):
    """Full report metadata as JSON — made to be fed into Claude Code
    for error analysis ("where is the program wrong, what to rewrite")."""
    report = await analyzer.db.get_report(report_id)
    if not report:
        return json_response({'error': 'report not found'}, status=404)
    export = {
        'generated_at': datetime.now().isoformat(),
        'config': CONFIG.get('advisor', {}),
        'report': report,
    }
    resp = json_response(export)
    resp.headers['Content-Disposition'] = f'attachment; filename="report_{report_id}.json"'
    return resp


@app.route('/api/advisor/run', methods=['POST'])
async def api_advisor_run_handler():
    """Manual trigger for the weekly pipeline (runs in celery worker)"""
    task = celery.send_task("tasks.run_weekly_advisor")
    return json_response({'status': 'enqueued', 'task_id': task.id})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
