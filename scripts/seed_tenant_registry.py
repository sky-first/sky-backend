"""Seed (or refresh) the tenant_registry row inside a tenant DB.

Why this exists: tenant pods (Model B) run against their own dedicated
Postgres DB. The platform's tenant_registry table doesn't ship to them
automatically, so the BE on a tenant pod can't answer questions like
"which auth methods did the Owner enable for me?" — it would query its
own DB, find nothing, and silently fall back to DEFAULT_AUTH_METHODS
(Google-only). Owner choices for password / Azure / Okta vanish.

This script runs INSIDE the tenant cluster, against the tenant's own
``DATABASE_URL``, with the row data passed via env vars by the workflow
that created the tenant. No platform-DB access required.

Env vars (all required unless marked optional):

    DATABASE_URL                 — tenant DB (already in every BE/migrate pod)
    TENANT_SEED_SLUG             — e.g. "gbt"
    TENANT_SEED_ID               — UUID of the platform row (so FKs match)
    TENANT_SEED_DISPLAY_NAME
    TENANT_SEED_TIER             — starter / foundation / core / advanced / strategic
    TENANT_SEED_DB_HOST
    TENANT_SEED_DB_PORT          — optional, default 5432
    TENANT_SEED_DB_NAME
    TENANT_SEED_DB_SECRET_ARN
    TENANT_SEED_REDIS_HOST
    TENANT_SEED_REDIS_SECRET_ARN
    TENANT_SEED_BEDROCK_ARN      — optional
    TENANT_SEED_RATE_LIMIT_RPM   — optional, default 60
    TENANT_SEED_RATE_LIMIT_TPM   — optional, default 50000
    TENANT_SEED_SSO_PROVIDER
    TENANT_SEED_SSO_CONFIG       — JSON, default '{}'
    TENANT_SEED_SSO_DOMAIN_RESTR — optional
    TENANT_SEED_CUSTOM_DOMAIN    — optional
    TENANT_SEED_FEATURE_FLAGS    — JSON, default '{}'
    TENANT_SEED_CAPACITY_LIMITS  — JSON, default '{}'
    TENANT_SEED_AUTH_METHODS     — JSON, e.g. '{"password":true,"google":false,...}'

Idempotent: an existing row is updated in place on the mutable Owner
columns (auth_methods, feature_flags, tier, etc.); the ID is preserved
so FKs that already point at it stay valid.

Used by the migrate Job command in ``gitops/bootstrap/clients/{slug}``
values files. The workflow that creates a new tenant injects the
TENANT_SEED_* env vars when it copies the chart values template.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

# Import the model registry so SQLAlchemy mapper resolution doesn't
# choke on related tables when the Tenant constructor runs.
import src.models  # noqa: F401, E402
from src.models.tenant import Tenant  # noqa: E402


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"{name} env var required")
    return v


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _json_env(name: str, default: str = "{}") -> dict:
    raw = os.environ.get(name) or default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{name} must decode to a JSON object")
    return parsed


def _prepare_async_url(url: str) -> str:
    """Strip libpq ``sslmode`` query param so asyncpg doesn't choke on it.

    The migrate Job command passes the platform-style URL with
    ``sslmode=require`` for psycopg2 compatibility; asyncpg rejects
    that as a kwarg. Move it into a ``ssl`` query param so SQLAlchemy
    forwards it as a connect_args entry on asyncpg's side via the
    ``connect_args`` we set below — but the simplest cross-version
    fix is to drop the param here and let asyncpg default to TLS.
    """
    parsed = urlparse(url)
    if not parsed.query:
        return url
    keep = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k != "sslmode"]
    return urlunparse(parsed._replace(query=urlencode(keep)))


async def main() -> int:
    db_url = _require("DATABASE_URL")
    if "+asyncpg" not in db_url:
        # Migrate Job env keeps the platform-style URL (no +asyncpg);
        # bend it for the async session here.
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    db_url = _prepare_async_url(db_url)

    slug = _require("TENANT_SEED_SLUG")
    raw_id = _require("TENANT_SEED_ID")
    try:
        tenant_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise SystemExit(f"TENANT_SEED_ID is not a valid UUID: {exc}") from exc

    display_name = _require("TENANT_SEED_DISPLAY_NAME")
    tier = _require("TENANT_SEED_TIER")
    db_host = _require("TENANT_SEED_DB_HOST")
    db_port = int(_opt("TENANT_SEED_DB_PORT", "5432"))
    db_name = _require("TENANT_SEED_DB_NAME")
    db_credentials_secret_arn = _require("TENANT_SEED_DB_SECRET_ARN")
    redis_host = _require("TENANT_SEED_REDIS_HOST")
    redis_credentials_secret_arn = _require("TENANT_SEED_REDIS_SECRET_ARN")
    bedrock_arn = _opt("TENANT_SEED_BEDROCK_ARN") or None
    rate_rpm = int(_opt("TENANT_SEED_RATE_LIMIT_RPM", "60"))
    rate_tpm = int(_opt("TENANT_SEED_RATE_LIMIT_TPM", "50000"))
    sso_provider = _require("TENANT_SEED_SSO_PROVIDER")
    sso_config = _json_env("TENANT_SEED_SSO_CONFIG")
    sso_domain_restriction = _opt("TENANT_SEED_SSO_DOMAIN_RESTR") or None
    custom_domain = _opt("TENANT_SEED_CUSTOM_DOMAIN") or None
    feature_flags = _json_env("TENANT_SEED_FEATURE_FLAGS")
    capacity_limits = _json_env("TENANT_SEED_CAPACITY_LIMITS")
    auth_methods = _json_env("TENANT_SEED_AUTH_METHODS")

    if not isinstance(auth_methods, dict) or not auth_methods:
        raise SystemExit(
            "TENANT_SEED_AUTH_METHODS must be a non-empty JSON object "
            "(e.g. '{\"password\":true,\"google\":false}')"
        )

    print(f"  seeding tenant_registry row for slug={slug!r} into tenant DB")
    print(f"  auth_methods={auth_methods}")

    engine = create_async_engine(db_url, echo=False)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            existing = (
                await session.execute(select(Tenant).where(Tenant.slug == slug))
            ).scalar_one_or_none()
            if existing is None:
                row = Tenant(
                    id=tenant_id,
                    slug=slug,
                    display_name=display_name,
                    tier=tier,
                    db_host=db_host,
                    db_port=db_port,
                    db_name=db_name,
                    db_credentials_secret_arn=db_credentials_secret_arn,
                    redis_host=redis_host,
                    redis_credentials_secret_arn=redis_credentials_secret_arn,
                    bedrock_inference_profile_arn=bedrock_arn,
                    rate_limit_rpm=rate_rpm,
                    rate_limit_tpm=rate_tpm,
                    is_active=True,
                    sso_provider=sso_provider,
                    sso_config=sso_config,
                    sso_domain_restriction=sso_domain_restriction,
                    custom_domain=custom_domain,
                    feature_flags=feature_flags,
                    capacity_limits=capacity_limits,
                    auth_methods=auth_methods,
                )
                session.add(row)
                await session.commit()
                print(f"  [OK] tenant_registry row INSERTED for {slug!r}")
            else:
                existing.display_name = display_name
                existing.tier = tier
                existing.db_host = db_host
                existing.db_port = db_port
                existing.db_name = db_name
                existing.db_credentials_secret_arn = db_credentials_secret_arn
                existing.redis_host = redis_host
                existing.redis_credentials_secret_arn = redis_credentials_secret_arn
                existing.bedrock_inference_profile_arn = bedrock_arn
                existing.rate_limit_rpm = rate_rpm
                existing.rate_limit_tpm = rate_tpm
                existing.sso_provider = sso_provider
                existing.sso_config = sso_config
                existing.sso_domain_restriction = sso_domain_restriction
                existing.custom_domain = custom_domain
                existing.feature_flags = feature_flags
                existing.capacity_limits = capacity_limits
                existing.auth_methods = auth_methods
                await session.commit()
                print(f"  [OK] tenant_registry row UPDATED for {slug!r}")
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
