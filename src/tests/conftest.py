"""Pytest configuration and fixtures."""

# ⚠️ CRÍTICO: Sobrescrever DATABASE_URL ANTES de qualquer import que use database
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from faker import Faker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.api.deps import get_db_session  # noqa: E402

# Agora sim, importar depois de sobrescrever a variável de ambiente
from src.config.database import Base, get_db  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.core.security import (  # noqa: E402
    create_access_token,
    create_refresh_token,
    get_password_hash,
)
from src.main import app  # noqa: E402
from src.models.user import RefreshToken  # noqa: E402
from src.repositories.user import UserRepository  # noqa: E402

# pytest-asyncio is configured via pytest.ini or pyproject.toml

# Test database URL (in-memory SQLite for testing)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session():
    """Create test database session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client(db_session):
    """Create test client."""

    async def override_get_db():
        yield db_session

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db_session
    # raise_server_exceptions=False allows middleware to handle exceptions
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def faker():
    """Faker instance for generating test data."""
    return Faker()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, faker: Faker):
    """Create a test user."""
    from src.services.onboarding_service import ensure_default_planet_and_space

    user_repo = UserRepository(db_session)

    email = faker.email()
    password = "test_password_123"

    user = await user_repo.create(
        email=email,
        password_hash=get_password_hash(password),
        name=faker.name(),
        role="admin",
    )

    # Ensure user has a default planet and space
    await ensure_default_planet_and_space(db_session, user)

    await db_session.commit()
    await db_session.refresh(user)

    return {
        "user": user,
        "email": email,
        "password": password,
    }


@pytest_asyncio.fixture
async def test_user_with_tokens(db_session: AsyncSession, test_user: dict):
    """Create a test user with access and refresh tokens."""
    user = test_user["user"]

    # Create tokens
    token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Save refresh token
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_token_model = RefreshToken(
        user_id=user.id,
        token=refresh_token,
        expires_at=expires_at,
    )
    db_session.add(refresh_token_model)
    await db_session.commit()

    return {
        **test_user,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


@pytest.fixture
def valid_token_payload(test_user: dict):
    """Generate valid JWT token payload."""
    user = test_user["user"]
    return {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
    }


@pytest.fixture
def valid_access_token(valid_token_payload: dict):
    """Generate a valid access token."""
    return create_access_token(valid_token_payload)


@pytest.fixture
def valid_refresh_token(valid_token_payload: dict):
    """Generate a valid refresh token."""
    return create_refresh_token(valid_token_payload)


@pytest.fixture
def invalid_token():
    """Generate an invalid JWT token."""
    return "invalid.token.here"


@pytest.fixture
def expired_token(valid_token_payload: dict):
    """Generate an expired access token."""
    # Create token with negative expiration
    expired_delta = timedelta(minutes=-1)
    return create_access_token(valid_token_payload, expires_delta=expired_delta)


@pytest.fixture
async def cleanup_refresh_tokens(db_session: AsyncSession):
    """Cleanup refresh tokens after test."""
    yield
    # Cleanup is handled by db_session fixture which drops all tables
