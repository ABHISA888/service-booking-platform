from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.database import get_db
from app.models.booking import Booking, BookingStatus
from app.models.user import User, UserRole
from app.schemas.booking import BookingCreate, BookingResponse, BookingUpdate

router = APIRouter(prefix="/bookings", tags=["Bookings"])


def verify_booking_access(booking: Booking, current_user: User) -> None:
    """Enforces role-based ownership access control.

    - Admin: can access all bookings.
    - Provider: can only access bookings for their provider_id.
    - Customer: can only access bookings for their customer_id.
    """
    if current_user.role == UserRole.ADMIN:
        return
    if current_user.role == UserRole.PROVIDER and booking.provider_id == current_user.id:
        return
    if current_user.role == UserRole.CUSTOMER and booking.customer_id == current_user.id:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: you do not have permission for this booking",
    )


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    booking_in: BookingCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if current_user.role == UserRole.PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Providers cannot create customer bookings",
        )

    provider = db.query(User).filter(User.id == booking_in.provider_id).first()
    if not provider or provider.role != UserRole.PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid provider ID: user does not exist or is not a provider",
        )

    overlap = (
        db.query(Booking)
        .filter(
            Booking.provider_id == booking_in.provider_id,
            Booking.status != BookingStatus.CANCELLED,
            and_(
                Booking.start_time < booking_in.end_time,
                Booking.end_time > booking_in.start_time,
            ),
        )
        .first()
    )
    if overlap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider is not available during the requested time slot",
        )

    booking = Booking(
        provider_id=booking_in.provider_id,
        customer_id=current_user.id,
        service_name=booking_in.service_name,
        start_time=booking_in.start_time,
        end_time=booking_in.end_time,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@router.get("", response_model=list[BookingResponse])
def get_bookings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if current_user.role == UserRole.ADMIN:
        return db.query(Booking).all()
    elif current_user.role == UserRole.PROVIDER:
        return db.query(Booking).filter(Booking.provider_id == current_user.id).all()
    else:  # UserRole.CUSTOMER
        return db.query(Booking).filter(Booking.customer_id == current_user.id).all()


@router.get("/{booking_id}", response_model=BookingResponse)
def get_booking_by_id(
    booking_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    verify_booking_access(booking, current_user)
    return booking


@router.put("/{booking_id}", response_model=BookingResponse)
def update_booking(
    booking_id: int,
    booking_in: BookingUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    verify_booking_access(booking, current_user)

    new_start = booking_in.start_time or booking.start_time
    new_end = booking_in.end_time or booking.end_time

    if new_start >= new_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must be strictly before end_time",
        )

    if booking_in.start_time or booking_in.end_time:
        overlap = (
            db.query(Booking)
            .filter(
                Booking.provider_id == booking.provider_id,
                Booking.id != booking.id,
                Booking.status != BookingStatus.CANCELLED,
                and_(
                    Booking.start_time < new_end,
                    Booking.end_time > new_start,
                ),
            )
            .first()
        )
        if overlap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider is not available during the requested time slot",
            )

    if booking_in.service_name is not None:
        booking.service_name = booking_in.service_name
    if booking_in.start_time is not None:
        booking.start_time = booking_in.start_time
    if booking_in.end_time is not None:
        booking.end_time = booking_in.end_time
    if booking_in.status is not None:
        booking.status = booking_in.status

    db.commit()
    db.refresh(booking)
    return booking


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(
    booking_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    verify_booking_access(booking, current_user)

    db.delete(booking)
    db.commit()
    return None
