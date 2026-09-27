from datetime import timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_role
from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.user import User, UserRole

# Fast in-memory database for testing authentication & RBAC
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
    provider = User(
        name="Provider User",
        email="provider1@example.com",
        password_hash=password_hash,
        role=UserRole.PROVIDER,
    )
    customer = User(
        name="Customer User",
        email="customer1@example.com",
        password_hash=password_hash,
        role=UserRole.CUSTOMER,
    )

    db.add_all([admin, provider, customer])
    db.commit()
    for u in [admin, provider, customer]:
        db.refresh(u)

    return {"admin": admin, "provider": provider, "customer": customer}


def get_headers_for_user(user: User, expires_delta: timedelta | None = None) -> dict[str, str]:
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value},
        expires_delta=expires_delta,
    )
    return {"Authorization": f"Bearer {token}"}


def test_user_registration(client: TestClient):
    response = client.post(
        "/auth/register",
        json={
            "name": "New User",
            "email": "newuser@example.com",
            "password": "secretpassword",
            "role": "customer",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["role"] == "customer"
    assert "id" in data


def test_duplicate_email_registration_fails(client: TestClient, seed_users: dict):
    response = client.post(
        "/auth/register",
        json={
            "name": "Duplicate User",
            "email": "customer1@example.com",
            "password": "secretpassword",
            "role": "customer",
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_login_success(client: TestClient, seed_users: dict):
    response = client.post(
        "/auth/login",
        json={
            "email": "customer1@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_password_fails(client: TestClient, seed_users: dict):
    response = client.post(
        "/auth/login",
        json={
            "email": "customer1@example.com",
            "password": "wrongpassword",
        },
    )
    assert response.status_code == 401


def test_get_me_profile_success(client: TestClient, seed_users: dict):
    customer = seed_users["customer"]
    headers = get_headers_for_user(customer)
    response = client.get("/users/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == customer.email
    assert data["role"] == "customer"


def test_missing_auth_header_fails(client: TestClient):
    response = client.get("/users/me")
    assert response.status_code == 401
    assert "Missing authentication token" in response.json()["detail"]


def test_invalid_jwt_token_fails(client: TestClient):
    response = client.get("/users/me", headers={"Authorization": "Bearer invalidtoken123"})
    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]


def test_expired_jwt_token_fails(client: TestClient, seed_users: dict):
    customer = seed_users["customer"]
    headers = get_headers_for_user(customer, expires_delta=timedelta(seconds=-10))
    response = client.get("/users/me", headers=headers)
    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]


def test_rbac_require_role_dependency(client: TestClient, seed_users: dict):
    @app.get("/test-admin-only")
    def admin_route(user: User = Depends(require_role(UserRole.ADMIN))):
        return {"msg": "welcome admin"}

    admin_headers = get_headers_for_user(seed_users["admin"])
    res_admin = client.get("/test-admin-only", headers=admin_headers)
    assert res_admin.status_code == 200

    cust_headers = get_headers_for_user(seed_users["customer"])
    res_cust = client.get("/test-admin-only", headers=cust_headers)
    assert res_cust.status_code == 403
    assert "insufficient role permissions" in res_cust.json()["detail"]
