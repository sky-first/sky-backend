"""CORS middleware."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.settings import settings


def setup_cors(app: FastAPI) -> None:
    """
    Setup CORS middleware.

    IMPORTANT: CORS middleware should be added FIRST (before other middlewares)
    to ensure CORS headers are set correctly for all responses, including error responses.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,  # Required for cookies and Authorization headers
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-CSRF-Token",
            "X-API-Key",
        ],
        expose_headers=[
            "X-RateLimit-Limit-Minute",
            "X-RateLimit-Remaining-Minute",
            "X-RateLimit-Limit-Hour",
            "X-RateLimit-Remaining-Hour",
        ],
        max_age=3600,  # Cache preflight requests for 1 hour
    )
