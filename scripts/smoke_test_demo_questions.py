#!/usr/bin/env python3
"""Demo-questions contract gate — runs the FE-canonical 20 questions
through the real BE → AI pipeline and exits non-zero on any refusal.

This is the structural answer to the recurring "colleague pushes a
fix, manual test still fails on 3-4 questions" loop:

  1. ``DEMO_QUESTIONS`` below is **the same 20 questions** the demo FE
     surfaces (``sky-poc-frontend/src/lib/demo-questions.ts``). The
     companion ``check_demo_questions_sync.py`` fails CI if the BE
     copy drifts from the FE source.

  2. Each question is fired against the **BE's** ``/api/v1/ai/query``
     using a freshly-provisioned demo JWT — same code path a real
     visitor takes, including BE-side keyword-based connection
     routing.

  3. The pass criterion is intentionally tolerant of LLM
     non-determinism (we don't pin to exact answer strings):
       * HTTP 200 from /ai/query
       * ``status == "completed"``
       * ``chosen_datasets`` is non-empty OR ``sql`` non-empty
       * answer does NOT contain the canonical refusal phrases
         (``I couldn't find any data…``, ``doesn't seem related to
         your data``, ``Your Knowledge layer is empty``, etc.)

  4. Exit code 0 → all 20 pass; non-zero → at least one failed. A
     markdown report is written to ``$REPORT_PATH`` (default
     ``/tmp/demo-questions-report.md``) with per-question detail.

Env vars:
  BE_BASE          base URL of the backend API (e.g.
                   https://sky-stg.example.com). Default
                   http://localhost:8000.
  TURNSTILE_BYPASS any non-empty value lets the script call /demo/signup
                   without solving the captcha (only honoured when the
                   server has TURNSTILE_SECRET_KEY blank — i.e. dev /
                   smoke environments).
  ENV_LABEL        label printed in headings (stg, prd, local, …).
  REPORT_PATH      where to write the markdown report.
  COMPANY_LABEL    company string used in the signup. Drives the
                   ``Demo — {company}`` Space-page name; defaults to a
                   timestamped one so repeated smoke runs don't collide.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------
# 20 demo questions — KEEP IN SYNC with
# sky-poc-frontend/src/lib/demo-questions.ts.
# check_demo_questions_sync.py validates the FE source matches this list.
# ---------------------------------------------------------------------
DEMO_QUESTIONS: list[dict[str, str]] = [
    # ── Revenue (7) ────────────────────────────────────────────────
    {
        "category": "revenue",
        "schema": "crm",
        "q": "How many accounts do we have, and how many are currently active?",
    },
    {
        "category": "revenue",
        "schema": "finance",
        "q": "List the top 10 accounts by total monthly subscription amount",
    },
    {
        "category": "revenue",
        "schema": "crm",
        "q": "How many opportunities are in each stage, and what is the total deal amount per stage?",
    },
    {
        "category": "revenue",
        "schema": "finance",
        "q": "Show total invoice revenue per month for the available data",
    },
    {
        "category": "revenue",
        "schema": "crm",
        "q": "What is the total amount of closed_won opportunities, grouped by account industry?",
    },
    {
        "category": "revenue",
        "schema": "crm",
        "q": "What is the average deal amount for each opportunity stage?",
    },
    {
        "category": "revenue",
        "schema": "finance",
        "q": "Which subscription plan has the highest total monthly_amount across all active subscriptions?",
    },
    # ── Customer health (6) ────────────────────────────────────────
    {
        "category": "customer-health",
        "schema": "product_usage",
        "q": "How many accounts are flagged as 'risk' or 'churn' in our health data?",
    },
    {
        "category": "customer-health",
        "schema": "product_usage",
        "q": "Show me accounts where seats_used is well below seats_paid",
    },
    {
        "category": "customer-health",
        "schema": "product_usage",
        "q": "List accounts that have not logged in in the last 7 days",
    },
    {
        "category": "customer-health",
        "schema": "finance",
        "q": "List all subscriptions that have a cancellation date, including the plan and when they cancelled",
    },
    {
        "category": "customer-health",
        "schema": "product_usage",
        "q": "What is the average health score for each risk level (healthy, watch, risk, churn)?",
    },
    {
        "category": "customer-health",
        "schema": "product_usage",
        "q": "Show account count grouped by risk level",
    },
    # ── Operations & Growth (7) ────────────────────────────────────
    {
        "category": "operations",
        "schema": "marketing",
        "q": "Which marketing channel has the highest total spend?",
    },
    {
        "category": "operations",
        "schema": "marketing",
        "q": "How many leads have a recorded conversion (converted_to_opportunity_id is not null), broken down by lead source?",
    },
    {
        "category": "operations",
        "schema": "web_analytics",
        "q": "Which utm_source drives the most web sessions?",
    },
    {
        "category": "operations",
        "schema": "crm",
        "q": "Show new signup count per month over the last year",
    },
    {
        "category": "operations",
        "schema": "product_usage",
        "q": "Top 5 product features by total usage",
    },
    {
        "category": "operations",
        "schema": "web_analytics",
        "q": "Show the top page_path values by event count from the events table",
    },
    {
        "category": "operations",
        "schema": "marketing",
        "q": "How many email opens and clicks did each campaign generate?",
    },
]

# Canonical refusal phrases the AI emits when it gives up. Any match
# = failure for the gate. Phrases come from
# sky-poc-ai/core/i18n/i18n.py (TECHNICAL_ERROR, NO_DATA_FOUND,
# NO_DATA_GENERIC) and the orchestrator's "doesn't seem related"
# fallback.
REFUSAL_PHRASES: tuple[str, ...] = (
    "I couldn't find any data to answer this question",
    "I couldn't find any data about",
    "Sorry, I couldn't find any data",
    "doesn't seem related to your data",
    "Your Knowledge layer is empty",
    "couldn't find relevant information across any",
    "No enterprise relationships or spaces have been configured",
    "No events or signals have been registered",
)

BE_BASE = os.environ.get("BE_BASE", "http://localhost:8000").rstrip("/")
ENV_LABEL = os.environ.get("ENV_LABEL", "local")
REPORT_PATH = os.environ.get("REPORT_PATH", "/tmp/demo-questions-report.md")
TURNSTILE_BYPASS = os.environ.get("TURNSTILE_BYPASS", "")
COMPANY_LABEL = os.environ.get("COMPANY_LABEL") or f"SmokeCo-{int(time.time())}"
# Attempts per question. LLMs are non-deterministic — the same orchestrator
# may pick the right table on attempt 2 even when it whiffed on attempt 1.
# Counting "success = any attempt passed" absorbs that jitter without
# changing AI logic. Tunable via env for cost / strictness trade-offs.
ATTEMPTS_PER_QUESTION = int(os.environ.get("ATTEMPTS_PER_QUESTION", "3"))


@dataclasses.dataclass
class Attempt:
    """One round-trip to /api/v1/ai/query for a question."""

    n: int
    latency_ms: int
    success: bool
    status: Optional[str] = None
    answer_excerpt: str = ""
    sql_excerpt: str = ""
    chosen_datasets: list[str] = dataclasses.field(default_factory=list)
    failure_reason: Optional[str] = None


@dataclasses.dataclass
class Result:
    n: int
    category: str
    schema: str
    question: str
    # success := any attempt passed. attempts holds every round-trip
    # so the markdown report can show why retries were needed.
    success: bool
    attempts: list[Attempt] = dataclasses.field(default_factory=list)

    @property
    def latency_ms(self) -> int:
        # Sum of all attempt latencies — useful for the report's p50/p95.
        return sum(a.latency_ms for a in self.attempts)

    @property
    def winning_attempt(self) -> Optional[Attempt]:
        for a in self.attempts:
            if a.success:
                return a
        return None

    @property
    def last_attempt(self) -> Optional[Attempt]:
        return self.attempts[-1] if self.attempts else None


def excerpt(s: str, n: int = 240) -> str:
    s = (s or "").strip().replace("\n", " ")
    return (s[:n] + "…") if len(s) > n else s


def detect_refusal(answer: str) -> Optional[str]:
    """Return the matched refusal phrase if the answer is a refusal."""
    if not answer:
        return None
    for phrase in REFUSAL_PHRASES:
        if phrase.lower() in answer.lower():
            return phrase
    return None


async def provision_signup(client: httpx.AsyncClient) -> tuple[str, str]:
    """POST /demo/signup → return (access_token, space_id)."""
    # Unique email per run so we don't hit the returning-visitor path.
    suffix = uuid.uuid4().hex[:10]
    payload = {
        "name": "Smoke Bot",
        "email": f"smoke-{suffix}@{COMPANY_LABEL.lower().replace(' ', '-')}.com",
        "company": COMPANY_LABEL,
        "role": "QA",
        "turnstile_token": TURNSTILE_BYPASS or "smoke-stub",
    }
    r = await client.post(f"{BE_BASE}/api/v1/demo/signup", json=payload, timeout=120.0)
    if r.status_code != 201:
        raise RuntimeError(f"signup failed: HTTP {r.status_code} body={r.text[:300]}")
    body = r.json()
    return body["access_token"], body["space_id"]


async def _attempt(
    client: httpx.AsyncClient,
    token: str,
    space_id: str,
    attempt_n: int,
    spec: dict[str, str],
) -> Attempt:
    """Single round-trip for a question. Same shape as before, just one
    attempt — the retry loop lives in ``ask``.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"question": spec["q"], "space_id": space_id, "is_personal": False}
    t0 = time.monotonic()
    try:
        r = await client.post(
            f"{BE_BASE}/api/v1/ai/query", json=payload, headers=headers, timeout=180.0
        )
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            return Attempt(
                n=attempt_n,
                latency_ms=ms,
                success=False,
                failure_reason=f"HTTP {r.status_code}: {r.text[:200]}",
            )
        body = r.json()
        answer = body.get("answer") or ""
        status = body.get("status")
        sql = body.get("sql") or ""
        chosen = body.get("chosen_datasets") or []
        refusal = detect_refusal(answer)
        if refusal:
            return Attempt(
                n=attempt_n,
                latency_ms=ms,
                success=False,
                status=status,
                answer_excerpt=excerpt(answer),
                sql_excerpt=excerpt(sql),
                chosen_datasets=chosen,
                failure_reason=f"refusal phrase matched: {refusal!r}",
            )
        if not chosen and not sql:
            return Attempt(
                n=attempt_n,
                latency_ms=ms,
                success=False,
                status=status,
                answer_excerpt=excerpt(answer),
                failure_reason="empty chosen_datasets AND empty sql",
            )
        return Attempt(
            n=attempt_n,
            latency_ms=ms,
            success=True,
            status=status,
            answer_excerpt=excerpt(answer),
            sql_excerpt=excerpt(sql),
            chosen_datasets=chosen,
        )
    except Exception as exc:  # noqa: BLE001
        ms = int((time.monotonic() - t0) * 1000)
        return Attempt(
            n=attempt_n,
            latency_ms=ms,
            success=False,
            failure_reason=f"{type(exc).__name__}: {exc}",
        )


