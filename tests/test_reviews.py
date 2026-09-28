from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.user import User, UserRole

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


@pytest.fixture
def client(db: Session):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seed_users(db: Session):
    password_hash = get_password_hash("password123")

    admin = User(
        name="Admin User",
        email="admin@example.com",
        password_hash=password_hash,
        role=UserRole.ADMIN,
    )
    provider1 = User(
        name="Provider One",
        email="provider1@example.com",
        password_hash=password_hash,
        role=UserRole.PROVIDER,
    )
    customer1 = User(
        name="Customer One",
        email="customer1@example.com",
        password_hash=password_hash,
        role=UserRole.CUSTOMER,
    )
    customer2 = User(
        name="Customer Two",
        email="customer2@example.com",
        password_hash=password_hash,
        role=UserRole.CUSTOMER,
    )

    db.add_all([admin, provider1, customer1, customer2])
    db.commit()
    for u in [admin, provider1, customer1, customer2]:
        db.refresh(u)

    return {
        "admin": admin,
        "provider1": provider1,
        "customer1": customer1,
        "customer2": customer2,
    }


def get_headers_for_user(user: User) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user.id), "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


def test_review_creation_workflow(client: TestClient, seed_users: dict):
    customer1 = seed_users["customer1"]
    customer2 = seed_users["customer2"]
    provider1 = seed_users["provider1"]

    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=1)

    # 1. Create booking
    res = client.post(
        "/bookings",
        headers=get_headers_for_user(customer1),
        json={
            "provider_id": provider1.id,
            "service_name": "Plumbing Repair",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )
    assert res.status_code == 201
    b_id = res.json()["id"]

    # 2. Attempt to review pending booking -> FAILS (400 Bad Request)
    rev_pending = client.post(
        f"/bookings/{b_id}/review",
        headers=get_headers_for_user(customer1),
        json={"rating": 5, "comment": "Great!"},
    )
    assert rev_pending.status_code == 400
    assert "completed" in rev_pending.json()["detail"]

    # 3. Update booking status to completed
    update_res = client.put(
        f"/bookings/{b_id}",
        headers=get_headers_for_user(customer1),
        json={"status": "completed"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "completed"

    # 4. Wrong customer attempts to review Customer 1's booking -> FAILS (403 Forbidden)
    rev_cust2 = client.post(
        f"/bookings/{b_id}/review",
        headers=get_headers_for_user(customer2),
        json={"rating": 4, "comment": "Not my booking"},
    )
    assert rev_cust2.status_code == 403

    # 5. Customer 1 reviews completed booking -> SUCCESS (201 Created)
    rev_ok = client.post(
        f"/bookings/{b_id}/review",
        headers=get_headers_for_user(customer1),
        json={"rating": 5, "comment": "Outstanding plumbing service!"},
    )
    assert rev_ok.status_code == 201
    rev_data = rev_ok.json()
    assert rev_data["rating"] == 5
    assert rev_data["booking_id"] == b_id

    # 6. Customer 1 attempts duplicate review on same booking -> FAILS (400 Bad Request)
    rev_dup = client.post(
        f"/bookings/{b_id}/review",
        headers=get_headers_for_user(customer1),
        json={"rating": 4, "comment": "Second review attempt"},
    )
    assert rev_dup.status_code == 400
    assert "already been reviewed" in rev_dup.json()["detail"]


def test_invalid_rating_rejected(client: TestClient, seed_users: dict):
    customer1 = seed_users["customer1"]
    provider1 = seed_users["provider1"]

    start = datetime.now(UTC) + timedelta(days=2)
    end = start + timedelta(hours=1)

    res = client.post(
        "/bookings",
        headers=get_headers_for_user(customer1),
        json={
            "provider_id": provider1.id,
            "service_name": "Cleaning",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )
    b_id = res.json()["id"]

    # Mark completed
    client.put(
        f"/bookings/{b_id}",
        headers=get_headers_for_user(customer1),
        json={"status": "completed"},
    )

    # Rating = 6 (Out of 1-5 range) -> 422 Unprocessable Entity
    rev_invalid = client.post(
        f"/bookings/{b_id}/review",
        headers=get_headers_for_user(customer1),
        json={"rating": 6, "comment": "Too high rating"},
    )
    assert rev_invalid.status_code == 422


@patch("app.api.reviews.enqueue_summary_job")
def test_review_summarize_endpoint(mock_enqueue, client: TestClient, seed_users: dict):
    mock_enqueue.return_value = "mock-job-id-12345"
    provider1 = seed_users["provider1"]

    response = client.post(
        "/reviews/summarize",
        headers=get_headers_for_user(provider1),
        json={"provider_id": provider1.id},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["job_id"] == "mock-job-id-12345"
    assert "queued" in data["message"]
    mock_enqueue.assert_called_once_with(provider_id=provider1.id)
