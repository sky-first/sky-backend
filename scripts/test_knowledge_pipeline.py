"""End-to-end test: uploads a document, waits for processing, queries the AI.

Usage (with both services running):
    python scripts/test_knowledge_pipeline.py

Requirements:
    - sky-poc-backend running on :8000  (or set BACKEND_URL)
    - sky-poc-ai running on :8001       (or set AI_URL)
    - Celery worker running:
        celery -A src.workers.celery_app worker -Q knowledge --loglevel=info
    - A valid JWT token for a commander-role user (set TOKEN or BACKEND_URL includes creds)

The test document is an in-memory .txt file — no real file needed on disk.
"""

from __future__ import annotations

import os
import sys
import time
import uuid

import httpx

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
AI     = os.getenv("AI_URL",      "http://localhost:8001")
TOKEN  = os.getenv("TEST_TOKEN",  "")         # JWT bearer token
SCOPE  = os.getenv("TEST_SCOPE",  "personal")
SCOPE_ID = os.getenv("TEST_SCOPE_ID", "")     # required for crew/space

HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

# ── Document we'll use as test content ────────────────────────────────────────
TEST_FILENAME = "sky_test_revenue_report.txt"
TEST_CONTENT  = b"""SKY PLATFORM — Q1 2025 REVENUE REPORT

Executive Summary
Total revenue for Q1 2025 reached $4.2 million, a 38% increase year-over-year.
The growth was primarily driven by enterprise subscription renewals and expansion
in the LATAM market, which contributed $1.1 million (26% of total).

Product Performance
- Platform subscriptions:    $2.8M   (67% of revenue)
- Professional services:     $0.9M   (21% of revenue)
- Marketplace commissions:   $0.5M   (12% of revenue)

Key Metrics
- Monthly Active Users (MAU):  12,400  (+52% YoY)
- Average Revenue per User:    $338
- Net Revenue Retention (NRR): 118%
- Customer Acquisition Cost:   $1,240

Risks & Outlook
Churn risk is concentrated in the SMB segment (< 50 seats). Q2 target is $5.0M
with pipeline coverage of 2.4×. The APAC expansion planned for Q3 adds an
estimated $0.6M in incremental ARR.
"""

MIME = "text/plain"


def step(msg: str) -> None:
    print(f"\n{'─'*60}\n▶  {msg}")


def ok(msg: str) -> None:
    print(f"   ✅  {msg}")


def fail(msg: str) -> None:
    print(f"   ❌  {msg}")
    sys.exit(1)


