from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserResponse


class ReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")
    comment: str = Field(..., min_length=1, max_length=1000, description="Review comment")


class ReviewResponse(BaseModel):
    id: int
    booking_id: int
    customer_id: int
    rating: int
    comment: str
    created_at: datetime
    customer: UserResponse | None = None

    model_config = ConfigDict(from_attributes=True)
