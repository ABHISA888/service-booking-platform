from datetime import UTC, datetime, timedelta

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


def test_customer_can_create_booking(client: TestClient, seed_users: dict):
    customer = seed_users["customer1"]
    provider = seed_users["provider1"]

    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/bookings",
        headers=get_headers_for_user(customer),
        json={
            "provider_id": provider.id,
            "service_name": "Car Wash",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["provider_id"] == provider.id
    assert data["customer_id"] == customer.id
    assert data["service_name"] == "Car Wash"
    assert data["status"] == "pending"


def test_provider_cannot_create_customer_booking(client: TestClient, seed_users: dict):
    provider = seed_users["provider1"]
    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/bookings",
        headers=get_headers_for_user(provider),
        json={
            "provider_id": provider.id,
            "service_name": "Self Service",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 403


def test_invalid_provider_id_fails(client: TestClient, seed_users: dict):
    customer = seed_users["customer1"]
    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/bookings",
        headers=get_headers_for_user(customer),
        json={
            "provider_id": 99999,  # Non-existent provider
            "service_name": "Haircut",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 400


def test_invalid_booking_time_range_fails(client: TestClient, seed_users: dict):
    customer = seed_users["customer1"]
    provider = seed_users["provider1"]

    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time - timedelta(hours=1)  # Invalid range

    response = client.post(
        "/bookings",
        headers=get_headers_for_user(customer),
        json={
            "provider_id": provider.id,
            "service_name": "Haircut",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 422


def test_overlapping_booking_fails(client: TestClient, seed_users: dict):
    customer1 = seed_users["customer1"]
    customer2 = seed_users["customer2"]
    provider = seed_users["provider1"]

    start_time = datetime.now(UTC) + timedelta(days=1)
    end_time = start_time + timedelta(hours=2)

    # First booking
    res1 = client.post(
        "/bookings",
        headers=get_headers_for_user(customer1),
        json={
            "provider_id": provider.id,
            "service_name": "Consultation",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert res1.status_code == 201

    # Overlapping booking attempt by customer 2
    res2 = client.post(
        "/bookings",
        headers=get_headers_for_user(customer2),
        json={
            "provider_id": provider.id,
            "service_name": "Consultation Overlap",
            "start_time": (start_time + timedelta(hours=1)).isoformat(),
            "end_time": (end_time + timedelta(hours=1)).isoformat(),
        },
    )
    assert res2.status_code == 400
    assert "not available" in res2.json()["detail"]


def test_update_and_delete_booking(client: TestClient, seed_users: dict):
    customer1 = seed_users["customer1"]
    provider1 = seed_users["provider1"]

    start_time = datetime.now(UTC) + timedelta(days=3)
    end_time = start_time + timedelta(hours=1)

    res = client.post(
        "/bookings",
        headers=get_headers_for_user(customer1),
        json={
            "provider_id": provider1.id,
            "service_name": "Initial Service",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    b_id = res.json()["id"]

    # Update service name and status
    put_res = client.put(
        f"/bookings/{b_id}",
        headers=get_headers_for_user(customer1),
        json={"service_name": "Updated Service", "status": "confirmed"},
    )
    assert put_res.status_code == 200
    assert put_res.json()["service_name"] == "Updated Service"
    assert put_res.json()["status"] == "confirmed"

    # Delete booking
    del_res = client.delete(f"/bookings/{b_id}", headers=get_headers_for_user(customer1))
    assert del_res.status_code == 204

    # Confirm 404 after deletion
    get_res = client.get(f"/bookings/{b_id}", headers=get_headers_for_user(customer1))
    assert get_res.status_code == 404
