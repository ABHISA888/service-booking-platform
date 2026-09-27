import json
import logging
import sys
import time
from typing import Any

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.booking import Booking
from app.models.review import Review
from app.services.review_queue import QUEUE_NAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("review_summary_worker")

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def process_job(job_data: dict[str, Any], db: Session) -> str:
    job_id = job_data.get("job_id")
    provider_id = job_data.get("provider_id")

    if not provider_id or not job_id:
        logger.error(f"Invalid job payload received: {job_data}")
        return "Invalid job payload"

    logger.info(f"Processing review summary job {job_id} for provider_id={provider_id}...")

    reviews = (
        db.query(Review)
        .join(Booking, Review.booking_id == Booking.id)
        .filter(Booking.provider_id == provider_id)
        .all()
    )

    review_count = len(reviews)
    if review_count == 0:
        summary = f"Provider {provider_id} has received 0 reviews. No summary available."
    else:
        avg_rating = round(sum(r.rating for r in reviews) / review_count, 1)
        summary = (
            f"Provider {provider_id} has received {review_count} reviews "
            f"with an average rating of {avg_rating}. "
            "Common feedback indicates positive service quality."
        )

    logger.info(f"JOB COMPLETED [{job_id}]: {summary}")
    return summary


def run_worker(poll_timeout: int = 5, max_jobs: int | None = None) -> None:
    logger.info("Starting Redis review summarisation worker...")
    jobs_processed = 0

    while True:
        if max_jobs is not None and jobs_processed >= max_jobs:
            logger.info(f"Processed target max_jobs ({max_jobs}), shutting down worker.")
            break

        try:
            redis_client = get_redis_client()
            result = redis_client.blpop(QUEUE_NAME, timeout=poll_timeout)

            if result:
                _, payload_str = result
                try:
                    job_data = json.loads(payload_str)
                    with SessionLocal() as db:
                        process_job(job_data, db)
                    jobs_processed += 1
                except json.JSONDecodeError as err:
                    logger.error(
                        f"Malformed payload (JSON decode error): {payload_str}. Error: {err}"
                    )
                except Exception as err:
                    logger.error(f"Error executing review summary job: {err}", exc_info=True)
        except redis.exceptions.RedisError as redis_err:
            logger.error(f"Redis connection error: {redis_err}. Retrying in 2 seconds...")
            time.sleep(2)
        except KeyboardInterrupt:
            logger.info("Worker stopped manually by KeyboardInterrupt.")
            break
        except Exception as err:
            logger.error(f"Unexpected error in worker loop: {err}", exc_info=True)
            time.sleep(1)


if __name__ == "__main__":
    run_worker()
