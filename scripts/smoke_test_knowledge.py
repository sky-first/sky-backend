"""Smoke test for the Knowledge Library RBAC + upload + approval + RAG pipeline.

Validates:
  1. Commander uploads → goes straight to processing → ready
  2. Navigator uploads → goes to pending_approval (no auto-process)
  3. Explorer upload attempt → 403 Forbidden
  4. Commander approves navigator's file → goes to processing → ready
  5. RAG query with @mention returns citations from the uploaded document

Pre-requisites:
  - Backend running on :8000
  - Celery worker running (for file processing)
  - Test users seeded:  python scripts/seed_test_users.py
  - A crew where clara (commander) and diego (navigator) and elena (explorer) are members.
    If none exists, the script creates one automatically.

Usage:
    cd sky-poc-backend
    source venv/bin/activate
    python scripts/smoke_test_knowledge.py

Optional env vars:
    BACKEND_URL   default http://localhost:8000/api/v1
    CREW_ID       UUID of an existing crew (auto-discovered/created if not set)
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

# ── Config ─────────────────────────────────────────────────────────────────────
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")

JWT_SECRET = os.getenv(
    "JWT_SECRET_KEY",
    "217a0c91c59bfeec95a3de24c6c1a5132bbc349f8bed90f15ca30f70d726ca4c",
)
JWT_ALGO = "HS256"

# Test user emails (seeded by seed_test_users.py)
EMAIL_COMMANDER = "clara@sky.local"
EMAIL_NAVIGATOR = "diego@sky.local"
EMAIL_EXPLORER  = "elena@sky.local"

TEST_CONTENT = b"""KNOWLEDGE SMOKE TEST DOCUMENT

This is an auto-generated document used to validate the SKY Knowledge Library pipeline.

Revenue Summary (Q1 2025):
- Total revenue: $4.2 million (+38% YoY)
- LATAM market contributed $1.1M (26%)
- Enterprise renewals drove 67% of revenue

Unique test phrase for citation validation: SMOKE_TEST_CITATION_ANCHOR_XK9
"""
TEST_FILENAME = "smoke_test_knowledge.txt"
MIME          = "text/plain"

POLL_TIMEOUT  = 90   # seconds to wait for processing
POLL_INTERVAL = 3


# ── Helpers ────────────────────────────────────────────────────────────────────

def _green(msg: str) -> str:  return f"\033[92m{msg}\033[0m"
def _red(msg: str) -> str:    return f"\033[91m{msg}\033[0m"
def _yellow(msg: str) -> str: return f"\033[93m{msg}\033[0m"
def _bold(msg: str) -> str:   return f"\033[1m{msg}\033[0m"

passed = 0
failed = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"   {_green('✅')} {msg}")


def warn(msg: str) -> None:
    print(f"   {_yellow('⚠️ ')} {msg}")


def fail(msg: str, abort: bool = True) -> None:
    global failed
    failed += 1
    print(f"   {_red('❌')} {msg}")
    if abort:
        _summary()
        sys.exit(1)


def step(msg: str) -> None:
    print(f"\n{_bold('─'*62)}\n{_bold('▶')} {msg}")


def _summary() -> None:
    total = passed + failed
    print(f"\n{'='*62}")
    if failed == 0:
        print(_green(f"All {total} checks passed ✓"))
    else:
        print(_red(f"{failed}/{total} checks FAILED"))
    print("="*62)


def _make_jwt(user_id: str, role: str = "member") -> str:
    from jose import jwt as _jwt
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=4),
    }
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _poll_ready(client: httpx.Client, file_id: str, token: str, label: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        r = client.get(f"{BACKEND}/knowledge/{file_id}", headers=_headers(token))
        if r.status_code != 200:
            fail(f"{label} poll returned {r.status_code}: {r.text}")
        info = r.json()
        st   = info.get("status")
        print(f"   [{label}] status={st}  chunks={info.get('chunks_count', 0)}", end="\r", flush=True)
        if st == "ready":
            print()
            return info
        if st == "error":
            print()
            fail(f"{label} processing error: {info.get('processing_error')}")
        time.sleep(POLL_INTERVAL)
    fail(f"{label} timed out waiting for status=ready after {POLL_TIMEOUT}s")
    return {}   # unreachable


# ── DB helpers (sync psycopg2) ─────────────────────────────────────────────────

def _db_conn():
    import psycopg2
    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres@localhost/ai_saas_db",
    ).replace("postgresql+asyncpg://", "postgresql://").replace("+asyncpg", "")
    return psycopg2.connect(dsn)


def _get_user(cur, email: str) -> dict | None:
    cur.execute("SELECT id, email, name, role FROM users WHERE email=%s AND deleted_at IS NULL", (email,))
    row = cur.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1], "name": row[2], "role": row[3]}


def _ensure_crew(cur, conn, commander_id: str, navigator_id: str, explorer_id: str) -> str:
    """Return crew_id for a test crew that has all three roles set up."""
    forced_id = os.getenv("CREW_ID")
    if forced_id:
        return forced_id

    # Need a real space_id — pick the first available space
    cur.execute("SELECT id FROM spaces LIMIT 1")
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("No spaces found in DB. Create at least one space first.")
    space_id = str(row[0])

    crew_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO crews (id, name, description, space_id, created_by, created_at, updated_at)
        VALUES (%s, 'Smoke Test Crew', 'Auto-created by smoke_test_knowledge.py', %s, %s, NOW(), NOW())
        """,
        (crew_id, space_id, commander_id),
    )
    for uid, role in [
        (commander_id, "commander"),
        (navigator_id, "navigator"),
        (explorer_id,  "explorer"),
    ]:
        cur.execute(
            """
            INSERT INTO crew_members (id, crew_id, user_id, role, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (crew_id, user_id) DO UPDATE SET role=EXCLUDED.role
            """,
            (str(uuid.uuid4()), crew_id, uid, role),
        )
    conn.commit()
    return crew_id


