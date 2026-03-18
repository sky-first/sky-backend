import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        header_name: str = "X-Correlation-ID",
        validate_uuid: bool = True,
    ):
        super().__init__(app)
        self.header_name = header_name
        self.validate_uuid = validate_uuid

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Extract or generate correlation ID
        correlation_id = request.headers.get(self.header_name)

        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Bind to structlog context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # Log request start
        logger.info(
            "request_started",
            path=request.url.path,
            method=request.method,
            client_ip=request.client.host if request.client else None,
        )

        response = await call_next(request)

        # Add header to response
        response.headers[self.header_name] = correlation_id

        # Log request completion
        logger.info(
            "request_completed",
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
        )

        return response
