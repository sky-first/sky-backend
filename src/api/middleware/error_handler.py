"""Global error handler middleware."""

import logging
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError

# ExceptionGroup / BaseExceptionGroup exist only on Python 3.11+.
# On 3.11, ExceptionGroup is also an Exception, so it would be caught by `except Exception`
# unless we explicitly detect and handle it.
try:  # pragma: no cover
    from builtins import BaseExceptionGroup as _BuiltinsBaseExceptionGroup  # type: ignore
except Exception:  # pragma: no cover
    _BuiltinsBaseExceptionGroup = None

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


def _apply_cors_headers(request: Request, response: Response) -> None:
    """
    Ensure CORS headers exist on error responses.

    NOTE: Our HTTP middlewares can short-circuit (return a Response) before Starlette's
    CORSMiddleware gets a chance to run, which makes browsers report a CORS failure
    instead of the real 401/403/404 response.
    """
    from src.config.settings import settings as app_settings

    origin = request.headers.get("Origin")
    if origin and origin in app_settings.cors_origins_list:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        # Vary is important when reflecting Origin
        try:
            response.headers.add_vary_header("Origin")
        except Exception:
            existing = response.headers.get("Vary")
            response.headers["Vary"] = "Origin" if not existing else f"{existing}, Origin"


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
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "Validation Error", "message": e.message},
        )
        _apply_cors_headers(request, response)
        return response
    except UnauthorizedError as e:
        logger.warning(f"Unauthorized: {e.message}")
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "Unauthorized", "message": e.message},
        )
        _apply_cors_headers(request, response)
        return response
    except ForbiddenError as e:
        logger.warning(f"Forbidden: {e.message}")
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "Forbidden", "message": e.message},
        )
        _apply_cors_headers(request, response)
        return response
    except NotFoundError as e:
        logger.warning(f"Not found: {e.message}")
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "Not Found", "message": e.message},
        )
        _apply_cors_headers(request, response)
        return response
    except BadRequestError as e:
        logger.warning(f"Bad request: {e.message}")
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "Bad Request", "message": e.message},
        )
        _apply_cors_headers(request, response)
        return response
    except ConflictError as e:
        logger.warning(f"Conflict: {e.message}")
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "Conflict", "message": e.message},
        )
        _apply_cors_headers(request, response)
        return response
    except JWTError as e:
        logger.warning(f"JWT error: {str(e)}")
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Unauthorized", "message": "Invalid token"},
        )
        _apply_cors_headers(request, response)
        return response
    except BaseAPIException as e:
        logger.error(f"API exception: {e.message}")
        response = JSONResponse(
            status_code=e.status_code,
            content={"error": "API Error", "message": e.message},
        )
        _apply_cors_headers(request, response)
        return response
    except Exception as e:
        # Python 3.11+: ExceptionGroup inherits from Exception, so handle it here first.
        if _BuiltinsBaseExceptionGroup is not None and isinstance(e, _BuiltinsBaseExceptionGroup):
            eg = e  # type: ignore[assignment]
            exceptions = getattr(eg, "exceptions", []) or []
            logger.warning(f"ExceptionGroup caught: {len(exceptions)} exceptions")

            for exc in exceptions:
                if isinstance(exc, UnauthorizedError):
                    response = JSONResponse(
                        status_code=exc.status_code,
                        content={"error": "Unauthorized", "message": exc.message},
                    )
                    _apply_cors_headers(request, response)
                    return response
                if isinstance(exc, BaseAPIException):
                    response = JSONResponse(
                        status_code=exc.status_code,
                        content={"error": "API Error", "message": exc.message},
                    )
                    _apply_cors_headers(request, response)
                    return response

            first = exceptions[0] if exceptions else None
            if first:
                raise first from eg
            raise

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
        _apply_cors_headers(request, response)
        return response

