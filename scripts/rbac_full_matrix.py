"""Standalone RBAC matrix runner — no pytest, full control.

Reads src/tests/data/rbac_inventory.tsv and runs every
(endpoint, role) combination against an in-process FastAPI TestClient
backed by a fresh SQLite in-memory DB.

Usage:
    ./venv/bin/python scripts/rbac_full_matrix.py
"""

# CRITICAL env overrides — MUST happen before ANY src.* import.
# Follows the pattern in src/tests/conftest.py.
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
# File-backed SQLite so multiple connections can see the same tables
# (in-memory + NullPool gives each conn a blank DB; in-memory + StaticPool
# forces single-conn deadlock under async dep chains). File + default
# pool = fast, parallel-safe, self-cleaning on exit.
_DB_FILE = Path("/tmp/rbac_matrix.db")
if _DB_FILE.exists():
    _DB_FILE.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["LOG_LEVEL"] = "WARNING"

import logging

logging.getLogger().setLevel(logging.WARNING)

import asyncio
import csv
import json
import time
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# STEP 1: Import the database module and REPLACE its engine + session
# factory with StaticPool variants BEFORE src.main (or any other module
# that captures AsyncSessionLocal into its own namespace) imports it.
# NullPool on :memory: gives every session a FRESH blank DB — seed is
# invisible to the app. StaticPool keeps one shared connection.
from src.config import database as db_mod  # noqa: E402

_shared_engine = create_async_engine(
    os.environ["DATABASE_URL"],
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)
_shared_sessionmaker = async_sessionmaker(
    _shared_engine, class_=AsyncSession, expire_on_commit=False
)
db_mod.engine = _shared_engine
db_mod.AsyncSessionLocal = _shared_sessionmaker

# src.main's lifespan calls init_db() on startup. init_db() does
# engine.dispose() + create_all — on an in-memory SQLite dispose drops
# the DB entirely, wiping seeded users. Neutralize it.
async def _noop_init_db():
    return None

db_mod.init_db = _noop_init_db

# STEP 2: now that the global refs point at our StaticPool engine,
# pull in everything else.
from src.config.database import Base  # noqa: E402
from src.core.security import create_access_token, get_password_hash  # noqa: E402
from src.main import app  # noqa: E402
from src.models.agent import Agent  # noqa: E402
from src.models.crew import Crew, CrewMember  # noqa: E402
from src.models.space import Space, SpaceMember  # noqa: E402

# Silence SQL noise.
for name in (
    "sqlalchemy.engine", "sqlalchemy.engine.Engine",
    "sqlalchemy.pool", "src.api.middleware.auth",
    "src.core.middleware.correlation", "httpx",
):
    logging.getLogger(name).setLevel(logging.WARNING)

# Kill asyncio background activity tracking. The get_current_user
# dependency schedules _track_activity() via asyncio.ensure_future; on
# StaticPool (single connection) those background writes serialize with
# the main request and cause the entire matrix to deadlock after a few
# minutes. We don't care about last_active_at in the RBAC probe.
from src.repositories.user import UserRepository

async def _noop_update_last_active(self, *args, **kwargs):
    return None

UserRepository.update_last_active_atomic = _noop_update_last_active
UserRepository.update_last_active = _noop_update_last_active

ROLES = ["explorer", "navigator", "commander", "admin", "owner"]
ROLE_IDX = {r: i for i, r in enumerate(ROLES)}

HERE = Path(__file__).parent
INVENTORY_TSV = HERE.parent / "src" / "tests" / "data" / "rbac_inventory.tsv"
RESULT_JSON = Path("/tmp/rbac_matrix_result.json")


def expect_for_role(min_role: str, role: str) -> str:
    if min_role not in ROLE_IDX:
        return "allow"
    return "allow" if ROLE_IDX[role] >= ROLE_IDX[min_role] else "deny"


def check(status: int, expected: str) -> bool:
    """RBAC-only check.

    For `expected=allow`: any status that is not an explicit RBAC block
    (401/403). Handler may still 404/422/5xx on fake data — not RBAC.

    For `expected=deny`: pass if the role was explicitly blocked (401/
    403) or the resource is hidden (404). Also pass on 422 when the
    request was rejected by Pydantic body validation BEFORE reaching
    the RBAC layer — since the role never got to *do* anything, that
    is not a leak. Similarly 307 (redirect) when the endpoint does
    trailing-slash normalization — httpx does not follow redirects so
    the role still did not succeed.

    Any 2xx on expected=deny IS a real leak (role executed the action).
    """
    if isinstance(status, str):  # EXC:*
        return False
    if expected == "allow":
        return status not in (401, 403)
    # deny
    if status in (401, 403, 404):
        return True
    if status == 422:  # body rejected upstream of RBAC
        return True
    if status in (307, 308):  # redirect not followed → role did not act
        return True
    return False


