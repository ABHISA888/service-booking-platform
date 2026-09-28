from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.booking import Booking, BookingStatus
from app.models.review import Review
from app.models.user import User, UserRole
from worker.main import process_job, run_worker

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_process_job_with_reviews(db: Session):
    provider = User(
        name="Worker Provider",
        email="wprov@test.com",
        password_hash="xxx",
        role=UserRole.PROVIDER,
    )
    customer = User(
        name="Worker Customer",
        email="wcust@test.com",
        password_hash="xxx",
        role=UserRole.CUSTOMER,
    )
    db.add_all([provider, customer])
    db.commit()
    db.refresh(provider)
    db.refresh(customer)

    now = datetime.now(UTC)
    booking1 = Booking(
        provider_id=provider.id,
        customer_id=customer.id,
        service_name="Cleaning",
        start_time=now,
        end_time=now + timedelta(hours=1),
        status=BookingStatus.COMPLETED,
    )
    booking2 = Booking(
        provider_id=provider.id,
        customer_id=customer.id,
        service_name="Plumbing",
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        status=BookingStatus.COMPLETED,
    )
    db.add_all([booking1, booking2])
    db.commit()
    db.refresh(booking1)
    db.refresh(booking2)

    review1 = Review(
        booking_id=booking1.id, customer_id=customer.id, rating=5, comment="Great service"
    )
    review2 = Review(
        booking_id=booking2.id, customer_id=customer.id, rating=4, comment="Very good"
    )
    db.add_all([review1, review2])
    db.commit()

    job_data = {"job_id": "job-123-abc", "provider_id": provider.id}
    summary = process_job(job_data, db)

    assert f"Provider {provider.id} has received 2 reviews" in summary
    assert "average rating of 4.5" in summary


def test_process_job_zero_reviews(db: Session):
    provider = User(
        name="New Provider",
        email="newp@test.com",
        password_hash="xxx",
        role=UserRole.PROVIDER,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)

    job_data = {"job_id": "job-empty-1", "provider_id": provider.id}
    summary = process_job(job_data, db)

    assert f"Provider {provider.id} has received 0 reviews" in summary


def test_process_job_invalid_payload(db: Session):
    job_data = {"invalid": "data"}
    summary = process_job(job_data, db)
    assert summary == "Invalid job payload"


@patch("worker.main.get_redis_client")
@patch("worker.main.SessionLocal")
def test_run_worker_single_job(mock_session_local, mock_get_redis, db: Session):
    mock_redis = MagicMock()
    mock_redis.blpop.return_value = (
        "review_summary_jobs",
        '{"job_id": "test-job-99", "provider_id": 1}',
    )
    mock_get_redis.return_value = mock_redis
    mock_session_local.return_value = db

    run_worker(poll_timeout=1, max_jobs=1)

    mock_redis.blpop.assert_called_once()
