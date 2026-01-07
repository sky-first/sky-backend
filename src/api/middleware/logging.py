"""Request logging middleware."""

import logging
import time
from typing import Callable

from fastapi import Request, Response

logger = logging.getLogger(__name__)


async def logging_middleware(request: Request, call_next: Callable) -> Response:
    """
    Logging middleware for requests.

    Args:
        request: FastAPI request
        call_next: Next middleware/route handler

    Returns:
        Response: HTTP response
    """
    start_time = time.time()

    # Log request
    logger.info(
        f"Request: {request.method} {request.url.path}",
        extra={
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else None,
        },
    )

    # Process request
    try:
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log response
        logger.info(
            f"Response: {request.method} {request.url.path} - {response.status_code} - {duration:.3f}s",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration": duration,
            },
        )

        return response
    except Exception as e:
        # Calculate duration even on error
        duration = time.time() - start_time
        logger.warning(
            f"Error: {request.method} {request.url.path} - {duration:.3f}s - {type(e).__name__}: {str(e)}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration": duration,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        # Re-raise to let error_handler_middleware handle it
        raise

