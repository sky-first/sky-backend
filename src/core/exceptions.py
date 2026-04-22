"""Custom exceptions for the application."""


class BaseAPIException(Exception):
    """Base exception for API errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class ValidationError(BaseAPIException):
    """Validation error (400)."""

    def __init__(self, message: str = "Validation error"):
        super().__init__(message, status_code=400)


class UnauthorizedError(BaseAPIException):
    """Unauthorized error (401)."""

    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, status_code=401)


class ForbiddenError(BaseAPIException):
    """Forbidden error (403)."""

    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, status_code=403)


class NotFoundError(BaseAPIException):
    """Not found error (404)."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404)


class BadRequestError(BaseAPIException):
    """Bad request error (400)."""

    def __init__(self, message: str = "Bad request"):
        super().__init__(message, status_code=400)


class ConflictError(BaseAPIException):
    """Conflict error (409)."""

    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message, status_code=409)


class InternalServerError(BaseAPIException):
    """Internal server error (500)."""

    def __init__(self, message: str = "Internal server error"):
        super().__init__(message, status_code=500)


class ServiceUnavailableError(BaseAPIException):
    """Upstream dependency is not available (503). Use when a real
    external service (AI backend, Ollama, etc.) is expected but cannot
    be reached — the API surface should not fall back to fake data."""

    def __init__(self, message: str = "Service unavailable"):
        super().__init__(message, status_code=503)
