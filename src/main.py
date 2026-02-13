"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.middleware import auth, cors, rate_limit
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
from src.core.errors.handlers import register_exception_handlers
from src.core.logging import configure_logging, get_logger
from src.core.middleware.correlation import CorrelationIdMiddleware

# Configure structured logging
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    # Startup
    logger.info("application_startup")
    await init_db()
    await init_redis()
    # Log initial connection stats
    await log_connection_stats()
    logger.info("application_ready")

    yield

    # Shutdown
    logger.info("application_shutdown")
    await close_db()
    await close_redis()
    logger.info("application_stopped")


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

# 1. CORS (Should be outer-most to handle OPTIONS requests)
cors.setup_cors(app)

# 2. Correlation ID (Should be early to trace everything)
app.add_middleware(CorrelationIdMiddleware)

# Setup HTTP middlewares
# IMPORTANT: In FastAPI, middleware added with app.middleware("http")() executes in REVERSE order
# Desired execution order:
# 1. auth (FIRST - sets request.state.user_id)
# 2. rate_limit (needs user_id from auth)
#
# So we add them as: rate_limit, auth (reverse order)
app.middleware("http")(rate_limit.rate_limit_middleware)  # Added 1st, executes 2nd
app.middleware("http")(auth.auth_middleware)  # Added 2nd (LAST), executes FIRST

# Register output-standardizing exception handlers
register_exception_handlers(app)

# Include API routers
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
# Also include at /api for legacy frontend support (without /v1)
app.include_router(api_router, prefix="/api")

# Observability: Prometheus metrics (Golden Signals)
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
            "description": "Enter JWT token",
        }
    }

    # Apply security globally to all endpoints
    openapi_schema["security"] = [{"BearerAuth": []}]

    logger.info("openapi_schema_generated", paths=len(openapi_schema.get("paths", {})))

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
    import sys

    import uvicorn

    # Check if a custom port is required (e.g. from tests)
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.DEBUG,
    )
