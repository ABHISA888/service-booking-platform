import json
import uuid
from datetime import UTC, datetime

import redis

from app.core.config import settings

QUEUE_NAME = "review_summary_jobs"


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def enqueue_summary_job(provider_id: int) -> str:
    redis_client = get_redis_client()
    job_id = str(uuid.uuid4())
    job_data = {
        "job_id": job_id,
        "provider_id": provider_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    redis_client.rpush(QUEUE_NAME, json.dumps(job_data))
    return job_id
