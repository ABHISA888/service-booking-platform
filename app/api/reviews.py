from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.database import get_db
from app.models.booking import Booking, BookingStatus
from app.models.review import Review
from app.models.user import User, UserRole
from app.schemas.review import ReviewCreate, ReviewResponse
from app.services.review_queue import enqueue_summary_job

router = APIRouter(tags=["Reviews"])


class SummarizeRequest(BaseModel):
    provider_id: int


class SummarizeResponse(BaseModel):
    message: str
    job_id: str


@router.post(
    "/bookings/{booking_id}/review",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    booking_id: int,
    review_in: ReviewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # 1. Ownership check: Only customer who owns the booking can review
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the customer who booked this service can submit a review",
        )

    # 2. Status check: Booking must be completed
    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reviews can only be submitted for completed bookings",
        )

    # 3. Uniqueness check: A booking can have at most one review
    existing_review = db.query(Review).filter(Review.booking_id == booking_id).first()
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This booking has already been reviewed",
        )

    review = Review(
        booking_id=booking_id,
        customer_id=current_user.id,
        rating=review_in.rating,
        comment=review_in.comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.post(
    "/reviews/summarize",
    response_model=SummarizeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_review_summarization(
    request: SummarizeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    # Authorization: Admin can summarize any provider; Provider can summarize self
    if current_user.role == UserRole.PROVIDER and current_user.id != request.provider_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Providers can only trigger review summarisation for themselves",
        )

    provider = db.query(User).filter(User.id == request.provider_id).first()
    if not provider or provider.role != UserRole.PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid provider ID: user does not exist or is not a provider",
        )

    job_id = enqueue_summary_job(provider_id=request.provider_id)
    return SummarizeResponse(
        message="Review summarisation job queued successfully",
        job_id=job_id,
    )
