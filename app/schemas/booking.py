from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.booking import BookingStatus
from app.schemas.user import UserResponse


class BookingBase(BaseModel):
    service_name: str
    start_time: datetime
    end_time: datetime


class BookingCreate(BookingBase):
    provider_id: int

    @model_validator(mode="after")
    def validate_time_range(self) -> "BookingCreate":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be strictly before end_time")
        return self


class BookingUpdate(BaseModel):
    service_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: BookingStatus | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "BookingUpdate":
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("start_time must be strictly before end_time")
        return self


class BookingResponse(BookingBase):
    id: int
    provider_id: int
    customer_id: int
    status: BookingStatus
    created_at: datetime
    provider: UserResponse | None = None
    customer: UserResponse | None = None

    model_config = ConfigDict(from_attributes=True)
