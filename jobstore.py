"""
Redis-backed store for background job state.

The web process (quart) enqueues jobs and reads progress; the celery worker
writes progress. Keys expire after JOB_TTL so the store cleans itself.
"""
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

JOB_TTL = 7 * 24 * 3600  # seconds


def job_key(job_id: str) -> str:
    return f"job:{job_id}"


def progress_key(secid: str) -> str:
    return f"progress:{secid.upper()}"


def user_jobs_key(user_id: str) -> str:
    return f"user_jobs:{user_id}"


def cancel_key(job_id: str) -> str:
    return f"cancel:{job_id}"


def new_job(secid: str, user_id: str, priority: str = "interactive") -> Dict:
    return {
        "id": str(uuid.uuid4()),
        "secid": secid.upper(),
        "user_id": user_id,
        "status": "queued",
        "progress": {"total": 0, "current": 0},
        "priority": priority,
        "created_at": datetime.now().isoformat(),
        "message": "",
    }


class JobStore:
    """Thin wrapper; works with both redis.Redis and redis.asyncio.Redis —
    every method comes in a sync (worker) and async (web) flavor."""

    def __init__(self, client):
        self.r = client

    # ---- sync API (celery worker) ----

    def save_job(self, job: Dict):
        self.r.set(job_key(job["id"]), json.dumps(job), ex=JOB_TTL)
        self.r.lrem(user_jobs_key(job["user_id"]), 0, job["id"])
        self.r.lpush(user_jobs_key(job["user_id"]), job["id"])
        self.r.ltrim(user_jobs_key(job["user_id"]), 0, 49)
        self.r.expire(user_jobs_key(job["user_id"]), JOB_TTL)

    def get_job(self, job_id: str) -> Optional[Dict]:
        raw = self.r.get(job_key(job_id))
        return json.loads(raw) if raw else None

    def set_progress(self, secid: str, progress: Dict):
        self.r.set(progress_key(secid), json.dumps(progress), ex=JOB_TTL)

    def get_progress(self, secid: str) -> Optional[Dict]:
        raw = self.r.get(progress_key(secid))
        return json.loads(raw) if raw else None

    def is_cancelled(self, job_id: str) -> bool:
        return bool(self.r.exists(cancel_key(job_id)))

    # ---- async API (quart web app) ----

    async def asave_job(self, job: Dict):
        await self.r.set(job_key(job["id"]), json.dumps(job), ex=JOB_TTL)
        await self.r.lrem(user_jobs_key(job["user_id"]), 0, job["id"])
        await self.r.lpush(user_jobs_key(job["user_id"]), job["id"])
        await self.r.ltrim(user_jobs_key(job["user_id"]), 0, 49)
        await self.r.expire(user_jobs_key(job["user_id"]), JOB_TTL)

    async def aget_job(self, job_id: str) -> Optional[Dict]:
        raw = await self.r.get(job_key(job_id))
        return json.loads(raw) if raw else None

    async def aget_progress(self, secid: str) -> Optional[Dict]:
        raw = await self.r.get(progress_key(secid))
        return json.loads(raw) if raw else None

    async def aget_user_jobs(self, user_id: str) -> List[Dict]:
        job_ids = await self.r.lrange(user_jobs_key(user_id), 0, -1)
        jobs = []
        for jid in job_ids:
            jid = jid.decode() if isinstance(jid, bytes) else jid
            job = await self.aget_job(jid)
            if job:
                jobs.append(job)
        return jobs

    async def arequest_cancel(self, job_id: str, user_id: str = None) -> bool:
        job = await self.aget_job(job_id)
        if not job:
            return False
        if user_id and job.get("user_id") != user_id:
            return False
        await self.r.set(cancel_key(job_id), "1", ex=JOB_TTL)
        if job.get("status") == "queued":
            job["status"] = "cancelled"
            await self.r.set(job_key(job_id), json.dumps(job), ex=JOB_TTL)
        return True

    async def afind_active_job(self, secid: str, user_id: str) -> Optional[Dict]:
        for job in await self.aget_user_jobs(user_id):
            if job.get("secid") == secid.upper() and job.get("status") in {"queued", "running"}:
                return job
        return None
