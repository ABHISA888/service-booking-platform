from fastapi import FastAPI

from app.api import auth, bookings, reviews, users
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Service Booking and Review Platform REST API",
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(bookings.router)
app.include_router(reviews.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "environment": settings.ENV,
    }
