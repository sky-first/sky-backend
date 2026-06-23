"""Bootstrap a tenant DB so end-to-end login works (Projeto A — operational).

Given a tenant slug, this script:

  1. Reads the row from ``tenant_registry`` (must already exist — run
     ``seed_tenants.py`` first).
  2. Builds the tenant's DB URL with the same logic the
     ``TenantConnectionManager`` uses (``TENANT_DB_URL_TEMPLATE`` env
     var first, then platform creds fallback).
  3. Runs ``alembic upgrade head`` against that URL — every Sky schema
     table appears in the tenant DB.
  4. Creates a default admin user inside the tenant DB so somebody can
     actually log in. Email defaults to ``admin@<slug>.local``;
     password is ``ChangeMe!2026`` (rotate after first login).

Usage::

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db \\
    POSTGRES_PASSWORD=postgres \\
    TENANT_DB_URL_TEMPLATE=postgresql+asyncpg://postgres:postgres@localhost:5432/{db_name} \\
        venv/Scripts/python.exe scripts/bootstrap_tenant.py alpha

After this runs, the tenant's API + UI become fully functional:

    https://workspace-alpha.skyfirstlabs.com   →  alpha's DB
    https://workspace-beta.skyfirstlabs.com    →  beta's DB

The script is idempotent — re-running upgrades to the current Alembic
head and re-creates the admin user if missing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Make ``src.*`` importable when running as ``python scripts/bootstrap_tenant.py``.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402
from src.config.tenant_connection_manager import TenantConnectionManager  # noqa: E402
from src.core.security import get_password_hash  # noqa: E402
from src.core.tenant_context import TenantContext  # noqa: E402
from src.models.tenant import Tenant  # noqa: E402
from src.models.user import User  # noqa: E402

# Pull the rest of the model registry so SQLAlchemy mapper resolution
# does not blow up when create_test_user references foreign tables.
import src.models  # noqa: F401, E402


DEFAULT_ADMIN_PASSWORD = "ChangeMe!2026"


async def _load_registry_row(slug: str) -> Tenant:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(select(Tenant).where(Tenant.slug == slug))
        ).scalar_one_or_none()
        if row is None:
            raise SystemExit(
                f"No tenant_registry row for slug={slug!r}. " f"Run scripts/seed_tenants.py first."
            )
        return row


def _tenant_db_url(tenant: Tenant) -> str:
    """Reuse the manager's URL builder so we hit the same DB the
    runtime will route to. Builds a synthetic TenantContext that
    matches the registry row, then asks the manager."""
    ctx = TenantContext(
        slug=tenant.slug,
        id=tenant.id,
        tier=tenant.tier,
        display_name=tenant.display_name,
        db_host=tenant.db_host,
        db_name=tenant.db_name,
        db_credentials_secret_arn=tenant.db_credentials_secret_arn or "",
        redis_host=tenant.redis_host,
        redis_credentials_secret_arn=tenant.redis_credentials_secret_arn or "",
    )
    return TenantConnectionManager()._build_url(ctx)


def _alembic_url_for_subprocess(async_url: str) -> str:
    """Alembic uses the sync psycopg2 driver. Strip the +asyncpg suffix
    so the subprocess can connect with the standard sqlalchemy URL."""
    return async_url.replace("+asyncpg", "")


def _run_alembic_upgrade(tenant_db_url: str) -> None:
    """Run ``alembic upgrade head`` against ``tenant_db_url``.

    We can't reuse the in-process Alembic API here because the rest of
    the app has already initialised SQLAlchemy with the platform URL.
    A subprocess with a fresh DATABASE_URL is the cleanest swap.

    NOTE for local dev (Projeto A operational): the bundled postgres
    docker image does not have the pgvector extension installed. Two
    migrations (``add_context_documents_20260415`` and
    ``e6e9eef87b74_add_knowledge_library_tables``) issue
    ``CREATE EXTENSION IF NOT EXISTS vector`` and fail without it.
    If you hit that, the workaround is to clone the platform DB's
    schema into the tenant DB and stamp alembic_version directly:

        docker exec sky_poc_postgres pg_dump -U postgres --schema-only \\
            --no-owner --no-acl -d ai_saas_db \\
            | grep -v 'EXTENSION.*vector' \\
            | docker exec -i sky_poc_postgres psql -U postgres -d tenant_<slug>
        docker exec sky_poc_postgres psql -U postgres -d tenant_<slug> -c \\
            "INSERT INTO alembic_version VALUES ('<current head>');"

    On real EKS / Aurora deployments pgvector is installed and this
    function works as written.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = _alembic_url_for_subprocess(tenant_db_url)
    # src.config.settings has a model validator that rebuilds
    # DATABASE_URL from POSTGRES_* env vars whenever POSTGRES_PASSWORD
    # is set — which would clobber our tenant URL. Strip those before
    # spawning so the alembic subprocess respects DATABASE_URL verbatim.
    for legacy in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    ):
        env.pop(legacy, None)
    cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    print(f"  $ DATABASE_URL=…/{tenant_db_url.rsplit('/', 1)[-1]}  alembic upgrade head")
    result = subprocess.run(
        cmd,
        env=env,
        cwd=str(Path(__file__).parent.parent),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("    stdout:")
        print("    " + result.stdout.replace("\n", "\n    "))
        print("    stderr:")
        print("    " + result.stderr.replace("\n", "\n    "))
        raise SystemExit(
            f"alembic upgrade failed for tenant DB (exit {result.returncode}).\n"
            f"If the error mentions ``vector.control``, follow the local-dev\n"
            f"workaround documented at the top of _run_alembic_upgrade."
        )
    print("    [OK] migrations applied")


async def _seed_tenant_registry_row(
    tenant: Tenant,
    tenant_db_url: str,
) -> None:
    """Copy the platform's ``tenant_registry`` row into the tenant's own DB.

    Why: ``/api/v1/auth/methods`` (and other code paths that read tenant
    metadata via ``select(Tenant).where(Tenant.slug == …)``) hit whichever
    DB the BE pod is connected to. The platform BE pod hits the platform
    DB; the dedicated tenant BE pod (Model B) hits the tenant's own DB.
    Without this seed step the tenant DB's ``tenant_registry`` is empty,
    so the BE falls back to ``DEFAULT_AUTH_METHODS`` (Google-only) and
    the Owner's create-tenant choices (password / Azure / Okta) silently
    vanish from /login.

    Idempotent: ON CONFLICT (slug) DO UPDATE on the columns the Owner is
    allowed to change post-create (auth_methods, feature_flags, tier,
    rate limits, display_name). Connection strings + secrets ARNs are
    re-asserted in case the platform row got renamed; the registry is
    the single source of truth for routing data.
    """
    engine = create_async_engine(tenant_db_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            existing = (
                await session.execute(select(Tenant).where(Tenant.slug == tenant.slug))
            ).scalar_one_or_none()
            if existing is None:
                copy = Tenant(
                    id=tenant.id,
                    slug=tenant.slug,
                    display_name=tenant.display_name,
                    tier=tenant.tier,
                    db_host=tenant.db_host,
                    db_port=tenant.db_port,
                    db_name=tenant.db_name,
                    db_credentials_secret_arn=tenant.db_credentials_secret_arn,
                    redis_host=tenant.redis_host,
                    redis_credentials_secret_arn=tenant.redis_credentials_secret_arn,
                    bedrock_inference_profile_arn=tenant.bedrock_inference_profile_arn,
                    rate_limit_rpm=tenant.rate_limit_rpm,
                    rate_limit_tpm=tenant.rate_limit_tpm,
                    is_active=tenant.is_active,
                    sso_provider=tenant.sso_provider,
                    sso_config=tenant.sso_config or {},
                    sso_domain_restriction=tenant.sso_domain_restriction,
                    custom_domain=tenant.custom_domain,
                    feature_flags=tenant.feature_flags or {},
                    capacity_limits=tenant.capacity_limits or {},
                    auth_methods=tenant.auth_methods or {},
                )
                session.add(copy)
                await session.commit()
                print(f"    [OK] tenant_registry row for {tenant.slug!r} " f"seeded into tenant DB")
            else:
                # Refresh the mutable Owner-visible columns; leave the
                # ID alone so any FKs pointing at it stay valid.
                existing.display_name = tenant.display_name
                existing.tier = tenant.tier
                existing.rate_limit_rpm = tenant.rate_limit_rpm
                existing.rate_limit_tpm = tenant.rate_limit_tpm
                existing.is_active = tenant.is_active
                existing.sso_provider = tenant.sso_provider
                existing.sso_config = tenant.sso_config or {}
                existing.sso_domain_restriction = tenant.sso_domain_restriction
                existing.custom_domain = tenant.custom_domain
                existing.feature_flags = tenant.feature_flags or {}
                existing.capacity_limits = tenant.capacity_limits or {}
                existing.auth_methods = tenant.auth_methods or {}
                await session.commit()
                print(
                    f"    [OK] tenant_registry row for {tenant.slug!r} " f"refreshed in tenant DB"
                )
    finally:
        await engine.dispose()


async def _create_admin_user(
    tenant: Tenant,
    tenant_db_url: str,
    admin_email: Optional[str],
    admin_password: str,
) -> None:
    """Idempotent admin-user creation inside the tenant DB."""
    email = admin_email or f"admin@{tenant.slug}.local"

    engine = create_async_engine(tenant_db_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_maker() as session:
            existing = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if existing is not None:
                existing.password_hash = get_password_hash(admin_password)
                existing.role = "admin"
                existing.email_verified = True
                existing.has_completed_onboarding = True
                await session.commit()
                print(f"    [OK] admin user {email!r} refreshed")
                return

            admin = User(
                email=email,
                password_hash=get_password_hash(admin_password),
                name=f"{tenant.display_name} Admin",
                role="admin",
                email_verified=True,
                has_completed_onboarding=True,
            )
            session.add(admin)
            await session.commit()
            print(f"    [OK] admin user {email!r} created")
    finally:
        await engine.dispose()


async def bootstrap(
    slug: str,
    admin_email: Optional[str],
    admin_password: str,
) -> None:
    print(f"\n== Bootstrapping tenant {slug!r} ==")
    tenant = await _load_registry_row(slug)
    tenant_db_url = _tenant_db_url(tenant)
    print(f"  registry row found: tier={tenant.tier} db_name={tenant.db_name}")

    _run_alembic_upgrade(tenant_db_url)
    await _seed_tenant_registry_row(tenant, tenant_db_url)
    await _create_admin_user(tenant, tenant_db_url, admin_email, admin_password)
    print(f"  [DONE] tenant {slug!r} ready for login")


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="Tenant slug (must exist in tenant_registry)")
    parser.add_argument(
        "--admin-email",
        default=None,
        help="Override admin email (default: admin@<slug>.local)",
    )
    parser.add_argument(
        "--admin-password",
        default=DEFAULT_ADMIN_PASSWORD,
        help=f"Override admin password (default: {DEFAULT_ADMIN_PASSWORD})",
    )
    args = parser.parse_args()
    asyncio.run(
        bootstrap(
            slug=args.slug,
            admin_email=args.admin_email,
            admin_password=args.admin_password,
        )
    )


if __name__ == "__main__":
    _cli()
