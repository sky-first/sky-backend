"""Add the route block to api/v1/console.py."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.resolve()
p = ROOT / "src/api/v1/console.py"
src = p.read_text(encoding="utf-8")

if "/tenants/{slug}/db-config" in src:
    print("SKIP - already applied")
    sys.exit(0)

ROUTES_OLD = (
    "# -- CSM notes (B#17) ----\n"
)

# Locate insertion point precisely
marker = "# ── CSM notes (B#17) ─"
idx = src.find(marker)
if idx == -1:
    # fallback: find the older comment without box-drawing
    marker = "# CSM notes (B#17)"
    idx = src.find(marker)
if idx == -1:
    print("FAIL: marker not found", file=sys.stderr)
    sys.exit(2)

# Find start of the line containing the marker
line_start = src.rfind("\n", 0, idx) + 1

ROUTES_NEW = '''# ── Per-tenant DB / Redis config (GBT deploy, PR #19) ──────────────


# 30 chars covers ``arn:aws:secretsmanager:eu-west-1:`` - enough to
# attribute a change to a region but not to the secret itself. The
# operator can always re-read the full value via GET /db-config.
_AUDIT_SECRET_PREFIX_LEN = 30


def _mask_secret_arn(value: Optional[str]) -> Optional[str]:
    """Replace a Secrets Manager ARN with its first 30 chars + ellipsis.

    Returned unchanged when ``None`` or shorter than the prefix length.
    """
    if value is None:
        return None
    if len(value) <= _AUDIT_SECRET_PREFIX_LEN:
        return value
    return value[:_AUDIT_SECRET_PREFIX_LEN] + "..."


def _redact_db_config_payload(changes: dict) -> dict:
    """Build the payload stored in ``InternalConsoleAudit.request_payload``.

    Host/port/name pass through verbatim - they are public operational
    knowledge. The two ``*_secret_arn`` fields get prefix-only
    treatment so the audit log cannot pivot to customer DB creds.
    """
    masked = dict(changes)
    for key in ("db_credentials_secret_arn", "redis_credentials_secret_arn"):
        if key in masked:
            masked[key] = _mask_secret_arn(masked[key])
    return masked


@router.get(
    "/tenants/{slug}/db-config",
    response_model=TenantDbConfigRead,
)
async def get_tenant_db_config(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantDbConfigRead:
    """Return the 6 connection fields currently stored on the registry row.

    Read-only; no audit entry (the parent ``/tenants/{slug}`` GET
    already produces one).
    """
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantDbConfigRead.model_validate(row)


@router.patch(
    "/tenants/{slug}/db-config",
    response_model=TenantDbConfigRead,
)
async def update_tenant_db_config(
    slug: str,
    request: Request,
    payload: TenantDbConfigUpdate,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantDbConfigRead:
    """Patch any subset of the tenant's data-plane connection details.

    Empty payloads are refused (422). All writes go through one
    transaction and end with ``clear_tenant_cache`` so the resolver
    rebuilds the engine on the next request.

    Audit: ``UPDATE_DB_CONFIG`` is emitted on success and failure.
    Secret ARNs are masked in ``request_payload`` (30-char prefix +
    ellipsis); host/port/name are logged verbatim.

    Does NOT restart the tenant API pods - the FE banner warns the
    operator that the change only takes effect after the next pod
    rollout (open question; see PR description).
    """
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "no_fields_supplied",
                "detail": "Provide at least one field to update.",
            },
        )

    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        await audit_action(
            db,
            actor=user,
            action=AuditAction.UPDATE_DB_CONFIG,
            tenant_slug=slug,
            result=AuditResult.FAILURE,
            result_details={"reason": "not_found"},
            actor_ip=_ip(request),
        )
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Snapshot the previous values for the audit trail.
    previous = {key: getattr(row, key) for key in changes.keys()}

    for key, value in changes.items():
        setattr(row, key, value)
    await db.flush()

    # The resolver caches the tenant context on first resolve.
    from src.api.middleware.tenant_resolver import clear_tenant_cache

    clear_tenant_cache()

    await audit_action(
        db,
        actor=user,
        action=AuditAction.UPDATE_DB_CONFIG,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        request_payload={
            "changed_fields": sorted(changes.keys()),
            "new_values": _redact_db_config_payload(changes),
        },
        result_details={
            "previous_values": _redact_db_config_payload(previous),
        },
        actor_ip=_ip(request),
    )
    return TenantDbConfigRead.model_validate(row)


@router.post(
    "/tenants/{slug}/db-config/test",
    response_model=TenantDbConfigTestResult,
    responses={503: {"model": TenantDbConfigTestResult}},
)
async def test_tenant_db_config(
    slug: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantDbConfigTestResult:
    """Open a transient connection to the tenant's Postgres and run ``SELECT 1``.

    Nothing is persisted regardless of outcome. The Console "Test
    connection" button calls this so the operator can verify the
    registry row points at a reachable DB.

    503 + ``ok=false`` on any connection / auth failure; the asyncpg
    / Secrets Manager error message is forwarded.
    ``TEST_DB_CONFIG`` audit entry written either way.
    """
    import asyncio
    import time

    from src.config.tenant_connection_manager import (
        TenantConnectionManager,
    )
    from src.core.tenant_context import TenantContext

    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    ctx = TenantContext(
        slug=row.slug,
        id=row.id,
        tier=row.tier,
        display_name=row.display_name,
        db_host=row.db_host,
        db_name=row.db_name,
        db_credentials_secret_arn=row.db_credentials_secret_arn,
    )

    # Reach into the manager only for the URL builder.
    manager = TenantConnectionManager()

    started = time.monotonic()
    error_message: Optional[str] = None
    ok = False
    try:
        from sqlalchemy import text as _text
        from sqlalchemy.ext.asyncio import create_async_engine

        url = manager._build_url(ctx)  # noqa: SLF001
        engine = create_async_engine(
            url,
            pool_pre_ping=False,
            pool_size=1,
            max_overflow=0,
            connect_args={"timeout": 5},
        )
        try:
            async with asyncio.timeout(8):
                async with engine.connect() as conn:
                    result = await conn.execute(_text("SELECT 1"))
                    _ = result.scalar()
                    ok = True
        finally:
            await engine.dispose()
    except asyncio.TimeoutError:
        error_message = "Connection attempt timed out after 8s"
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {str(exc)[:200]}"

    latency_ms = int((time.monotonic() - started) * 1000)

    await audit_action(
        db,
        actor=user,
        action=AuditAction.TEST_DB_CONFIG,
        tenant_slug=slug,
        result=AuditResult.SUCCESS if ok else AuditResult.FAILURE,
        request_payload={
            "target_host": row.db_host,
            "target_db": row.db_name,
        },
        result_details={
            "latency_ms": latency_ms,
            "error": error_message,
        },
        actor_ip=_ip(request),
    )

    result_payload = TenantDbConfigTestResult(
        ok=ok,
        latency_ms=latency_ms,
        error=error_message,
        target_host=row.db_host,
        target_db=row.db_name,
    )
    if not ok:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503, content=result_payload.model_dump()
        )
    return result_payload


'''

new_src = src[:line_start] + ROUTES_NEW + src[line_start:]
p.write_text(new_src, encoding="utf-8")
print("OK - routes inserted at offset", line_start)
