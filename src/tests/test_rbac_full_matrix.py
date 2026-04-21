"""RBAC full matrix — every endpoint × every role.

Reads src/tests/data/rbac_inventory.tsv (295 rows) and runs
one HTTP call per (endpoint, role) combination, then asserts the
observed status code matches the expected allow/deny classification.

Role hierarchy: explorer < navigator < commander < admin < owner.

allow = status < 400 OR validation error (400/422) — means RBAC let the
        request through to the business logic.
deny  = 401/403/404 — means RBAC blocked (404 counts as hidden-deny).

Endpoints classified as `public` (pre-auth) are skipped from the role
matrix — they have no role semantics.

Path placeholders like `{space_id}` are substituted from the seeded
fixtures; unknown placeholders become random UUIDs.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
from typing import Literal
from uuid import uuid4

import pytest

# Silence app + SQL chatter so the 1300-cell run doesn't produce MB of logs.
# Each request otherwise emits ~6 INFO lines via structlog + the engine logger.
for name in (
    "sqlalchemy.engine", "sqlalchemy.pool",
    "src.api.middleware.auth",
    "src.core.middleware.correlation",
    "src.core.middleware",
    "httpx", "uvicorn", "uvicorn.access",
):
    logging.getLogger(name).setLevel(logging.WARNING)
# Root at WARNING — covers anything we forgot above.
logging.getLogger().setLevel(logging.WARNING)

ROLES = ["explorer", "navigator", "commander", "admin", "owner"]
ROLE_IDX = {r: i for i, r in enumerate(ROLES)}

Expect = Literal["allow", "deny"]

HERE = os.path.dirname(__file__)
INVENTORY = os.path.join(HERE, "data", "rbac_inventory.tsv")


def _expect_for_role(min_role: str, role: str) -> Expect:
    """Decide allow/deny for a given cell.

    Base rule: every logged-in user is at least explorer. Endpoints
    classified as `explorer` must allow every role from the matrix."""
    if min_role not in ROLE_IDX:
        return "allow"  # defensive; should not happen
    return "allow" if ROLE_IDX[role] >= ROLE_IDX[min_role] else "deny"


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _check(status_code: int, expected: Expect) -> bool:
    if expected == "allow":
        # RBAC passed — anything that is not a hard-deny is fine
        return status_code not in (401, 403, 404)
    # RBAC should deny
    return status_code in (401, 403, 404)


# -----------------------------------------------------------------------------
# Seed
# -----------------------------------------------------------------------------


async def _seed_async(db_session) -> dict:
    from src.core.security import create_access_token, get_password_hash
    from src.models.agent import Agent
    from src.models.space import Space, SpaceMember
    from src.repositories.user import UserRepository

    user_repo = UserRepository(db_session)
    users: dict[str, object] = {}
    tokens: dict[str, str] = {}

    # Platform role column values: "owner" | "admin" | "member"
    # (commander/navigator/explorer do not exist at the platform layer)
    for role in ROLES:
        platform_role = (
            "owner" if role == "owner"
            else "admin" if role == "admin"
            else "member"
        )
        u = await user_repo.create(
            email=f"{role}@rbac-test.local",
            password_hash=get_password_hash("test"),
            name=role.title(),
            role=platform_role,
        )
        users[role] = u
        tokens[role] = create_access_token({
            "sub": str(u.id),
            "email": u.email,
            "role": platform_role,
        })

    commander = users["commander"]
    space = Space(name="RBAC Full Matrix Space", created_by=commander.id)
    db_session.add(space)
    await db_session.flush()

    for r in ("commander", "navigator", "explorer"):
        db_session.add(SpaceMember(
            space_id=space.id,
            user_id=users[r].id,
            role=r,
        ))

    agent = Agent(
        name="RBAC full-matrix agent",
        archetype="custom",
        scope="space",
        scope_id=str(space.id),
        status="active",
        monitor_type="question",
        focus="What is happening?",
        frequency="daily",
        connection_ids=[],
        created_by=commander.id,
    )
    db_session.add(agent)
    await db_session.commit()

    return {
        "users": users,
        "tokens": tokens,
        "space_id": str(space.id),
        "agent_id": str(agent.id),
        "explorer_id": str(users["explorer"].id),
        "target_user_id": str(users["explorer"].id),
    }


@pytest.fixture
def seeded(db_session) -> dict:
    import nest_asyncio  # type: ignore
    nest_asyncio.apply()
    return asyncio.get_event_loop().run_until_complete(_seed_async(db_session))


# -----------------------------------------------------------------------------
# Inventory loader
# -----------------------------------------------------------------------------


def _load_inventory() -> list[dict]:
    rows = []
    with open(INVENTORY) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows.append(r)
    return rows


def _substitute(path: str, seed: dict) -> str:
    subs = {
        "{space_id}": seed["space_id"],
        "{agent_id}": seed["agent_id"],
        "{user_id}": seed["target_user_id"],
        "{provider}": "google",
        "{source_table}": "agents",
        "{table_name}": "users",
    }
    out = path
    # Known placeholders first
    for k, v in subs.items():
        out = out.replace(k, v)
    # Anything remaining {*} → random uuid (expected to give 404 if RBAC would allow,
    # which is treated as allow; if RBAC denies, the 403 comes before the 404 lookup)
    import re
    out = re.sub(r"\{[^}]+\}", lambda m: str(uuid4()), out)
    return out


def _body_for(method: str) -> dict:
    if method in ("POST", "PUT", "PATCH"):
        return {}
    return None


# -----------------------------------------------------------------------------
# The big test
# -----------------------------------------------------------------------------


def test_rbac_full_matrix(seeded, client, capsys):
    """For every endpoint × every role, verify RBAC matches the inventory.

    Iterates 295 endpoints × 5 roles = 1475 cells. Collects failures and
    reports the grid. Public endpoints are skipped (no role semantics).
    """
    import sys
    print("\n[rbac-full] loading inventory...", flush=True)
    inv = _load_inventory()
    cases = [
        r for r in inv
        if r["min_role"] != "public" and r.get("skip_matrix") != "true"
    ]
    print(f"[rbac-full] {len(cases)} cases × {len(ROLES)} roles = "
          f"{len(cases)*len(ROLES)} cells", flush=True)
    failures: list[dict] = []
    pass_count = 0
    skip_count = 0

    import sys

    for idx, row in enumerate(cases):
        method = row["method"]
        full_path = _substitute(row["full_path"], seeded)
        min_role = row["min_role"]
        url = f"/api/v1{full_path}"

        # Progress dot every 10 cases, via print to get captured tail
        if idx % 10 == 0:
            print(f"[rbac-full] {idx}/{len(cases)} {method} {full_path[:55]}", flush=True)

        body = _body_for(method)

        for role in ROLES:
            expected = _expect_for_role(min_role, role)
            headers = _auth_headers(seeded["tokens"][role])
            try:
                if method == "GET":
                    resp = client.get(url, headers=headers)
                elif method == "DELETE":
                    resp = client.delete(url, headers=headers)
                elif method == "POST":
                    resp = client.post(url, json=body, headers=headers)
                elif method == "PUT":
                    resp = client.put(url, json=body, headers=headers)
                elif method == "PATCH":
                    resp = client.patch(url, json=body, headers=headers)
                else:
                    skip_count += 1
                    continue
            except Exception as e:
                failures.append({
                    "method": method,
                    "path": row["full_path"],
                    "role": role,
                    "expected": expected,
                    "got": f"EXC:{type(e).__name__}",
                    "min_role": min_role,
                })
                continue

            ok = _check(resp.status_code, expected)
            if ok:
                pass_count += 1
            else:
                failures.append({
                    "method": method,
                    "path": row["full_path"],
                    "role": role,
                    "expected": expected,
                    "got": resp.status_code,
                    "min_role": min_role,
                    "body": resp.text[:120] if hasattr(resp, "text") else "",
                })

    total = pass_count + len(failures)
    print(f"\n\n=== RBAC Full Matrix ===")
    print(f"Total cells: {total} (+ {skip_count} skipped)")
    print(f"Pass:        {pass_count}")
    print(f"Fail:        {len(failures)}")
    print(f"Pass rate:   {100*pass_count/max(total,1):.1f}%")
    print()

    if failures:
        # Group failures by endpoint for readability
        from collections import defaultdict
        by_ep = defaultdict(list)
        for f in failures:
            key = f"{f['method']} {f['path']}"
            by_ep[key].append(f)

        print(f"--- First 50 failing endpoints (of {len(by_ep)}) ---")
        for i, (ep, fs) in enumerate(list(by_ep.items())[:50]):
            min_role = fs[0]["min_role"]
            roles_summary = ", ".join(
                f"{f['role'][:3]}={f['expected']}/{f['got']}" for f in fs
            )
            print(f"  {ep} [min={min_role}] -> {roles_summary}")

    assert not failures, (
        f"{len(failures)}/{total} RBAC cells wrong. See stdout for breakdown."
    )