async def ask(
    client: httpx.AsyncClient,
    token: str,
    space_id: str,
    n: int,
    spec: dict[str, str],
) -> Result:
    """Up to ``ATTEMPTS_PER_QUESTION`` attempts. Success = any attempt
    passed; the report shows every attempt so a flaky question is
    visible (3 attempts, 1 success → still "PASS" but with a note).
    """
    attempts: list[Attempt] = []
    for i in range(1, ATTEMPTS_PER_QUESTION + 1):
        a = await _attempt(client, token, space_id, i, spec)
        attempts.append(a)
        if a.success:
            break
    return Result(
        n=n,
        category=spec["category"],
        schema=spec["schema"],
        question=spec["q"],
        success=any(a.success for a in attempts),
        attempts=attempts,
    )


def render_report(results: list[Result]) -> str:
    out: list[str] = []
    out.append(f"# Demo-questions smoke — env={ENV_LABEL}")
    out.append("")
    out.append(f"BE: `{BE_BASE}`")
    out.append("")
    total = len(results)
    ok = sum(1 for r in results if r.success)
    fail = total - ok
    lat = [r.latency_ms for r in results]
    out.append("## Summary")
    out.append("")
    out.append(f"- Total: **{total}**")
    out.append(f"- Pass: **{ok}** ({ok / total * 100:.0f}%)")
    out.append(f"- Fail: **{fail}**")
    if lat:
        out.append(f"- Latency p50: **{int(statistics.median(lat))} ms**")
        sorted_lat = sorted(lat)
        p95 = sorted_lat[max(0, int(len(sorted_lat) * 0.95) - 1)]
        out.append(f"- Latency p95: **{p95} ms**")
        out.append(f"- Latency max: **{max(lat)} ms**")
    out.append("")
    # By category
    out.append("## By category")
    out.append("")
    out.append("| Category | Total | Pass | Fail |")
    out.append("|---|---:|---:|---:|")
    for cat in ("revenue", "customer-health", "operations"):
        cat_r = [r for r in results if r.category == cat]
        if not cat_r:
            continue
        cat_ok = sum(1 for r in cat_r if r.success)
        out.append(f"| {cat} | {len(cat_r)} | {cat_ok} | {len(cat_r) - cat_ok} |")
    out.append("")
    # Retry summary — surface flaky questions (passed but needed > 1
    # attempt). Helps the team spot questions that pass over-time but
    # are one bad LLM roll away from a failure.
    flaky = [r for r in results if r.success and len(r.attempts) > 1]
    if flaky:
        out.append("## Flaky (passed on retry)")
        out.append("")
        out.append("| # | Question | Attempts |")
        out.append("|---:|---|---:|")
        for r in flaky:
            out.append(f"| {r.n} | {r.question} | {len(r.attempts)} |")
        out.append("")

    # Per-question detail
    out.append("## Detail")
    out.append("")
    for r in results:
        icon = "PASS" if r.success else "FAIL"
        attempts_used = len(r.attempts)
        suffix = f" ({attempts_used}× attempts)" if attempts_used > 1 else ""
        out.append(
            f"### #{r.n:02d} [{r.category}/{r.schema}] {icon}{suffix} — {r.latency_ms} ms total"
        )
        out.append("")
        out.append(f"**Q:** {r.question}")
        out.append("")
        if r.success:
            win = r.winning_attempt
            assert win is not None
            out.append(f"**A** (attempt {win.n}, {win.latency_ms} ms): {win.answer_excerpt}")
            if win.sql_excerpt:
                out.append("")
                out.append("```sql")
                out.append(win.sql_excerpt)
                out.append("```")
            if win.chosen_datasets:
                out.append(f"_datasets: {', '.join(win.chosen_datasets)}_")
            # Also list failed attempts that preceded the win so
            # patterns are debuggable.
            losers = [a for a in r.attempts if not a.success]
            if losers:
                out.append("")
                out.append("Earlier attempts that failed:")
                for a in losers:
                    out.append(f"- attempt {a.n}: `{a.failure_reason}`")
        else:
            out.append("**All attempts failed:**")
            for a in r.attempts:
                out.append(f"- attempt {a.n} ({a.latency_ms} ms): `{a.failure_reason}`")
                if a.answer_excerpt:
                    out.append(f"  _answer:_ {a.answer_excerpt}")
        out.append("")
    return "\n".join(out) + "\n"


