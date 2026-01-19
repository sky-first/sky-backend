"""FastAPI application entry point."""

import logging
import sys
from pythonjsonlogger import jsonlogger
from contextlib import asynccontextmanager

from prometheus_fastapi_instrumentator import Instrumentator

from fastapi import Depends, FastAPI

from src.api.middleware import auth, cors, error_handler
from src.api.middleware import logging as logging_middleware
from src.api.middleware import rate_limit
from src.api.v1.router import api_router
from src.config import settings
from src.config.database import (
    close_db,
    get_connection_pool_stats,
    get_database_connections,
    get_db,
    init_db,
    log_connection_stats,
)
from src.config.redis import close_redis, init_redis

# Configure logging
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
_root = logging.getLogger()
_root.handlers = [_handler]
_root.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    # Startup
    logger.info("Starting application...")
    await init_db()
    await init_redis()
    # Log initial connection stats
    await log_connection_stats()
    logger.info("Application started successfully")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    await close_db()
    await close_redis()
    logger.info("Application shut down successfully")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for AI SaaS Dashboard",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Setup CORS FIRST (before other middlewares)
# CORS uses add_middleware which executes in normal order (first added = first executed)
cors.setup_cors(app)

# Setup HTTP middlewares
# IMPORTANT: In FastAPI, middleware added with app.middleware("http")() executes in REVERSE order
# So we add them in REVERSE order of desired execution:
# Desired execution order:
# 1. auth (FIRST - sets request.state.user_id)
# 2. rate_limit (needs user_id from auth)
# 3. logging
# 4. error_handler (LAST - catches exceptions)
#
# So we add them as: error_handler, logging, rate_limit, auth (reverse order)
app.middleware("http")(error_handler.error_handler_middleware)  # Added 1st, executes LAST
app.middleware("http")(logging_middleware.logging_middleware)  # Added 2nd, executes 3rd
app.middleware("http")(rate_limit.rate_limit_middleware)  # Added 3rd, executes 2nd
app.middleware("http")(auth.auth_middleware)  # Added 4th (LAST), executes FIRST

from fastapi.responses import JSONResponse
from jose import JWTError

# Add exception handlers BEFORE routers (these catch exceptions from middleware and routes)
from src.api.middleware import error_handler as error_handler_module
from src.core.exceptions import (
    BadRequestError,
    BaseAPIException,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


@app.exception_handler(UnauthorizedError)
async def unauthorized_exception_handler(request, exc: UnauthorizedError):
    """Handle UnauthorizedError exceptions."""
    error_handler_module.logger.warning(f"Unauthorized handler: {exc.message}")
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": "Unauthorized", "message": exc.message},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


@app.exception_handler(JWTError)
async def jwt_exception_handler(request, exc: JWTError):
    """Handle JWTError exceptions."""
    error_handler_module.logger.warning(f"JWT error handler: {str(exc)}")
    response = JSONResponse(
        status_code=401,
        content={"error": "Unauthorized", "message": "Invalid token"},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc: ValidationError):
    """Handle ValidationError exceptions."""
    error_handler_module.logger.warning(f"Validation error handler: {exc.message}")
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": "Validation Error", "message": exc.message},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


@app.exception_handler(ForbiddenError)
async def forbidden_exception_handler(request, exc: ForbiddenError):
    """Handle ForbiddenError exceptions."""
    error_handler_module.logger.warning(f"Forbidden handler: {exc.message}")
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": "Forbidden", "message": exc.message},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


@app.exception_handler(NotFoundError)
async def not_found_exception_handler(request, exc: NotFoundError):
    """Handle NotFoundError exceptions."""
    error_handler_module.logger.warning(f"Not found handler: {exc.message}")
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": "Not Found", "message": exc.message},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


@app.exception_handler(BadRequestError)
async def bad_request_exception_handler(request, exc: BadRequestError):
    """Handle BadRequestError exceptions."""
    error_handler_module.logger.warning(f"Bad request handler: {exc.message}")
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": "Bad Request", "message": exc.message},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


@app.exception_handler(ConflictError)
async def conflict_exception_handler(request, exc: ConflictError):
    """Handle ConflictError exceptions."""
    error_handler_module.logger.warning(f"Conflict handler: {exc.message}")
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": "Conflict", "message": exc.message},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


@app.exception_handler(BaseAPIException)
async def base_api_exception_handler(request, exc: BaseAPIException):
    """Handle other BaseAPIException exceptions."""
    error_handler_module.logger.error(f"API exception handler: {exc.message}")
    response = JSONResponse(
        status_code=exc.status_code,
        content={"error": "API Error", "message": exc.message},
    )
    error_handler_module._apply_cors_headers(request, response)
    return response


# Include API routers
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Observability: Prometheus metrics (Golden Signals)
# Exposes `/metrics` for Prometheus scraping.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


# Override the openapi() function - simplified for clean start
def custom_openapi():
    """Custom OpenAPI schema - will add security when endpoints are implemented."""
    from fastapi.openapi.utils import get_openapi

    # Force regeneration - clear any cached schema
    app.openapi_schema = None

    # Generate base schema from routes
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Add Security Scheme for Bearer Token
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter JWT token"
        }
    }

    # Apply security globally to all endpoints
    # Endpoints that don't need it will simply ignore it, or we can be more granular
    openapi_schema["security"] = [{"BearerAuth": []}]

    logger.info(f"📋 OpenAPI schema generated with {len(openapi_schema.get('paths', {}))} paths")

    # Cache the schema
    app.openapi_schema = openapi_schema

    return openapi_schema


