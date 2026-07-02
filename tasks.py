"""
Celery tasks: heavy work lives here, not in the web process.

- parse_reviews: scrape + neural analysis of social posts for one security
- run_weekly_advisor: Saturday full report (see advisor.py)
- run_midweek_check: Thursday intermediate report with alarms
"""
import re
import sys
import asyncio
import logging

import redis as redis_lib

from celery_app import app
from settings import BASE_DIR, CONFIG, REDIS_URL
from jobstore import JobStore

logger = logging.getLogger("tasks")


def _ensure_project_path():
    """Celery scrubs the cwd from sys.path AFTER the app is loaded (security
    fix in celery core), which breaks lazy project imports at task time —
    so re-pin the project dir right before importing."""
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)


# Lazy singletons: one set of models per worker process, loaded on first use
_ctx = {}


def _get_ctx():
    if not _ctx:
        _ensure_project_path()
        from database import Database
        from parsers import ReviewsParser
        from text_models import TextAnalyser

        logger.info("Loading neural models in worker process")
        _ctx["db"] = Database()
        _ctx["parser"] = ReviewsParser()
        _ctx["analyser"] = TextAnalyser()
        _ctx["store"] = JobStore(redis_lib.Redis.from_url(REDIS_URL))
    return _ctx


def _redis_lock(name: str, ttl: int = 7200) -> bool:
    r = redis_lib.Redis.from_url(REDIS_URL)
    return bool(r.set(f"lock:{name}", "1", nx=True, ex=ttl))


def _redis_unlock(name: str):
    redis_lib.Redis.from_url(REDIS_URL).delete(f"lock:{name}")


@app.task(name="tasks.parse_reviews")
def parse_reviews(secid: str, user_id: str, job_id: str):
    ctx = _get_ctx()
    asyncio.run(_parse_reviews_async(ctx, secid.upper(), user_id, job_id))


async def _parse_reviews_async(ctx, secid: str, user_id: str, job_id: str):
    db, parser, analyser, store = ctx["db"], ctx["parser"], ctx["analyser"], ctx["store"]

    job = store.get_job(job_id) or {"id": job_id, "secid": secid, "user_id": user_id,
                                    "progress": {"total": 0, "current": 0}}

    def update(status: str, total: int = None, current: int = None, error: str = None):
        if total is not None:
            job["progress"]["total"] = total
        if current is not None:
            job["progress"]["current"] = current
        job["status"] = status
        if error:
            job["message"] = error
        store.save_job(job)
        store.set_progress(secid, {
            "total": job["progress"]["total"],
            "current": job["progress"]["current"],
            "status": status,
            "error": error,
            "job_id": job_id,
        })

    try:
        if store.is_cancelled(job_id):
            update("cancelled")
            return

        last_parsed, should_parse = await db.should_parse_reviews(secid)
        if not should_parse:
            update("completed")
            return

        update("parsing")
        logger.info(f"[Job {job_id}] Parsing reviews for {secid}")
        reviews = await parser.parse_reviews(secid, last_parsed)

        if not reviews:
            await db.update_date_reviews(secid)
            update("completed")
            return

        # Busy tickers (SBER on smart-lab) can yield thousands of posts a week;
        # analyzing them all costs hours of GPU. Keep the newest N (the parser
        # sorts newest-first) and say so in the log — no silent truncation.
        max_reviews = CONFIG["advisor"].get("max_reviews_per_job", 300)
        if max_reviews and len(reviews) > max_reviews:
            logger.warning(
                f"[Job {job_id}] Parsed {len(reviews)} reviews, analyzing only the "
                f"{max_reviews} newest (advisor.max_reviews_per_job)")
            reviews = reviews[:max_reviews]

        update("analyzing", total=len(reviews), current=0)

        analysis_reviews = []
        loop = asyncio.get_event_loop()
        for i, review in enumerate(reviews):
            if store.is_cancelled(job_id):
                logger.info(f"[Job {job_id}] Cancel requested, stopping")
                update("cancelled")
                return
            try:
                review_text = review.get("text", "")
                if not review_text:
                    continue

                # Detect language and translate accordingly
                total_chars = len(review_text.replace(" ", ""))
                ratio_ru = len(re.findall(r'[А-Яа-яЁё]', review_text)) / total_chars if total_chars else 0
                if ratio_ru > 0.1:
                    translated_text = await analyser.translator.translate(
                        review_text, src_lang='Russian', trg_lang='English')
                    review_text_ru = review_text
                else:
                    translated_text = review_text
                    review_text_ru = await analyser.translator.translate(
                        review_text, src_lang='English', trg_lang='Russian')

                analysis = await loop.run_in_executor(
                    None,
                    analyser._analyze_neural_networks_sync,
                    translated_text,
                    review.get("img"),
                )
                if analysis is not None:
                    analysis_reviews.append({
                        **review,
                        **analysis,
                        'text_en': translated_text,
                        'text_ru': review_text_ru,
                    })
            except Exception as e:
                logger.error(f"[Job {job_id}] Error analyzing review {i}: {e}")
            finally:
                update("analyzing", current=i + 1)

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        if analysis_reviews:
            await db.insert_reviews(secid, analysis_reviews)
            logger.info(f"[Job {job_id}] Saved {len(analysis_reviews)} analyzed reviews for {secid}")
        else:
            await db.update_date_reviews(secid)
            logger.info(f"[Job {job_id}] No analyzed reviews, but updated date for {secid}")

        update("completed")
    except Exception as e:
        logger.error(f"[Job {job_id}] Error parsing reviews for {secid}: {e}")
        update("error", error=str(e))


@app.task(name="tasks.run_weekly_advisor", bind=True, max_retries=1, default_retry_delay=600)
def run_weekly_advisor(self, week_start: str = None):
    if not _redis_lock("weekly_advisor"):
        logger.warning("Weekly advisor is already running, skipping")
        return
    try:
        _ensure_project_path()
        from advisor import run_weekly_pipeline
        asyncio.run(run_weekly_pipeline(week_start=week_start))
    except Exception as e:
        logger.error(f"Weekly advisor failed: {e}")
        raise self.retry(exc=e)
    finally:
        _redis_unlock("weekly_advisor")


@app.task(name="tasks.run_midweek_check")
def run_midweek_check():
    if not _redis_lock("midweek_check", ttl=3600):
        logger.warning("Midweek check is already running, skipping")
        return
    try:
        _ensure_project_path()
        from advisor import run_midweek_pipeline
        asyncio.run(run_midweek_pipeline())
    finally:
        _redis_unlock("midweek_check")
