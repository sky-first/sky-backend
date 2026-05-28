"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.middleware import auth, cors, idempotency, rate_limit, tenant_resolver
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
from src.core.context_events import init_context_events
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
    logger.info("VERIFY_RELOAD_SUCCESSFUL")
    logger.info("application_startup")
    await init_db()
    await init_redis()

    # Real-time relays — must run after init_redis so they can detect Redis
    from src.api.v1.chat_ws import init_chat_relay
    from src.api.v1.cursor import init_cursor_relay
    await init_chat_relay()
    await init_cursor_relay()

    # Context Layer — register domain-event listeners that publish to the
    # `context:ingest` Redis stream consumed by the AI service ingest
    # worker. Bound to the base `sqlalchemy.orm.Session` class
    # internally; every AsyncSession flush fires through a sync
    # Session so that's where the after_flush / after_commit /
    # after_rollback events exist. No sessionmaker arg needed.
    init_context_events()
    # Log initial connection stats
    await log_connection_stats()
    logger.info("application_ready")

    yield

    # Shutdown
    logger.info("application_shutdown")
    # Tenant engine pools (Model B) — dispose before the global pool so
    # ``tenant_connection_manager`` can flush any remaining sessions.
    from src.config.tenant_connection_manager import tenant_connection_manager

    await tenant_connection_manager.dispose_all()
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

# 3. Security response headers (HSTS/CSP/nosniff/frame-options + server
# fingerprint strip). Added late so it wraps every response including
# ones produced by exception handlers. Red-team infra findings
# 2026-04-23.
from src.middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402
app.add_middleware(SecurityHeadersMiddleware)

# 4. Request size limit — rejects >1 MiB bodies at Content-Length
# before they hit a handler. Closes the "5 MB chat message melts the
# LLM" DoS vector found by red-team. Large-body routes (file upload,
# ingest) are explicitly allowlisted inside the middleware.
from src.middleware.request_limits import RequestSizeLimitMiddleware  # noqa: E402
app.add_middleware(RequestSizeLimitMiddleware)

# Setup HTTP middlewares
# IMPORTANT: In FastAPI, middleware added with app.middleware("http")() executes in REVERSE order
# Desired execution order:
# 1. auth (FIRST - sets request.state.user_id)
# 2. tenant_resolver (needs auth so JWT fallback works; runs before rate_limit
#    so rate_limit can scope per-tenant)
# 3. rate_limit (needs user_id from auth + tenant from resolver)
# 4. idempotency (needs user_id from auth)
#
# So we add them as: idempotency, rate_limit, tenant_resolver, auth (reverse order)
app.middleware("http")(idempotency.idempotency_middleware)
app.middleware("http")(rate_limit.rate_limit_middleware)
app.middleware("http")(tenant_resolver.tenant_resolver_middleware)
app.middleware("http")(auth.auth_middleware)

# Register output-standardizing exception handlers
register_exception_handlers(app)

# Include API routers
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
# Also include at /api for legacy frontend support (without /v1)
app.include_router(api_router, prefix="/api")

# Internal Console (Projeto B). Mounted at /api/console/v1 — separate
# prefix from the customer-facing v1 surface so we can scope rate
# limits, OpenAPI tags, and (eventually) a distinct ingress per
# console.skyfirstlabs.com.
from src.api.v1.console import router as console_router  # noqa: E402

app.include_router(
    console_router, prefix="/api/console/v1", tags=["Internal Console"]
)

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
setattr(app, "openapi", custom_openapi)


@app.get("/health", tags=["Health"])
@app.get("/healthz", tags=["Health"], include_in_schema=False)
async def health():
    """Health check endpoint.

    Exposed under both /health (legacy) and /healthz (k8s convention).
    The Dockerfile HEALTHCHECK uses /healthz; local dev agents
    (k8s extensions, Datadog, etc.) also follow that name. Keeping
    both stops dev-mode log floods of 404s while we migrate callers.
    """
    from datetime import datetime, timezone

    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Health"])
@app.get("/healthz/ready", tags=["Health"], include_in_schema=False)
async def ready():
    """Readiness check endpoint."""
    # TODO: Check database and Redis connections
    return {"status": "ready"}


@app.get("/live", tags=["Health"])
@app.get("/healthz/live", tags=["Health"], include_in_schema=False)
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


def _get_connection_recommendations(pool_stats: dict, db_connections: dict) -> list[dict[str, str]]:
    """Generate recommendations based on connection statistics."""
    recommendations: list[dict[str, str]] = []

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
