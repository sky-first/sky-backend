"""Alembic environment configuration."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Import your models here for autogenerate
from src.models import *  # noqa: F401, F403
from src.config.database import Base
from src.config.settings import settings

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set SQLAlchemy URL from settings
# Build URL directly if POSTGRES_PASSWORD env var is available (Docker Compose)
import os
from urllib.parse import quote_plus

postgres_password = os.getenv('POSTGRES_PASSWORD')
if postgres_password:
    # Build URL from separate env vars with properly encoded password
    postgres_user = os.getenv('POSTGRES_USER', 'postgres')
    postgres_host = os.getenv('POSTGRES_HOST', 'postgres')
    postgres_port = os.getenv('POSTGRES_PORT', '5432')
    postgres_db = os.getenv('POSTGRES_DB', 'ai_saas_db')
    encoded_password = quote_plus(postgres_password)
    sync_url = f"postgresql://{postgres_user}:{encoded_password}@{postgres_host}:{postgres_port}/{postgres_db}"
    # Escape % for ConfigParser (doubles % to prevent interpolation)
    sync_url = sync_url.replace('%', '%%')
else:
    # Use settings URL and escape % for ConfigParser
    sync_url = settings.database_url_sync.replace('%', '%%')

config.set_main_option("sqlalchemy.url", sync_url)

# Add your model's MetaData object here
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    # Unescape %% back to % (ConfigParser doubles % to escape interpolation)
    if url:
        url = url.replace('%%', '%')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Build URL directly to avoid ConfigParser interpolation issues
    import os
    from urllib.parse import quote_plus
    
    postgres_password = os.getenv('POSTGRES_PASSWORD')
    if postgres_password:
        # Build URL from separate env vars with properly encoded password
        postgres_user = os.getenv('POSTGRES_USER', 'postgres')
        postgres_host = os.getenv('POSTGRES_HOST', 'postgres')
        postgres_port = os.getenv('POSTGRES_PORT', '5432')
        postgres_db = os.getenv('POSTGRES_DB', 'ai_saas_db')
        encoded_password = quote_plus(postgres_password)
        sync_url = f"postgresql://{postgres_user}:{encoded_password}@{postgres_host}:{postgres_port}/{postgres_db}"
    else:
        # Use settings URL and unescape %% if present
        sync_url = settings.database_url_sync.replace('%%', '%')
    
    # Create engine directly with URL to avoid ConfigParser issues
    from sqlalchemy import create_engine
    connectable = create_engine(sync_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