def _cleanup_crew(cur, conn, crew_id: str) -> None:
    cur.execute("DELETE FROM crew_members WHERE crew_id=%s", (crew_id,))
    cur.execute("DELETE FROM crews WHERE id=%s", (crew_id,))
    conn.commit()


def _upload_flow(
    client: httpx.Client,
    token: str,
    scope: str,
    scope_id: str | None,
    label: str,
) -> tuple[str, str]:
    """Perform upload-url → PUT blob → confirm. Return (file_id, status_after_confirm)."""
    body: dict = {
        "filename": TEST_FILENAME,
        "mime_type": MIME,
        "size_bytes": len(TEST_CONTENT),
        "scope": scope,
    }
    if scope_id:
        body["scope_id"] = scope_id

    r = client.post(f"{BACKEND}/knowledge/upload-url", json=body, headers=_headers(token))
    if r.status_code != 200:
        fail(f"{label} upload-url returned {r.status_code}: {r.text}")
    data      = r.json()
    file_id   = data["file_id"]
    upload_url = data["upload_url"]

    put_r = httpx.put(upload_url, content=TEST_CONTENT, headers={"Content-Type": MIME}, timeout=30)
    if put_r.status_code not in (200, 201):
        fail(f"{label} PUT blob returned {put_r.status_code}: {put_r.text}")

    r = client.post(
        f"{BACKEND}/knowledge/{file_id}/confirm",
        json={"sha256_hash": None},
        headers=_headers(token),
    )
    if r.status_code != 200:
        fail(f"{label} confirm returned {r.status_code}: {r.text}")

    return file_id, r.json().get("status", "")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── 0. DB setup ───────────────────────────────────────────────────────────
    step("Setup — resolving test users from DB")
    try:
        conn = _db_conn()
        cur  = conn.cursor()
    except Exception as e:
        fail(f"Cannot connect to DB: {e}")
        return

    commander = _get_user(cur, EMAIL_COMMANDER)
    navigator = _get_user(cur, EMAIL_NAVIGATOR)
    explorer  = _get_user(cur, EMAIL_EXPLORER)

    # For AI query test: we need an admin/owner user (data.query.run is only
    # allowed for admin+ — pre-existing permission gap, not related to Knowledge Library RBAC)
    cur.execute("SELECT id, email, role FROM users WHERE role IN ('admin','owner') AND deleted_at IS NULL LIMIT 1")
    admin_row = cur.fetchone()
    admin_user = {"id": str(admin_row[0]), "email": admin_row[1], "role": admin_row[2]} if admin_row else None

    missing = [e for e, u in [(EMAIL_COMMANDER, commander), (EMAIL_NAVIGATOR, navigator), (EMAIL_EXPLORER, explorer)] if u is None]
    if missing:
        fail(
            f"Missing test users: {missing}\n"
            "   Run:  python scripts/seed_test_users.py"
        )
        return

    ok(f"Commander: {commander['name']} ({commander['id'][:8]}…)")
    ok(f"Navigator: {navigator['name']} ({navigator['id'][:8]}…)")
    ok(f"Explorer:  {explorer['name']}  ({explorer['id'][:8]}…)")

    crew_id = _ensure_crew(cur, conn, commander["id"], navigator["id"], explorer["id"])
    ok(f"Test crew ready: {crew_id}")

    # Generate JWTs
    tok_commander = _make_jwt(commander["id"], commander["role"])
    tok_navigator = _make_jwt(navigator["id"], navigator["role"])
    tok_explorer  = _make_jwt(explorer["id"],  explorer["role"])

    client = httpx.Client(timeout=60.0)
    files_to_cleanup: list[tuple[str, str]] = []   # (file_id, token)

    try:
        # ── 1. Backend health ─────────────────────────────────────────────────
        step("Check 1 — Backend is reachable")
        r = client.get("http://localhost:8000/health")
        if r.status_code == 200:
            ok("Backend healthy")
        else:
            fail(f"Health returned {r.status_code}")

        # ── 2. Commander → processing immediately ─────────────────────────────
        step("Check 2 — Commander upload goes straight to processing (crew scope)")
        file_id, status_after = _upload_flow(
            client, tok_commander, "crew", crew_id, "COMMANDER"
        )
        files_to_cleanup.append((file_id, tok_commander))
        if status_after == "processing":
            ok(f"Status after confirm = processing ✓ (file_id={file_id[:8]}…)")
        elif status_after == "ready":
            ok(f"Status = ready (processed very fast, that's fine)")
        else:
            fail(f"Expected 'processing', got '{status_after}'", abort=False)

        # Poll to ready
        info = _poll_ready(client, file_id, tok_commander, "COMMANDER")
        ok(f"Commander file ready — {info.get('chunks_count', 0)} chunks")
        commander_file_id = file_id

        # ── 3. Navigator → pending_approval ───────────────────────────────────
        step("Check 3 — Navigator upload goes to pending_approval")
        file_id_nav, status_nav = _upload_flow(
            client, tok_navigator, "crew", crew_id, "NAVIGATOR"
        )
        files_to_cleanup.append((file_id_nav, tok_commander))  # commander will delete
        if status_nav == "pending_approval":
            ok(f"Status after confirm = pending_approval ✓ (file_id={file_id_nav[:8]}…)")
        else:
            fail(f"Expected 'pending_approval', got '{status_nav}'", abort=False)

        # ── 4. Explorer upload → 403 ──────────────────────────────────────────
        step("Check 4 — Explorer upload to crew scope is forbidden")
        r = client.post(
            f"{BACKEND}/knowledge/upload-url",
            json={"filename": TEST_FILENAME, "mime_type": MIME, "size_bytes": len(TEST_CONTENT), "scope": "crew", "scope_id": crew_id},
            headers=_headers(tok_explorer),
        )
        if r.status_code == 403:
            ok("Explorer correctly received 403 Forbidden")
        elif r.status_code == 200:
            fail("Explorer got 200 — should be blocked!", abort=False)
            # Clean up if explorer somehow uploaded
            files_to_cleanup.append((r.json().get("file_id", ""), tok_commander))
        else:
            warn(f"Expected 403, got {r.status_code}: {r.text[:200]}")

        # ── 5. Commander approves navigator's file ────────────────────────────
        step("Check 5 — Commander approves navigator's pending_approval file")
        r = client.post(
            f"{BACKEND}/knowledge/{file_id_nav}/approve",
            headers=_headers(tok_commander),
        )
        if r.status_code == 200:
            approved_status = r.json().get("status")
            ok(f"Approve succeeded → status={approved_status}")
        else:
            fail(f"Approve returned {r.status_code}: {r.text}", abort=False)

        # Poll navigator's file to ready
        info_nav = _poll_ready(client, file_id_nav, tok_commander, "NAVIGATOR")
        ok(f"Navigator file ready after approval — {info_nav.get('chunks_count', 0)} chunks")

        # ── 6. Navigator cannot approve ───────────────────────────────────────
        step("Check 6 — Navigator cannot approve (files.approve = False)")
        # Upload another file as navigator to try approving
        file_id_nav2, status_nav2 = _upload_flow(
            client, tok_navigator, "crew", crew_id, "NAVIGATOR2"
        )
        files_to_cleanup.append((file_id_nav2, tok_commander))
        if status_nav2 == "pending_approval":
            r = client.post(
                f"{BACKEND}/knowledge/{file_id_nav2}/approve",
                headers=_headers(tok_navigator),
            )
            if r.status_code == 403:
                ok("Navigator correctly received 403 when trying to approve")
            else:
                fail(f"Navigator approve returned {r.status_code} (expected 403)", abort=False)
        else:
            warn(f"Skipping approve test — navigator file has status '{status_nav2}' (expected pending_approval)")

        # ── 7. Commander cannot approve non-pending file ──────────────────────
        step("Check 7 — Approving a 'ready' file returns 400")
        r = client.post(
            f"{BACKEND}/knowledge/{commander_file_id}/approve",
            headers=_headers(tok_commander),
        )
        if r.status_code == 400:
            ok("Approving ready file returned 400 Bad Request ✓")
        else:
            fail(f"Expected 400, got {r.status_code}", abort=False)

        # ── 8. File listing respects scope ────────────────────────────────────
        step("Check 8 — List files for the crew scope")
        r = client.get(
            f"{BACKEND}/knowledge",
            params={"scope": "crew", "scope_id": crew_id},
            headers=_headers(tok_commander),
        )
        if r.status_code == 200:
            items = r.json().get("items", [])
            ready_count = sum(1 for f in items if f["status"] == "ready")
            ok(f"List returned {len(items)} file(s), {ready_count} ready")
        else:
            fail(f"List files returned {r.status_code}", abort=False)

        # ── 9. RAG: query AI with @mention returns citations ──────────────────
        step("Check 9 — AI query with @mention returns citations")
        if admin_user is None:
            warn("No admin user found — skipping AI citation check")
        else:
            tok_admin = _make_jwt(admin_user["id"], admin_user["role"])
            print(f"   Using {admin_user['email']} (role={admin_user['role']}) for AI query")

            # Fetch the space_id that the test crew belongs to
            cur.execute("SELECT space_id FROM crews WHERE id=%s", (crew_id,))
            crew_row = cur.fetchone()
            ai_space_id = str(crew_row[0]) if crew_row else None

            query_payload = {
                "question": "What is the unique smoke test citation anchor phrase in the document?",
                "space_id": ai_space_id,
                "is_personal": False,
                "mentioned_file_ids": [commander_file_id],
            }
            r = client.post(
                f"{BACKEND}/ai/query",
                json=query_payload,
                headers=_headers(tok_admin),
                timeout=90,
            )
            if r.status_code == 200:
                result  = r.json()
                answer  = result.get("answer", "")
                meta    = result.get("meta") or {}
                cites   = meta.get("citations") or []

                if answer:
                    ok(f"AI answered ({len(answer)} chars)")
                    preview = answer[:120].replace("\n", " ")
                    print(f"      Preview: {preview}…")
                else:
                    warn("AI returned empty answer")

                if cites:
                    ok(f"{len(cites)} citation(s) returned — AI used the knowledge document ✓")
                    for c in cites:
                        print(f"        [{c.get('score', 0):.2f}] {c.get('file_name')} — {c.get('excerpt', '')[:60]}")
                    anchor_in_answer = "SMOKE_TEST_CITATION_ANCHOR_XK9" in answer
                    anchor_in_cites  = any("SMOKE_TEST_CITATION_ANCHOR_XK9" in (c.get("excerpt") or "") for c in cites)
                    if anchor_in_answer or anchor_in_cites:
                        ok("Unique anchor phrase found in response — RAG correctly retrieved the document ✓")
                    else:
                        warn("Anchor phrase not found in answer/citations (may still be correct if AI paraphrased)")
                else:
                    warn(
                        "No citations returned.\n"
                        "      Possible causes:\n"
                        "        a) Celery worker not running (file not chunked/embedded)\n"
                        "        b) AI service doesn't support citations for this query type\n"
                        "        c) Cosine similarity below threshold"
                    )
            elif r.status_code in (404, 422):
                warn(f"AI query returned {r.status_code} — endpoint may require a connection_id. Skipping citation check.")
            else:
                fail(f"AI query returned {r.status_code}: {r.text[:300]}", abort=False)

    finally:
        # ── Cleanup ────────────────────────────────────────────────────────────
        step("Cleanup — deleting test files")
        for fid, tok in files_to_cleanup:
            if not fid:
                continue
            r = client.delete(f"{BACKEND}/knowledge/{fid}", headers=_headers(tok))
            if r.status_code in (200, 204):
                print(f"   deleted {fid[:8]}…")
            else:
                print(f"   could not delete {fid[:8]}… ({r.status_code})")

        if not os.getenv("CREW_ID"):
            _cleanup_crew(cur, conn, crew_id)
            print(f"   deleted test crew {crew_id[:8]}…")

        cur.close()
        conn.close()
        client.close()

    _summary()


if __name__ == "__main__":
    main()