async def seed() -> dict:
    async with _shared_sessionmaker() as session:
        user_repo = UserRepository(session)
        users, tokens = {}, {}
        for role in ROLES:
            platform_role = (
                "owner" if role == "owner"
                else "admin" if role == "admin"
                else "member"
            )
            u = await user_repo.create(
                email=f"{role}@rbactest.example.com",
                password_hash=get_password_hash("test"),
                name=role.title(),
                role=platform_role,
            )
            users[role] = u
            tokens[role] = create_access_token({
                "sub": str(u.id), "email": u.email, "role": platform_role,
            })

        # Separate "target" user used as {user_id} substitution — kept out
        # of the request-issuing pool so concurrent DELETE /users/{id} can't
        # wipe a logged-in tester mid-run (caused 401 cascades on explorer).
        target = await user_repo.create(
            email="target@rbactest.example.com",
            password_hash=get_password_hash("test"),
            name="Target",
            role="member",
        )

        commander = users["commander"]
        space = Space(name="RBAC Space", created_by=commander.id)
        session.add(space)
        await session.flush()
        for r in ("commander", "navigator", "explorer"):
            session.add(SpaceMember(
                space_id=space.id, user_id=users[r].id, role=r,
            ))
        # Also seed a crew with the same membership pattern so crew-scoped
        # endpoints resolve roles instead of defaulting to "guest".
        crew = Crew(
            name="RBAC Crew", space_id=space.id, created_by=commander.id,
        )
        session.add(crew)
        await session.flush()
        for r in ("commander", "navigator", "explorer"):
            session.add(CrewMember(
                crew_id=crew.id, user_id=users[r].id, role=r,
            ))
        agent = Agent(
            name="RBAC agent", archetype="custom", scope="space",
            scope_id=str(space.id), status="active", monitor_type="question",
            focus="What?", frequency="daily", connection_ids=[],
            created_by=commander.id,
        )
        session.add(agent)

        # Seed the single support_settings row the migration inserts on
        # prod. Without it, POST /support/sessions short-circuits to 403
        # "Sky Support access is disabled".
        from src.models.support import SupportSettings
        session.add(SupportSettings(
            access_enabled=True,
            require_ticket_id=False,
            allowed_modes=["read_only"],
            auto_revoke_after_minutes=240,
        ))
        await session.commit()
        return {
            "users": {k: {"id": str(v.id), "email": v.email} for k, v in users.items()},
            "tokens": tokens,
            "space_id": str(space.id),
            "agent_id": str(agent.id),
            "crew_id": str(crew.id),
            "target_user_id": str(target.id),
        }


def substitute(path: str, seed_data: dict) -> str:
    import re
    subs = {
        "{space_id}": seed_data["space_id"],
        "{agent_id}": seed_data["agent_id"],
        "{crew_id}": seed_data["crew_id"],
        "{user_id}": seed_data["target_user_id"],
        "{provider}": "google",
        "{source_table}": "agents",
        "{table_name}": "users",
    }
    out = path
    for k, v in subs.items():
        out = out.replace(k, v)
    out = re.sub(r"\{[^}]+\}", lambda m: str(uuid4()), out)
    return out


def body_for(method: str):
    return {} if method in ("POST", "PUT", "PATCH") else None


def load_inventory():
    with open(INVENTORY_TSV) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [
        r for r in rows
        if r["min_role"] != "public" and r.get("skip_matrix") != "true"
    ]


