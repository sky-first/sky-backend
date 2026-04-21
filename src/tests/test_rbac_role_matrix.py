"""RBAC role matrix — incremental coverage per role, aggregated.

See docs/rbac-role-test-matrix.md for the full 150-case matrix.

Architecture:
  - Seed ONCE per test run (all roles + space + agent).
  - One Python test iterates every (case, role) pair via the sync
    `client` fixture and records the outcome in a list.
  - At the end, assert the failure list is empty. Individual failures
    are reported as f"{case_id}[{role}] expected X got Y".

This beats pytest.mark.parametrize on two axes — which was hanging
the test runner for ~25×5 = 125 combinations because each needed its
own fixture cycle.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Literal

import pytest

ROLES = ["explorer", "navigator", "commander", "platform_admin", "owner"]
ROLE_IDX = {r: i for i, r in enumerate(ROLES)}


Expect = Literal["allow", "deny"]


def _expect_for_role(allowed_from: str, role: str) -> Expect:
    return "allow" if ROLE_IDX[role] >= ROLE_IDX[allowed_from] else "deny"


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _check(resp, expected: Expect) -> tuple[bool, str]:
    code = resp.status_code
    if expected == "allow":
        ok = code < 400
    else:
        ok = code in (403, 404)
    return ok, f"status={code}"


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

    for role in ROLES:
        platform_role = (
            "owner" if role == "owner"
            else "admin" if role == "platform_admin"
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
    space = Space(name="RBAC Test Space", created_by=commander.id)
    db_session.add(space)
    await db_session.flush()

    for r in ("commander", "navigator", "explorer"):
        db_session.add(SpaceMember(
            space_id=space.id,
            user_id=users[r].id,
            role=r,
        ))

    agent = Agent(
        name="RBAC test agent",
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
    }


@pytest.fixture
def seeded(db_session) -> dict:
    import nest_asyncio  # type: ignore
    nest_asyncio.apply()
    return asyncio.get_event_loop().run_until_complete(_seed_async(db_session))


# -----------------------------------------------------------------------------
# Case definition
# -----------------------------------------------------------------------------


def _cases(seeded) -> list[tuple[str, str, Callable]]:
    """Return a list of (case_id, min_role, call_fn). call_fn takes
    (client, role) and returns the response."""
    sp = seeded["space_id"]
    ag = seeded["agent_id"]
    expl_id = str(seeded["users"]["explorer"].id)

    def get(path):
        return lambda client, role: client.get(path, headers=_auth_headers(seeded["tokens"][role]))

    def post(path, body):
        return lambda client, role: client.post(path, json=body, headers=_auth_headers(seeded["tokens"][role]))

    def put(path, body):
        return lambda client, role: client.put(path, json=body, headers=_auth_headers(seeded["tokens"][role]))

    def delete(path):
        return lambda client, role: client.delete(path, headers=_auth_headers(seeded["tokens"][role]))

    return [
        # Section I — read (baseline Explorer)
        ("I-01", "explorer", get("/api/v1/spaces")),
        ("I-02", "explorer", get(f"/api/v1/spaces/{sp}")),
        ("I-03", "explorer", get(f"/api/v1/spaces/{sp}/members")),
        ("I-05", "explorer", get(f"/api/v1/spaces/{sp}/connections")),
        ("I-08", "explorer", get("/api/v1/agents/")),
        ("I-09", "explorer", get(f"/api/v1/agents/{ag}")),
        ("I-10", "explorer", get(f"/api/v1/agents/{ag}/findings")),
        ("I-12", "explorer", get(f"/api/v1/agents/{ag}/metrics")),
        ("I-24", "explorer", get("/api/v1/users/me")),
        ("I-25", "explorer", get("/api/v1/auth/session")),
        ("I-30", "platform_admin", get("/api/v1/audit-logs/")),

        # Section II — write (baseline Navigator)
        ("II-31", "navigator", post("/api/v1/agents/", {
            "name": "rbac-agent",
            "archetype": "custom",
            "scope": "space",
            "scope_id": sp,
            "monitor_type": "question",
            "focus": "test",
            "frequency": "daily",
            "connection_ids": [],
        })),
        ("II-34", "navigator", post(f"/api/v1/agents/{ag}/pause", {})),
        ("II-36", "navigator", put(f"/api/v1/agents/{ag}", {"name": "updated"})),

        # Section III — manage (baseline Commander)
        ("III-61", "commander", post(f"/api/v1/spaces/{sp}/members", {
            "user_id": expl_id,
            "role": "navigator",
        })),
        ("III-64", "commander", post("/api/v1/crews/", {
            "name": "rbac-crew",
            "space_id": sp,
        })),

        # Section IV — platform (baseline Admin)
        ("IV-91", "platform_admin", post("/api/v1/spaces/", {
            "name": "rbac-space",
            "description": "rbac",
        })),
        ("IV-96", "platform_admin", get("/api/v1/users/")),
        ("IV-99", "platform_admin", get("/api/v1/agents/metrics/summary")),
    ]


# -----------------------------------------------------------------------------
# Aggregated test — one function, reports full grid
# -----------------------------------------------------------------------------


def test_rbac_role_matrix(seeded, client, capsys):
    """One run, all cases × all roles, collect failures. On failure,
    print the full grid so you can see the shape of the breakage.

    Exit code green ⇒ every cell matches the matrix. Red ⇒ at least
    one cell is wrong; each failure line names the case and role."""
    cases = _cases(seeded)
    failures: list[str] = []
    grid: list[str] = []

    import sys
    for case_id, min_role, fn in cases:
        sys.stderr.write(f"\n>> {case_id} ")
        sys.stderr.flush()
        row = [case_id.ljust(8)]
        for role in ROLES:
            sys.stderr.write(f"{role[:3]} ")
            sys.stderr.flush()
            expected = _expect_for_role(min_role, role)
            resp = fn(client, role)
            ok, info = _check(resp, expected)
            mark = "✓" if ok else f"✗({info})"
            if not ok:
                failures.append(
                    f"{case_id}[{role}] expected={expected} {info} body={resp.text[:120]}"
                )
            row.append(f"{role[:3]}:{mark}")
        grid.append("  ".join(row))

    # Print always — capsys picks it up and pytest -s makes it visible.
    print("\n=== RBAC role matrix ===")
    print(f"{'case'.ljust(8)}  " + "  ".join(r[:3].ljust(15) for r in ROLES))
    for row in grid:
        print(row)
    print("========================")

    assert not failures, (
        f"{len(failures)} RBAC cells wrong:\n" + "\n".join(failures[:30])
    )
