"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware import auth, cors, error_handler, logging as logging_middleware, rate_limit
from src.api.v1.router import api_router
from src.config import settings
from src.config.database import close_db, init_db
from src.config.redis import close_redis, init_redis

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    # Startup
    logger.info("Starting application...")
    await init_db()
    await init_redis()
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

# Setup middleware (order matters!)
app.middleware("http")(error_handler.error_handler_middleware)
app.middleware("http")(logging_middleware.logging_middleware)
app.middleware("http")(rate_limit.rate_limit_middleware)
app.middleware("http")(auth.auth_middleware)

# Setup CORS
cors.setup_cors(app)

# Include API routers
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


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




if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