# Override the default openapi function
app.openapi = custom_openapi


@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint."""
    from datetime import datetime, timezone

    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Health"])
async def ready():
    """Readiness check endpoint."""
    # TODO: Check database and Redis connections
    return {"status": "ready"}


@app.get("/live", tags=["Health"])
async def live():
    """Liveness check endpoint."""
    return {"status": "alive"}


@app.get("/api/v1/monitoring/connections", tags=["Monitoring"])
async def monitoring_connections(db=Depends(get_db)):
    """
    Monitor database connections.
    Returns pool statistics and PostgreSQL connection information.
    """
    pool_stats = await get_connection_pool_stats()
    db_connections = await get_database_connections(db)

    return {
        "pool_stats": pool_stats,
        "database_connections": db_connections,
        "recommendations": _get_connection_recommendations(pool_stats, db_connections),
    }


def _get_connection_recommendations(pool_stats: dict, db_connections: dict) -> list:
    """Generate recommendations based on connection statistics."""
    recommendations = []

    if "error" in db_connections:
        return recommendations

    # Check pool usage
    pool_usage_percent = (
        pool_stats["total_connections"] / pool_stats["pool_max_size"] * 100
        if pool_stats["pool_max_size"] > 0
        else 0
    )

    if pool_usage_percent > 80:
        recommendations.append(
            {
                "level": "warning",
                "message": f"Pool usage is {pool_usage_percent:.1f}% - consider increasing pool_size or max_overflow",
            }
        )

    # Check database connection usage
    db_usage_percent = db_connections.get("connection_usage_percent", 0)
    if db_usage_percent > 80:
        recommendations.append(
            {
                "level": "critical",
                "message": f"Database connection usage is {db_usage_percent:.1f}% - close idle connections or increase max_connections",
            }
        )

    # Check for idle in transaction
    idle_in_transaction = db_connections.get("idle_in_transaction", 0)
    if idle_in_transaction > 0:
        recommendations.append(
            {
                "level": "warning",
                "message": f"{idle_in_transaction} connections are idle in transaction - these may indicate connection leaks",
            }
        )

    # Check overflow usage
    if pool_stats["overflow"] > 0:
        recommendations.append(
            {
                "level": "info",
                "message": f"{pool_stats['overflow']} connections in overflow - pool is being used beyond base size",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "level": "success",
                "message": "Connection pool is healthy",
            }
        )

    return recommendations


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint - API information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "api_prefix": settings.API_V1_PREFIX,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
# Trigger fresh build
# Build trigger: Sun Jan 18 10:23:06 UTC 2026