def main() -> None:
    client = httpx.Client(timeout=60.0)

    # ── 1. Request upload URL ─────────────────────────────────────────────────
    step("Step 1 — Request SAS upload URL")
    body: dict = {
        "filename": TEST_FILENAME,
        "mime_type": MIME,
        "size_bytes": len(TEST_CONTENT),
        "scope": SCOPE,
    }
    if SCOPE_ID:
        body["scope_id"] = SCOPE_ID

    r = client.post(f"{BACKEND}/knowledge/upload-url", json=body, headers=HEADERS)
    if r.status_code != 200:
        fail(f"upload-url returned {r.status_code}: {r.text}")
    data = r.json()
    file_id   = data["file_id"]
    upload_url = data["upload_url"]
    ok(f"file_id={file_id}")
    ok(f"upload_url={upload_url[:80]}...")

    # ── 2. PUT the blob ───────────────────────────────────────────────────────
    step("Step 2 — PUT blob to upload URL")
    put_r = httpx.put(upload_url, content=TEST_CONTENT,
                      headers={"Content-Type": MIME}, timeout=30)
    if put_r.status_code not in (200, 201):
        fail(f"PUT blob returned {put_r.status_code}: {put_r.text}")
    ok("Blob uploaded")

    # ── 3. Confirm upload ─────────────────────────────────────────────────────
    step("Step 3 — Confirm upload (triggers Celery worker)")
    r = client.post(f"{BACKEND}/knowledge/{file_id}/confirm",
                    json={"sha256_hash": None}, headers=HEADERS)
    if r.status_code != 200:
        fail(f"confirm returned {r.status_code}: {r.text}")
    ok(f"status={r.json().get('status')}")

    # ── 4. Poll until ready ───────────────────────────────────────────────────
    step("Step 4 — Polling for status=ready (max 60s)")
    deadline = time.time() + 60
    while time.time() < deadline:
        r = client.get(f"{BACKEND}/knowledge/{file_id}", headers=HEADERS)
        if r.status_code != 200:
            fail(f"get file returned {r.status_code}")
        info = r.json()
        status = info.get("status")
        chunks = info.get("chunks_count", 0)
        print(f"   status={status}  chunks={chunks}", end="\r", flush=True)
        if status == "ready" and chunks > 0:
            print()
            ok(f"File ready — {chunks} chunks created")
            break
        if status == "error":
            print()
            fail(f"Worker reported error: {info.get('processing_error')}")
        time.sleep(3)
    else:
        fail("Timed out waiting for file to reach status=ready")

    # ── 5. Call the AI with a question about the document ─────────────────────
    step("Step 5 — Query the AI with a question about the document")
    question = "What was the total Q1 2025 revenue and which market drove LATAM growth?"

    # Call AI service directly (bypasses auth, useful for dev/test)
    ai_payload = {
        "question": question,
        "user_id": str(uuid.uuid4()),
        "space_id": SCOPE_ID or str(uuid.uuid4()),
        "is_personal": SCOPE == "personal",
        "mentioned_file_ids": [file_id],
    }

    # Try the connection-level query endpoint (requires a connection_id)
    # For a pure knowledge query, use the backend chat endpoint instead
    backend_payload = {
        "question": question,
        "space_id": SCOPE_ID or None,
        "is_personal": SCOPE == "personal",
        "mentioned_file_ids": [file_id],
    }
    r = client.post(f"{BACKEND}/ai/query", json=backend_payload, headers=HEADERS, timeout=90)
    if r.status_code != 200:
        fail(f"AI query returned {r.status_code}: {r.text[:500]}")

    result = r.json()
    answer  = result.get("answer", "")
    meta    = result.get("meta") or {}
    cites   = meta.get("citations") or []

    print(f"\n   Answer:\n   {answer[:400]}")
    print(f"\n   Citations ({len(cites)}):")
    for c in cites:
        print(f"     • [{c.get('score', 0):.2f}] {c.get('file_name')} p.{c.get('page_number')} — {c.get('excerpt', '')[:80]}")

    if not answer:
        fail("AI returned empty answer")
    ok(f"Answer received ({len(answer)} chars)")

    if cites:
        ok(f"{len(cites)} citation(s) returned ← AI used the document ✓")
        matching = [c for c in cites if file_id in (c.get("file_id") or "")]
        if matching:
            ok(f"Citation correctly references our file_id")
        else:
            print("   ⚠️  Citations present but none reference our file_id — check scope filter")
    else:
        print("   ⚠️  No citations returned.")
        print("      This means either:")
        print("        a) The AI answered from SQL data, not the knowledge file")
        print("        b) The scope filter didn't include this file (check user_id/space_id)")
        print("        c) Cosine similarity was below the 0.25 threshold")

    # ── 6. Cleanup ────────────────────────────────────────────────────────────
    step("Step 6 — Delete the test file")
    r = client.delete(f"{BACKEND}/knowledge/{file_id}", headers=HEADERS)
    if r.status_code in (200, 204):
        ok("Test file deleted")
    else:
        print(f"   ⚠️  Delete returned {r.status_code} (not critical)")

    print(f"\n{'='*60}")
    print("Pipeline test complete.")


if __name__ == "__main__":
    if not TOKEN:
        print("⚠️  TEST_TOKEN not set. Set it with:")
        print("   export TEST_TOKEN=<jwt>")
        print("   Continuing without auth (will fail on protected endpoints).\n")
    main()
