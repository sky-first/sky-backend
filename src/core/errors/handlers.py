from typing import Any

import httpx
import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jose import JWTError
from starlette.exceptions import HTTPException as StarletteHTTPException

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

logger = structlog.get_logger(__name__)


def register_exception_handlers(app: FastAPI):
    """Register all global exception handlers."""

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", error=str(exc), exc_info=True)
        return _json_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # We don't always log 404s as errors to avoid noise
        log_method = logger.warning if exc.status_code < 500 else logger.error
        log_method("http_exception", status_code=exc.status_code, detail=exc.detail)

        return _json_response(
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail),
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("validation_error", errors=exc.errors())
        return _json_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="Invalid request format.",
            details=exc.errors(),
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(httpx.TimeoutException)
    async def httpx_timeout_exception_handler(request: Request, exc: httpx.TimeoutException):
        logger.warning("ai_service_timeout", error=str(exc))
        return _json_response(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            code="GATEWAY_TIMEOUT",
            message="Connection to AI service timed out.",
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(BaseAPIException)
    async def app_exception_handler(request: Request, exc: BaseAPIException):
        logger.warning("app_exception", error=exc.message, status_code=exc.status_code)

        # Map exception class to error code string
        code_map = {
            UnauthorizedError: "UNAUTHORIZED",
            ForbiddenError: "FORBIDDEN",
            NotFoundError: "NOT_FOUND",
            ValidationError: "VALIDATION_ERROR",
            BadRequestError: "BAD_REQUEST",
            ConflictError: "CONFLICT",
            InternalServerError: "SERVER_ERROR",
        }

        code = code_map.get(type(exc), "API_ERROR")

        return _json_response(
            status_code=exc.status_code,
            code=code,
            message=exc.message,
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(JWTError)
    async def jwt_exception_handler(request: Request, exc: JWTError):
        logger.warning("jwt_error", error=str(exc))
        return _json_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
            message="Invalid authentication token.",
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )


def _json_response(
    status_code: int, code: str, message: str, details: Any = None, correlation_id: str = None
):
    content = {
        "error": {
            "code": code,
            "message": message,
        }
    }

    if details:
        content["error"]["details"] = details

    if correlation_id:
        content["error"]["correlation_id"] = correlation_id

    return JSONResponse(status_code=status_code, content=content)