async def main() -> int:
    print("=" * 60)
    print(f"Demo-questions smoke — env={ENV_LABEL}, BE={BE_BASE}")
    print(f"  questions: {len(DEMO_QUESTIONS)}")
    print(f"  company: {COMPANY_LABEL}")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        try:
            token, space_id = await provision_signup(client)
        except Exception as exc:  # noqa: BLE001
            print(f"FATAL: signup failed — {exc}")
            return 2
        print(f"  space_id: {space_id}")
        print()

        results: list[Result] = []
        for n, spec in enumerate(DEMO_QUESTIONS, start=1):
            r = await ask(client, token, space_id, n, spec)
            icon = "OK  " if r.success else "FAIL"
            attempts_used = len(r.attempts)
            suffix = f" (retried {attempts_used - 1}×)" if attempts_used > 1 else ""
            print(
                f"  {icon} #{n:02d} [{r.category[:6]:<6}] {r.latency_ms:>5} ms — "
                f"{r.question[:60]}{suffix}"
            )
            if not r.success and r.last_attempt:
                print(f"        ↳ {r.last_attempt.failure_reason}")
            results.append(r)

    report = render_report(results)
    Path(REPORT_PATH).write_text(report, encoding="utf-8")
    print()
    print(f"Report: {REPORT_PATH}")
    failed = [r for r in results if not r.success]
    if failed:
        print(f"FAIL — {len(failed)}/{len(results)} questions failed.")
        for r in failed:
            last = r.last_attempt
            reason = last.failure_reason if last else "(no attempts)"
            print(f"  #{r.n:02d} {r.question}\n      ↳ {reason}")
        return 1
    flaky = [r for r in results if r.success and len(r.attempts) > 1]
    if flaky:
        print(
            f"PASS with flake — all {len(results)} answered but "
            f"{len(flaky)} needed retries (see report)."
        )
    else:
        print(f"PASS — all {len(results)} questions answered on first try.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
