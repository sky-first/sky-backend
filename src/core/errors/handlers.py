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
    PaymentRequiredError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)

logger = structlog.get_logger(__name__)


from src.config.tenant_connection_manager import TenantUnavailableError


def register_exception_handlers(app: FastAPI):
    """Register all global exception handlers."""

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", error=str(exc), exc_info=True)
        return _json_response(
            request=request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(TenantUnavailableError)
    async def tenant_unavailable_handler(request: Request, exc: TenantUnavailableError):
        """Um cliente que existe mas cuja base não abre.

        Tem de estar AQUI e não no middleware do resolvedor. Foi a lição de
        15/08/2026: pusemos lá um `except` e ele nunca chegou a correr, porque
        em Starlette os handlers registados na app correm DENTRO da pilha de
        middleware — o `@app.exception_handler(Exception)` acima apanhava isto
        primeiro e devolvia o mesmo 500 de sempre. A correcção parecia feita e
        não estava; só se viu ao sondar a produção depois do deploy.

        A resposta é a MESMA de "cliente não existe", de propósito: domínio
        desconhecido, domínio desactivado e cliente suspenso já são
        indistinguíveis para quem sonda de fora, e um cliente avariado não tem
        de ser a excepção que confirma que ele existe. A razão verdadeira ficou
        no log, em `tenant_engine_unavailable`.
        """
        logger.error("tenant_unavailable", slug=getattr(exc, "slug", None), exc_info=True)
        return _json_response(
            request=request,
            status_code=status.HTTP_404_NOT_FOUND,
            code="tenant_not_found",
            message="The requested tenant does not exist or is suspended.",
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # We don't always log 404s as errors to avoid noise
        log_method = logger.warning if exc.status_code < 500 else logger.error
        log_method("http_exception", status_code=exc.status_code, detail=exc.detail)

        return _json_response(
            request=request,
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail),
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("validation_error", errors=exc.errors())
        # SECURITY FIX (Phase 0): Pydantic v2 validation errors include the
        # raw `input` dict in each error detail. This means a malformed
        # connection-creation request echoes back the credential payload
        # (`config.password`, `config.secret`, etc.) in the 422 response.
        # We strip the `input` key from every error detail before returning
        # it to the client. The `input` is still available in the logger
        # line above for debugging.
        sanitized = []
        for err in exc.errors():
            safe = {k: v for k, v in err.items() if k != "input"}
            # Pydantic's `ctx` can embed the original Exception instance
            # (e.g. ValueError raised by a model_validator). Exceptions
            # aren't JSON-serializable, so JSONResponse raises TypeError
            # which the rate-limit middleware's error branch then catches
            # — flatten any non-serializable ctx values to their str form.
            if isinstance(safe.get("ctx"), dict):
                safe["ctx"] = {
                    k: (str(v) if isinstance(v, BaseException) else v)
                    for k, v in safe["ctx"].items()
                }
            sanitized.append(safe)
        return _json_response(
            request=request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="Invalid request format.",
            details=sanitized,
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(httpx.TimeoutException)
    async def httpx_timeout_exception_handler(request: Request, exc: httpx.TimeoutException):
        logger.warning("ai_service_timeout", error=str(exc))
        return _json_response(
            request=request,
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
            PaymentRequiredError: "PAYMENT_REQUIRED",
            InternalServerError: "SERVER_ERROR",
            ServiceUnavailableError: "SERVICE_UNAVAILABLE",
        }

        code = code_map.get(type(exc), "API_ERROR")

        # PaymentRequiredError carries an upgrade_cta string so the FE
        # can render a button label in the toast/modal without
        # hardcoding it client-side. Keeping copy on the BE means
        # changing the marketing message doesn't ship a FE deploy.
        details = None
        if isinstance(exc, PaymentRequiredError):
            details = {"upgrade_cta": exc.upgrade_cta}

        return _json_response(
            request=request,
            status_code=exc.status_code,
            code=code,
            message=exc.message,
            details=details,
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    @app.exception_handler(JWTError)
    async def jwt_exception_handler(request: Request, exc: JWTError):
        logger.warning("jwt_error", error=str(exc))
        return _json_response(
            request=request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
            message="Invalid authentication token.",
            correlation_id=structlog.contextvars.get_contextvars().get("correlation_id"),
        )

    # W6 wire-in — ChatError family. Each subclass carries its own
    # http_status + stable code; we serialize via the dedicated
    # envelope so the FE mapper can switch on `error.code`.
    from src.core.errors.chat_errors import ChatError as _ChatError

    @app.exception_handler(_ChatError)
    async def chat_error_handler(request: Request, exc: _ChatError):
        # If the trace_id was not pre-populated by the pipeline, attach
        # the request correlation_id here so support has a thread to pull.
        if exc.trace_id is None:
            exc.trace_id = structlog.contextvars.get_contextvars().get("correlation_id")
        logger.warning(
            "chat_error",
            code=exc.code,
            status=exc.http_status,
            trace_id=exc.trace_id,
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.envelope().to_dict(),
        )


def _json_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    correlation_id: str = None,
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

    response = JSONResponse(status_code=status_code, content=content)

    # Inject CORS headers manually because FastAPI exception handlers run
    # outside the Starlette middleware chain, so CORSMiddleware never sees
    # these error responses and cannot add the required headers itself.
    try:
        from src.config.settings import settings

        origin = request.headers.get("origin") or request.headers.get("Origin")
        if origin and origin in settings.cors_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.append("Vary", "Origin")
    except Exception:
        # Never break error responses due to CORS header injection failure
        pass

    return response
