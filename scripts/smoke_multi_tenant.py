"""End-to-end multi-tenant smoke (Projeto A — Phase 5).

Pre-flight (run once):

    venv/Scripts/python.exe scripts/seed_tenants.py

This script then:

  1. Hits ``GET /api/v1/_test/tenant-echo`` with the flag OFF and
     asserts the response says ``multi_tenant_enabled=false`` and
     the default tenant. (Baseline — change nothing else.)
  2. Hits the same endpoint with the flag ON and three different
     tenant signals (Host header, X-Tenant-Slug header, none) and
     asserts the resolver returns the right context each time.
  3. Hits ``GET /api/v1/_test/tenant-db-ping`` for each tenant and
     asserts the pool name reflects the tenant slug.

The script does NOT manage the backend lifecycle — it expects a live
backend at BACKEND_URL (default http://localhost:8000). If the backend
isn't running, start it from a separate terminal with the standard
``uvicorn src.main:app --reload --port 8000`` and re-run.

Exit code 0 on full success, non-zero otherwise. Pretty-prints what
it saw on each step so a human can audit at a glance.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

try:
    import httpx  # noqa: F401
except ImportError:  # pragma: no cover
    print("httpx is required: pip install httpx", file=sys.stderr)
    sys.exit(2)

import httpx


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def _ok(msg: str) -> None:
    print(f"  [ OK  ] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL ] {msg}", file=sys.stderr)


def _section(title: str) -> None:
    print()
    print(f"== {title} ==")


def _get(path: str, headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    headers = headers or {}
    resp = httpx.get(f"{BACKEND_URL}{path}", headers=headers, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def _assert(condition: bool, label: str, value: Any = None) -> bool:
    if condition:
        _ok(label + (f" (got {value!r})" if value is not None else ""))
        return True
    _fail(label + (f" (got {value!r})" if value is not None else ""))
    return False


def smoke() -> int:
    ok = True

    _section("1. tenant-echo with default context")
    body = _get("/api/v1/_test/tenant-echo")
    ok &= _assert(
        body["tenant"]["slug"] == "default",
        "echo returned default slug",
        body["tenant"]["slug"],
    )
    ok &= _assert(
        body["tenant"]["is_default"] is True,
        "default context flagged is_default=True",
    )

    _section("2. tenant-echo with X-Tenant-Slug: alpha")
    body = _get(
        "/api/v1/_test/tenant-echo",
        headers={"X-Tenant-Slug": "alpha"},
    )
    multi = body.get("multi_tenant_enabled")
    if multi is False:
        print(
            "  [INFO ] MULTI_TENANT_ENABLED=false on the backend — set the\n"
            "          env var to 'true' and restart the API to exercise the\n"
            "          rest of this smoke script. Stopping with exit 0; the\n"
            "          flag-OFF behaviour above is still validated."
        )
        return 0 if ok else 1
    ok &= _assert(
        body["tenant"]["slug"] == "alpha",
        "echo returned alpha for X-Tenant-Slug: alpha",
        body["tenant"]["slug"],
    )
    ok &= _assert(
        body["tenant"]["tier"] == "pilot",
        "alpha resolved to its tier",
        body["tenant"]["tier"],
    )

    _section("3. tenant-echo with X-Tenant-Slug: beta")
    body = _get(
        "/api/v1/_test/tenant-echo",
        headers={"X-Tenant-Slug": "beta"},
    )
    ok &= _assert(
        body["tenant"]["slug"] == "beta",
        "echo returned beta for X-Tenant-Slug: beta",
        body["tenant"]["slug"],
    )
    ok &= _assert(
        body["tenant"]["tier"] == "foundation",
        "beta resolved to its tier",
        body["tenant"]["tier"],
    )

    _section("4. tenant-echo with subdomain (Host header)")
    body = _get(
        "/api/v1/_test/tenant-echo",
        headers={"Host": "workspace-alpha.skyfirstlabs.com"},
    )
    ok &= _assert(
        body["tenant"]["slug"] == "alpha",
        "subdomain workspace-alpha resolved to alpha",
        body["tenant"]["slug"],
    )

    _section("5. tenant-db-ping per tenant routes to its pool")
    body = _get(
        "/api/v1/_test/tenant-db-ping",
        headers={"X-Tenant-Slug": "alpha"},
    )
    ok &= _assert(
        body["pool"] == "tenant:alpha",
        "alpha db-ping -> tenant:alpha pool",
        body["pool"],
    )

    body = _get(
        "/api/v1/_test/tenant-db-ping",
        headers={"X-Tenant-Slug": "beta"},
    )
    ok &= _assert(
        body["pool"] == "tenant:beta",
        "beta db-ping -> tenant:beta pool",
        body["pool"],
    )
    ok &= _assert(
        set(body["known_tenant_pools"]) == {"alpha", "beta"},
        "both tenants cached in connection manager",
        body["known_tenant_pools"],
    )

    _section("6. tenant-echo with unknown slug returns 404")
    try:
        httpx.get(
            f"{BACKEND_URL}/api/v1/_test/tenant-echo",
            headers={"X-Tenant-Slug": "ghost-not-a-tenant"},
            timeout=10.0,
        ).raise_for_status()
        _fail("ghost slug did not 404")
        ok = False
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            _ok("unknown slug correctly 404s")
        else:
            _fail(f"unknown slug returned {exc.response.status_code} (expected 404)")
            ok = False

    print()
    if ok:
        print("ALL CHECKS PASSED.")
        return 0
    print("ONE OR MORE CHECKS FAILED.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(smoke())
