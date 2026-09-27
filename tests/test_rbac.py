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
    provider2 = User(
        name="Provider Two",
        email="provider2@example.com",
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

    db.add_all([admin, provider1, provider2, customer1, customer2])
    db.commit()
    for u in [admin, provider1, provider2, customer1, customer2]:
        db.refresh(u)

    return {
        "admin": admin,
        "provider1": provider1,
        "provider2": provider2,
        "customer1": customer1,
        "customer2": customer2,
    }


def get_headers_for_user(user: User) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user.id), "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


def test_customer_isolation_and_rbac(client: TestClient, seed_users: dict):
    customer1 = seed_users["customer1"]
    customer2 = seed_users["customer2"]
    provider1 = seed_users["provider1"]
    admin = seed_users["admin"]

    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=1)

    # Customer 1 creates booking
    res1 = client.post(
        "/bookings",
        headers=get_headers_for_user(customer1),
        json={
            "provider_id": provider1.id,
            "service_name": "Service 1",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )
    assert res1.status_code == 201
    b1_id = res1.json()["id"]

    # Customer 2 creates booking
    start2 = start + timedelta(hours=3)
    end2 = start2 + timedelta(hours=1)
    res2 = client.post(
        "/bookings",
        headers=get_headers_for_user(customer2),
        json={
            "provider_id": provider1.id,
            "service_name": "Service 2",
            "start_time": start2.isoformat(),
            "end_time": end2.isoformat(),
        },
    )
    assert res2.status_code == 201
    b2_id = res2.json()["id"]

    # Customer 1 reads own booking -> 200 OK
    get_res1 = client.get(f"/bookings/{b1_id}", headers=get_headers_for_user(customer1))
    assert get_res1.status_code == 200

    # Customer 1 attempts to read Customer 2's booking -> FORBIDDEN (403)
    get_res2 = client.get(f"/bookings/{b2_id}", headers=get_headers_for_user(customer1))
    assert get_res2.status_code == 403

    # Customer 1 lists bookings -> sees only own booking
    list_res = client.get("/bookings", headers=get_headers_for_user(customer1))
    assert list_res.status_code == 200
    booking_ids = [b["id"] for b in list_res.json()]
    assert b1_id in booking_ids
    assert b2_id not in booking_ids

    # Admin lists bookings -> sees all bookings
    admin_list = client.get("/bookings", headers=get_headers_for_user(admin))
    assert admin_list.status_code == 200
    all_ids = [b["id"] for b in admin_list.json()]
    assert b1_id in all_ids
    assert b2_id in all_ids


def test_provider_isolation(client: TestClient, seed_users: dict):
    customer1 = seed_users["customer1"]
    provider1 = seed_users["provider1"]
    provider2 = seed_users["provider2"]

    start = datetime.now(UTC) + timedelta(days=2)
    end = start + timedelta(hours=1)

    # Booking for Provider 1
    res1 = client.post(
        "/bookings",
        headers=get_headers_for_user(customer1),
        json={
            "provider_id": provider1.id,
            "service_name": "Provider 1 Service",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )
    assert res1.status_code == 201
    b1_id = res1.json()["id"]

    # Provider 1 reads own booking -> 200 OK
    p1_get = client.get(f"/bookings/{b1_id}", headers=get_headers_for_user(provider1))
    assert p1_get.status_code == 200

    # Provider 2 attempts to read Provider 1's booking -> FORBIDDEN (403)
    p2_get = client.get(f"/bookings/{b1_id}", headers=get_headers_for_user(provider2))
    assert p2_get.status_code == 403
