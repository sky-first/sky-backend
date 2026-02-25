from src.config.settings import Settings


def test_build_redis_url_manual_components():
    """Test that REDIS_URL is built from individual components when empty."""
    settings = Settings(
        REDIS_URL="", REDIS_HOST="myredis", REDIS_PORT=6379, REDIS_DB=5, REDIS_PASSWORD="mypassword"
    )
    # The validator runs automatically on init
    assert settings.REDIS_URL == "redis://:mypassword@myredis:6379/5"


def test_build_redis_url_keeps_existing():
    """Test that REDIS_URL is NOT overwritten if already set."""
    existing_url = "redis://otherhost:7000/1"
    settings = Settings(REDIS_URL=existing_url, REDIS_HOST="ignored", REDIS_PORT=6379)
    assert settings.REDIS_URL == existing_url


def test_build_redis_url_from_env_vars(monkeypatch):
    """Test that REDIS_URL respects environment variables during build."""
    monkeypatch.setenv("REDIS_HOST", "envhost")
    monkeypatch.setenv("REDIS_PORT", "9999")
    monkeypatch.setenv("REDIS_DB", "2")
    monkeypatch.setenv("REDIS_PASSWORD", "envpass")

    settings = Settings(REDIS_URL="")
    assert settings.REDIS_URL == "redis://:envpass@envhost:9999/2"


def test_settings_properties():
    """Test various helper properties in Settings."""
    settings = Settings(ENVIRONMENT="production", CORS_ORIGINS="http://a.com, http://b.com")
    assert settings.is_production is True
    assert settings.is_development is False
    assert settings.cors_origins_list == ["http://a.com", "http://b.com"]

    settings.ENVIRONMENT = "development"
    assert settings.is_production is False
    assert settings.is_development is True


def test_cors_origins_default():
    """Test CORS_ORIGINS default parsing."""
    settings = Settings(CORS_ORIGINS="")
    assert "http://localhost:3000" in settings.cors_origins_list


def test_database_url_sync_helper():
    """Test the database_url_sync property."""
    settings = Settings(DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db")
    assert settings.database_url_sync == "postgresql://user:pass@localhost/db"

    settings.DATABASE_URL = "postgresql+asyncpg://localhost/db"
    assert settings.database_url_sync == "postgresql://localhost/db"


def test_apply_environment_defaults_logic(monkeypatch):
    """Test apply_environment_defaults logic for rate limits."""
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_HOUR", raising=False)

    # Production defaults
    s_prod = Settings(ENVIRONMENT="production")
    assert s_prod.RATE_LIMIT_PER_MINUTE == 60
    assert s_prod.RATE_LIMIT_PER_HOUR == 1000

    # Development defaults
    s_dev = Settings(ENVIRONMENT="development")
    assert s_dev.RATE_LIMIT_PER_MINUTE == 600
    assert s_dev.RATE_LIMIT_PER_HOUR == 10000


def test_build_database_url_from_components(monkeypatch):
    """Test building DATABASE_URL from individual POSTGRES_* components."""
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv(
        "POSTGRES_PASSWORD", "p-ss"
    )  # Use simpler pass to avoid re-encoding issues in test
    monkeypatch.setenv("POSTGRES_HOST", "h")
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.setenv("POSTGRES_DB", "d")

    s = Settings(POSTGRES_PORT=5432)
    # Should use asyncpg driver by default and omit port 5432 (default behavior)
    assert "postgresql+asyncpg://u:p-ss@h/d" in s.DATABASE_URL


def test_database_url_password_encoding():
    """Test that DATABASE_URL password encoding/decoding logic works."""
    # Already encoded password
    url = "postgresql+asyncpg://user:p%2Bss@localhost/db"
    s = Settings(DATABASE_URL=url)
    assert s.DATABASE_URL == url

    # Password with special chars that needs encoding
    url_raw = "postgresql+asyncpg://user:p+ss@localhost/db"
    s2 = Settings(DATABASE_URL=url_raw)
    assert "p%2Bss" in s2.DATABASE_URL


def test_database_url_sync_complex():
    """Test database_url_sync with various formats."""
    s = Settings(DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db")
    assert s.database_url_sync == "postgresql://user:pass@host:5432/db"

    s2 = Settings(DATABASE_URL="postgresql://user:pass@host/db")
    assert s2.database_url_sync == "postgresql://user:pass@host/db"


def test_get_settings_cached():
    """Test that get_settings returns the same instance (lru_cache)."""
    from src.config.settings import get_settings, settings

    assert get_settings() is settings
