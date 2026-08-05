"""Alembic environment configuration."""

import os
from logging.config import fileConfig
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import pool

from src.config.database import Base
from src.config.settings import settings

# Import your models here for autogenerate
from src.models import *  # noqa: F401, F403

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set SQLAlchemy URL from settings
# Build URL directly if POSTGRES_PASSWORD env var is available (Docker Compose)
postgres_password = os.getenv("POSTGRES_PASSWORD")
if postgres_password:
    # Build URL from separate env vars with properly encoded password
    postgres_user = os.getenv("POSTGRES_USER", "postgres")
    postgres_host = os.getenv("POSTGRES_HOST", "postgres")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")
    postgres_db = os.getenv("POSTGRES_DB", "ai_saas_db")
    encoded_password = quote_plus(postgres_password)
    sync_url = f"postgresql://{postgres_user}:{encoded_password}@{postgres_host}:{postgres_port}/{postgres_db}"
    # Escape % for ConfigParser (doubles % to prevent interpolation)
    sync_url = sync_url.replace("%", "%%")
else:
    # Use settings URL and escape % for ConfigParser
    sync_url = settings.database_url_sync.replace("%", "%%")

config.set_main_option("sqlalchemy.url", sync_url)

# Add your model's MetaData object here
# list of tables to ignore (managed by sky-poc-ai or langgraph)
IGNORED_TABLES = {
    "table_metadata",
    "chat_history", 
    "semantic_cache",
    "embeddings",
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "user_permissions",
    "pipeline_jobs",
    "checkpoint_writes",
    "dashboards"
}

def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in IGNORED_TABLES:
        return False
    return True

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    # Unescape %% back to % (ConfigParser doubles % to escape interpolation)
    if url:
        url = url.replace("%%", "%")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        # Isolate sky-be's migration head from sky-ai's — they share the
        # same Postgres database in staging and need separate
        # ``alembic_version_*`` tables (see ``skyfirst-alembic-version-conflict``
        # memory). Bootstrap the new table from the legacy one via
        # ``scripts/migrate_alembic_version_table.py`` before the first
        # deploy with this env file.
        version_table="alembic_version_be",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Build URL directly to avoid ConfigParser interpolation issues
    import os
    from urllib.parse import quote_plus

    postgres_password = os.getenv("POSTGRES_PASSWORD")
    if postgres_password:
        # Build URL from separate env vars with properly encoded password
        postgres_user = os.getenv("POSTGRES_USER", "postgres")
        postgres_host = os.getenv("POSTGRES_HOST", "postgres")
        postgres_port = os.getenv("POSTGRES_PORT", "5432")
        postgres_db = os.getenv("POSTGRES_DB", "ai_saas_db")
        encoded_password = quote_plus(postgres_password)
        sync_url = f"postgresql://{postgres_user}:{encoded_password}@{postgres_host}:{postgres_port}/{postgres_db}"
    else:
        # Use settings URL and unescape %% if present
        sync_url = settings.database_url_sync.replace("%%", "%")

    # Create engine directly with URL to avoid ConfigParser issues
    from sqlalchemy import create_engine

    connectable = create_engine(sync_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Alembic creates ``version_num`` as VARCHAR(32). This project's
        # revision ids are long and descriptive — eight of them already
        # exceed 32 characters, the longest at 40 — so the very first one
        # that overflows aborts the whole upgrade with
        # StringDataRightTruncation and, because the migrate Job is a
        # PreSync hook, the deployment never rolls out at all. That is
        # exactly what blocked production on agent_finding_structured_
        # 20260730 (33 chars).
        #
        # Widen it here rather than in a migration: a migration cannot fix
        # the table it needs in order to record that it ran.
        from sqlalchemy import text as _sa_text

        connection.execute(
            _sa_text(
                "ALTER TABLE IF EXISTS alembic_version_be "
                "ALTER COLUMN version_num TYPE VARCHAR(64)"
            )
        )
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            # See offline-mode docstring above — keeps sky-be heads in
            # ``alembic_version_be`` so sky-ai's rows in the legacy
            # ``alembic_version`` table never confuse our stamp/upgrade.
            version_table="alembic_version_be",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
