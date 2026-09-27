from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.booking import Booking, BookingStatus
from app.models.review import Review
from app.models.user import User, UserRole

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_create_user_models(db_session):
    admin = User(
        name="Admin",
        email="admin@example.com",
        password_hash="hash",
        role=UserRole.ADMIN,
    )
    provider = User(
        name="Provider",
        email="provider@example.com",
        password_hash="hash",
        role=UserRole.PROVIDER,
    )
    customer = User(
        name="Customer",
        email="customer@example.com",
        password_hash="hash",
        role=UserRole.CUSTOMER,
    )

    db_session.add_all([admin, provider, customer])
    db_session.commit()

    assert admin.id is not None
    assert provider.role == UserRole.PROVIDER
    assert customer.role == UserRole.CUSTOMER


def test_unique_email_constraint(db_session):
    user1 = User(name="U1", email="same@example.com", password_hash="hash")
    user2 = User(name="U2", email="same@example.com", password_hash="hash")

    db_session.add(user1)
    db_session.commit()

    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_booking_and_review_relationships(db_session):
    provider = User(
        name="Provider",
        email="p@example.com",
        password_hash="hash",
        role=UserRole.PROVIDER,
    )
    customer = User(
        name="Customer",
        email="c@example.com",
        password_hash="hash",
        role=UserRole.CUSTOMER,
    )
    db_session.add_all([provider, customer])
    db_session.commit()

    now = datetime.now(UTC)
    booking = Booking(
        provider_id=provider.id,
        customer_id=customer.id,
        service_name="AC Repair",
        start_time=now,
        end_time=now + timedelta(hours=1),
        status=BookingStatus.COMPLETED,
    )
    db_session.add(booking)
    db_session.commit()

    review = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        rating=5,
        comment="Great service!",
    )
    db_session.add(review)
    db_session.commit()

    assert booking.review.id == review.id
    assert review.booking.service_name == "AC Repair"
    assert review.customer.email == "c@example.com"
