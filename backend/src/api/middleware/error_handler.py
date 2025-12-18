"""Global error handler middleware."""

import logging
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError

from src.core.exceptions import (
    BadRequestError,
    BaseAPIException,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)

logger = logging.getLogger(__name__)


async def error_handler_middleware(request: Request, call_next: Callable) -> Response:
    """
    Global error handler middleware.

    Args:
        request: FastAPI request
        call_next: Next middleware/route handler

    Returns:
        Response: HTTP response
    """
    try:
        response = await call_next(request)
        return response
    except ValidationError as e:
        logger.warning(f"Validation error: {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": "Validation Error", "message": e.message},
        )
    except UnauthorizedError as e:
        logger.warning(f"Unauthorized: {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": "Unauthorized", "message": e.message},
        )
    except ForbiddenError as e:
        logger.warning(f"Forbidden: {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": "Forbidden", "message": e.message},
        )
    except NotFoundError as e:
        logger.warning(f"Not found: {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": "Not Found", "message": e.message},
        )
    except BadRequestError as e:
        logger.warning(f"Bad request: {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": "Bad Request", "message": e.message},
        )
    except ConflictError as e:
        logger.warning(f"Conflict: {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": "Conflict", "message": e.message},
        )
    except JWTError as e:
        logger.warning(f"JWT error: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Invalid token"},
        )
    except BaseAPIException as e:
        logger.error(f"API exception: {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": "API Error", "message": e.message},
        )
    except Exception as e:
        # Log full exception details for debugging
        import traceback
        error_traceback = traceback.format_exc()
        logger.exception(f"Unhandled exception: {str(e)}\n{error_traceback}")
        # In development, return more details
        from src.config.settings import settings
        error_message = str(e) if settings.DEBUG else "An unexpected error occurred"
        response = JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "message": error_message,
                "details": error_traceback if settings.DEBUG else None,
            },
        )
        # Ensure CORS headers are added even for 500 errors
        # Use the same CORS configuration as the CORS middleware
        from src.config.settings import settings as app_settings
        origin = request.headers.get("Origin")
        if origin and origin in app_settings.cors_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

