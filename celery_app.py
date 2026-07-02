"""
Celery application: broker, beat schedule (weekly + midweek advisor runs)
"""
from celery import Celery
from celery.schedules import crontab

from settings import CONFIG, REDIS_URL

advisor_cfg = CONFIG["advisor"]

app = Celery("invest", broker=REDIS_URL, include=["tasks"])

app.conf.update(
    timezone="Europe/Moscow",
    enable_utc=True,
    result_backend=None,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Full weekly report: the trading week is closed, the summary is
        # ready over the weekend before Monday open
        "weekly-advisor": {
            "task": "tasks.run_weekly_advisor",
            "schedule": crontab(
                hour=advisor_cfg["weekly_hour"], minute=0,
                day_of_week=advisor_cfg["weekly_day"],
            ),
        },
        # Midweek check: intermediate report, alarms on recommendations
        # that moved strongly against us
        "midweek-check": {
            "task": "tasks.run_midweek_check",
            "schedule": crontab(
                hour=advisor_cfg["midweek_hour"], minute=0,
                day_of_week=advisor_cfg["midweek_day"],
            ),
        },
    },
)