async def run():
    print("[rbac] create_all...", flush=True)
    t0 = time.time()
    async with _shared_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"[rbac] schema ready in {time.time()-t0:.1f}s", flush=True)

    print("[rbac] seeding...", flush=True)
    seed_data = await seed()
    print(f"[rbac] seeded space={seed_data['space_id'][:8]} "
          f"agent={seed_data['agent_id'][:8]}", flush=True)

    cases = load_inventory()
    print(f"[rbac] {len(cases)} cases × {len(ROLES)} roles = "
          f"{len(cases)*len(ROLES)} cells", flush=True)

    # Fresh session per request via NullPool + file-backed SQLite: every
    # connection hits the same DB file so seeded data is visible, and
    # NullPool avoids StaticPool's single-conn deadlock with async dep
    # chains (get_current_user depends on get_db_session opening its own
    # conn for last_active tracking etc).
    from src.api.deps import get_db_session as _deps_get_db_session
    from src.config.database import get_db as _cfg_get_db

    async def _override_get_db():
        async with _shared_sessionmaker() as session:
            yield session

    app.dependency_overrides[_cfg_get_db] = _override_get_db
    app.dependency_overrides[_deps_get_db_session] = _override_get_db

    results = []
    failures = []

    # Async client with ASGI transport — fire requests concurrently so
    # the 1275 cells run in ~1 min instead of ~30 min serial. TestClient
    # is sync and holds the event loop, which is what caused each request
    # to take 1-2s even when the handler returns in ms.
    transport = httpx.ASGITransport(app=app)
    CONCURRENCY = 10
    REQ_TIMEOUT = 5.0

    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=REQ_TIMEOUT,
    ) as client:
        owner_token = seed_data["tokens"]["owner"]
        t0 = time.time()
        sanity = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        print(f"[sanity] /auth/me owner -> {sanity.status_code} in {time.time()-t0:.2f}s", flush=True)
        if sanity.status_code != 200:
            print("[sanity] ABORT — seed invisible to app", flush=True)
            return

        # Build the flat task list: one coroutine per (case, role).
        async def _make_call(method, url, body, headers):
            if method == "GET":
                return await client.get(url, headers=headers)
            if method == "DELETE":
                return await client.delete(url, headers=headers)
            if method == "POST":
                return await client.post(url, json=body, headers=headers)
            if method == "PUT":
                return await client.put(url, json=body, headers=headers)
            if method == "PATCH":
                return await client.patch(url, json=body, headers=headers)
            return None

        async def run_one(row, role):
            method = row["method"]
            full_path = substitute(row["full_path"], seed_data)
            url = f"/api/v1{full_path}"
            min_role = row["min_role"]
            body = body_for(method)
            expected = expect_for_role(min_role, role)
            token = seed_data["tokens"][role]
            headers = {"Authorization": f"Bearer {token}"}
            try:
                # Hard 8s per-call cap — some handlers ignore httpx's
                # own timeout (await deep in asyncio.ensure_future).
                resp = await asyncio.wait_for(
                    _make_call(method, url, body, headers), timeout=8.0
                )
                if resp is None:
                    return None
                status = resp.status_code
            except asyncio.TimeoutError:
                return {
                    "case": f"{method} {row['full_path']}",
                    "role": role, "expected": expected,
                    "min_role": min_role,
                    "status": "EXC:Timeout",
                    "ok": False,
                }
            except Exception as e:
                return {
                    "case": f"{method} {row['full_path']}",
                    "role": role, "expected": expected,
                    "min_role": min_role,
                    "status": f"EXC:{type(e).__name__}",
                    "ok": False,
                }
            ok = check(status, expected)
            return {
                "case": f"{method} {row['full_path']}",
                "role": role, "expected": expected,
                "min_role": min_role, "status": status, "ok": ok,
            }

        sem = asyncio.Semaphore(CONCURRENCY)

        async def gated(row, role):
            async with sem:
                return await run_one(row, role)

        tasks = []
        for row in cases:
            for role in ROLES:
                tasks.append(asyncio.create_task(gated(row, role)))

        print(f"[rbac] dispatching {len(tasks)} tasks, concurrency={CONCURRENCY}", flush=True)
        t_loop = time.time()
        done_count = 0
        for fut in asyncio.as_completed(tasks):
            entry = await fut
            done_count += 1
            if entry is None:
                continue
            results.append(entry)
            if not entry["ok"]:
                failures.append(entry)
            if done_count % 100 == 0:
                elapsed = time.time() - t_loop
                rate = done_count / max(elapsed, 0.01)
                print(f"[rbac] {done_count}/{len(tasks)} ({rate:.0f} req/s)", flush=True)
                # Incremental dump so a crash doesn't lose everything.
                RESULT_JSON.write_text(json.dumps({
                    "in_progress": True,
                    "done": done_count, "total": len(tasks),
                    "passed": sum(1 for r in results if r["ok"]),
                    "failed": sum(1 for r in results if not r["ok"]),
                    "results": results,
                }))

    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    print(f"\n=== RBAC Full Matrix — {total} cells ===", flush=True)
    print(f"Pass: {passed} ({100*passed/max(total,1):.1f}%)")
    print(f"Fail: {len(failures)}")

    RESULT_JSON.write_text(json.dumps({
        "total": total, "passed": passed, "failed": len(failures),
        "results": results,
    }, indent=2))
    print(f"\nFull results → {RESULT_JSON}", flush=True)

    if failures:
        from collections import defaultdict
        by_ep = defaultdict(list)
        for f in failures:
            by_ep[f["case"]].append(f)
        print(f"\nFailing endpoints ({len(by_ep)}):")
        for ep, fs in list(by_ep.items())[:60]:
            roles = ", ".join(
                f"{f['role'][:3]}(exp={f['expected']} got={f['status']})"
                for f in fs
            )
            print(f"  {ep} [min={fs[0]['min_role']}] -> {roles}")


if __name__ == "__main__":
    asyncio.run(run())
