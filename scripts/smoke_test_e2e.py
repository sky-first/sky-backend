#!/usr/bin/env python3
"""End-to-end smoke test against an AWS cluster (stg or prd).

Exercises the BE → AI → Bedrock pipeline with 20 questions covering 4
context surfaces: SQL connections, metrics, glossary, and mixed.

Designed to run inside the cluster as a K8s Job, where:
  * the BE container image is reused (has DB + httpx + auth helpers)
  * AI service reachable at AI_SERVICE_URL (cluster DNS)
  * RDS reachable via the same secret-injected DATABASE_URL

Outputs a Markdown report at /tmp/smoke-report.md with per-question
results and aggregate metrics. The Job's stdout also prints a summary
table so `kubectl logs` is enough for a fast read.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if not os.environ.get("DATABASE_URL"):
    print("Set DATABASE_URL.", file=sys.stderr)
    sys.exit(1)

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402


async def _sessao():
    """A sessao sobre a base onde os dados de demonstracao vivem hoje.

    Este script foi escrito antes do modelo multi-cliente e olhava
    sempre para o `DATABASE_URL` — a base da **plataforma**. As ligacoes
    de demonstracao mudaram-se para a base do cliente `sandbox`, e o
    teste passou a encontrar `connections: []`: nada para perguntar, e as
    vinte perguntas a falhar a 0 ms sem sequer sairem daqui.

    Com `TENANT_SLUG`, a base dedicada e descoberta a partir do registo,
    como no `seed_tenant_admin_user.py`. Sem ele, nada muda.
    """
    slug = (os.environ.get("TENANT_SLUG") or "").strip()
    if not slug:
        return AsyncSessionLocal()

    sys.path.insert(0, str(Path(__file__).parent))
    from _ligacao_ao_tenant import url_do_tenant
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = await url_do_tenant(slug)
    print(f"  cliente {slug!r}: base dedicada resolvida a partir do registo")
    motor = create_async_engine(url, pool_pre_ping=True)
    return async_sessionmaker(motor, expire_on_commit=False)()


from src.models.user import User  # noqa: E402
from src.models.space import Space  # noqa: E402
from src.models.connection import DataConnection  # noqa: E402

OWNER_EMAIL = "rbac.owner@example.com"
AI_BASE = os.environ.get("AI_SERVICE_URL", "http://localhost:8001").rstrip("/")
ENV_LABEL = os.environ.get("ENV_LABEL", "unknown")
REPORT_PATH = os.environ.get("REPORT_PATH", "/tmp/smoke-report.md")


# ---------------------------------------------------------------------
# Question catalogue — 20 questions across 4 categories
# ---------------------------------------------------------------------

QUESTIONS: list[dict] = [
    # ── Category A — SQL puro (tests connection retrieval + SQL specialist + Bedrock) ─
    {"cat": "SQL", "conn_hint": "Sales", "q": "What are the top 5 customers by total revenue?"},
    {
        "cat": "SQL",
        "conn_hint": "Marketing",
        "q": "Which marketing channels delivered the most new signups in the last 90 days?",
    },
    {
        "cat": "SQL",
        "conn_hint": "Finance",
        "q": "Show me total active subscription value grouped by plan tier.",
    },
    {
        "cat": "SQL",
        "conn_hint": "Web Analytics",
        "q": "What pages had the highest bounce rate last month?",
    },
    {
        "cat": "SQL",
        "conn_hint": "Product Usage",
        "q": "How many distinct active users did we have yesterday?",
    },
    # ── Category B — Metric retrieval (tests RAG over `metrics`) ─
    {
        "cat": "METRIC",
        "conn_hint": "Finance",
        "q": "How is MRR calculated in this workspace, and what's the current threshold?",
    },
    {"cat": "METRIC", "conn_hint": "Finance", "q": "Show me ARPU and explain the formula we use."},
    {
        "cat": "METRIC",
        "conn_hint": "Marketing",
        "q": "What's our CAC target, and what counts as the warning threshold?",
    },
    {
        "cat": "METRIC",
        "conn_hint": "Product Usage",
        "q": "Explain how we measure DAU/MAU and what the target ratio is.",
    },
    {
        "cat": "METRIC",
        "conn_hint": "Finance",
        "q": "What metric do we use for customer churn, and how is it computed?",
    },
    # ── Category C — Glossary retrieval (tests RAG over `glossary_terms`) ─
    {"cat": "GLOSSARY", "conn_hint": "Sales", "q": "Define cohort in our context."},
    {
        "cat": "GLOSSARY",
        "conn_hint": "Sales",
        "q": "What does GMV stand for, and how is it different from revenue?",
    },
    {"cat": "GLOSSARY", "conn_hint": "Sales", "q": "Explain LTV and how it relates to ARPU."},
    {
        "cat": "GLOSSARY",
        "conn_hint": "Sales",
        "q": "What's a payback period and what's a healthy benchmark for B2B SaaS?",
    },
    {
        "cat": "GLOSSARY",
        "conn_hint": "Sales",
        "q": "Difference between voluntary and involuntary churn — and what fixes each?",
    },
    # ── Category D — Mixed (tests orchestrator coordinating multiple sources) ─
    {
        "cat": "MIXED",
        "conn_hint": "Finance",
        "q": "Calculate this month's MRR from our Finance subscriptions and define cohort while you're at it.",
    },
    {
        "cat": "MIXED",
        "conn_hint": "Marketing",
        "q": "Is our CAC above the warning threshold? Define CAC first, then check the data.",
    },
    {
        "cat": "MIXED",
        "conn_hint": "Product Usage",
        "q": "Show DAU/MAU evolution over the last 30 days and reference the glossary definition of cohort.",
    },
    {
        "cat": "MIXED",
        "conn_hint": "Sales",
        "q": "Which customer cohort by signup month has the highest retention? Use LTV definition from glossary.",
    },
    {
        "cat": "MIXED",
        "conn_hint": "Finance",
        "q": "Is our churn rate above target? Reference the metric definition and the voluntary-vs-involuntary glossary entry.",
    },
]


@dataclass
class QuestionResult:
    n: int
    category: str
    question: str
    connection_id: Optional[str]
    success: bool
    latency_ms: int
    answer_excerpt: str = ""
    sql: Optional[str] = None
    num_rows: int = 0
    error: Optional[str] = None
    detected_language: Optional[str] = None
    response_format: Optional[str] = None


def excerpt(s: str, n: int = 220) -> str:
    s = (s or "").strip().replace("\n", " ")
    return (s[:n] + "...") if len(s) > n else s


async def resolve_owner_and_space(db) -> tuple[User, Space, dict[str, str]]:
    owner = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()
    spaces = (await db.execute(select(Space).where(Space.created_by == owner.id))).scalars().all()
    space = next(
        (s for s in spaces if s.name and s.name.startswith("Demo") and "Sky" in s.name),
        None,
    )
    if not space:
        raise RuntimeError("'Demo' Space not found — run seed_demo_connections.py first")

    conns = (
        (
            await db.execute(
                select(DataConnection).where(
                    DataConnection.created_by == owner.id,
                    DataConnection.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    conn_by_hint: dict[str, str] = {}
    for c in conns:
        n = c.name or ""
        if "Sales" in n:
            conn_by_hint["Sales"] = str(c.id)
        elif "Marketing" in n:
            conn_by_hint["Marketing"] = str(c.id)
        elif "Finance" in n:
            conn_by_hint["Finance"] = str(c.id)
        elif "Web" in n:
            conn_by_hint["Web Analytics"] = str(c.id)
        elif "Product" in n:
            conn_by_hint["Product Usage"] = str(c.id)
    return owner, space, conn_by_hint


async def ask_one(
    client: httpx.AsyncClient,
    n: int,
    spec: dict,
    owner_id: str,
    space_id: str,
    conn_id: str,
) -> QuestionResult:
    payload = {
        "question": spec["q"],
        "user_id": owner_id,
        "space_id": space_id,
        "is_personal": False,
        "thread_id": f"smoke-{n}",
    }
    url = f"{AI_BASE}/connections/{conn_id}/query"
    t0 = time.monotonic()
    try:
        r = await client.post(url, json=payload, timeout=120.0)
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            return QuestionResult(
                n=n,
                category=spec["cat"],
                question=spec["q"],
                connection_id=conn_id,
                success=False,
                latency_ms=ms,
                error=f"HTTP {r.status_code}: {r.text[:200]}",
            )
        body = r.json()
        meta = body.get("meta") or {}
        return QuestionResult(
            n=n,
            category=spec["cat"],
            question=spec["q"],
            connection_id=conn_id,
            success=not meta.get("error"),
            latency_ms=ms,
            answer_excerpt=excerpt(body.get("answer") or ""),
            sql=meta.get("sql"),
            num_rows=meta.get("num_rows") or 0,
            error=meta.get("error"),
            detected_language=meta.get("detected_language"),
        )
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return QuestionResult(
            n=n,
            category=spec["cat"],
            question=spec["q"],
            connection_id=conn_id,
            success=False,
            latency_ms=ms,
            error=f"{type(exc).__name__}: {exc}",
        )


def render_report(results: list[QuestionResult]) -> str:
    lines: list[str] = []
    lines.append(f"# Sky smoke test — {ENV_LABEL}")
    lines.append("")
    lines.append(f"AI service: `{AI_BASE}`")
    lines.append("")

    # Aggregate
    total = len(results)
    ok = sum(1 for r in results if r.success)
    fail = total - ok
    latencies = [r.latency_ms for r in results]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total: **{total}** questions")
    lines.append(f"- Success: **{ok}** ({ok / total * 100:.0f}%)")
    lines.append(f"- Failed: **{fail}**")
    if latencies:
        lines.append(f"- Latency p50: **{int(statistics.median(latencies))} ms**")
        if len(latencies) >= 2:
            sorted_l = sorted(latencies)
            p95 = sorted_l[max(0, int(len(sorted_l) * 0.95) - 1)]
            lines.append(f"- Latency p95: **{p95} ms**")
        lines.append(f"- Latency max: **{max(latencies)} ms**")
    lines.append("")

    # By category
    lines.append("## By category")
    lines.append("")
    lines.append("| Category | Total | OK | Fail | p50 ms | max ms |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for cat in ("SQL", "METRIC", "GLOSSARY", "MIXED"):
        cat_r = [r for r in results if r.category == cat]
        if not cat_r:
            continue
        cat_ok = sum(1 for r in cat_r if r.success)
        cat_lat = [r.latency_ms for r in cat_r]
        lines.append(
            f"| {cat} | {len(cat_r)} | {cat_ok} | {len(cat_r) - cat_ok} | "
            f"{int(statistics.median(cat_lat))} | {max(cat_lat)} |"
        )
    lines.append("")

    lines.append("## Per-question detail")
    lines.append("")
    for r in results:
        status_icon = "OK" if r.success else "FAIL"
        lines.append(f"### #{r.n} [{r.category}] {status_icon}  ({r.latency_ms} ms)")
        lines.append("")
        lines.append(f"**Q:** {r.question}")
        lines.append("")
        if r.success:
            lines.append(f"**A:** {r.answer_excerpt}")
            if r.sql:
                lines.append("")
                lines.append("```sql")
                lines.append(r.sql.strip())
                lines.append("```")
                lines.append(f"_rows: {r.num_rows}_")
        else:
            lines.append(f"**Error:** `{r.error}`")
        lines.append("")
    return "\n".join(lines) + "\n"


async def discover_all(
    client: httpx.AsyncClient, conn_by_hint: dict[str, str], space_id: str
) -> None:
    """Trigger AI-side metadata discovery + embeddings for each connection.

    The AI service holds its own copy of table metadata and embeddings
    (separate from the BE's ConnectionService.sync_connection result).
    Without this the /connections/{id}/query endpoint replies
    "No metadata found for this connection" — exactly what the first
    smoke run hit.
    """
    print("Discover phase — populating AI-side metadata + embeddings...")
    for hint, conn_id in conn_by_hint.items():
        url = (
            f"{AI_BASE}/connections/{conn_id}/discover"
            f"?space_id={space_id}"
            f"&run_in_background=false"
            f"&auto_generate_embeddings=true"
            f"&skip_if_recent_seconds=0"
        )
        t0 = time.monotonic()
        try:
            r = await client.post(url, timeout=180.0)
            ms = int((time.monotonic() - t0) * 1000)
            ok = r.status_code == 200
            tag = "OK  " if ok else "FAIL"
            print(f"  {tag} {hint:<14} {ms:>5} ms  HTTP {r.status_code}")
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            print(f"  FAIL {hint:<14} {ms:>5} ms  {type(exc).__name__}: {exc}")
    print()


async def main() -> None:
    print("=" * 60)
    print(f"Sky smoke test — env={ENV_LABEL}, ai={AI_BASE}")
    print("=" * 60)

    async with await _sessao() as db:
        owner, space, conn_by_hint = await resolve_owner_and_space(db)

    print(f"  owner={owner.id}  space={space.id}")
    print(f"  connections: {list(conn_by_hint.keys())}")
    print()

    results: list[QuestionResult] = []
    async with httpx.AsyncClient() as client:
        await discover_all(client, conn_by_hint, str(space.id))
        for n, spec in enumerate(QUESTIONS, start=1):
            conn_id = conn_by_hint.get(spec["conn_hint"])
            if not conn_id:
                results.append(
                    QuestionResult(
                        n=n,
                        category=spec["cat"],
                        question=spec["q"],
                        connection_id=None,
                        success=False,
                        latency_ms=0,
                        error=f"connection {spec['conn_hint']!r} not found",
                    )
                )
                continue
            print(f"  Q{n:>2} [{spec['cat']:<8}] {spec['q'][:70]}")
            res = await ask_one(client, n, spec, str(owner.id), str(space.id), conn_id)
            tag = "OK  " if res.success else "FAIL"
            print(
                f"        {tag} {res.latency_ms} ms"
                + (f"  err={res.error[:80]}" if res.error else "")
            )
            results.append(res)

    report = render_report(results)
    Path(REPORT_PATH).write_text(report, encoding="utf-8")
    print()
    print("=" * 60)
    print(f"Report written to {REPORT_PATH}")
    print("=" * 60)
    # Final summary line stdout-friendly
    ok = sum(1 for r in results if r.success)
    print(
        f"PASS={ok}/{len(results)}  p50={int(statistics.median([r.latency_ms for r in results]))}ms"
    )

    # ── Um teste que falha tudo nao pode terminar bem. ────────────────
    #
    # Ate 02/09/2026 este script imprimia `PASS=0/20` e saia com 0. Como
    # Job de Kubernetes isso e `Complete 1/1`: o ArgoCD ve saude, o
    # `kubectl get jobs` ve sucesso, e o relatorio com vinte FAIL fica
    # dentro dos logs a espera de que alguem os abra.
    #
    # A unica razao de ser deste teste e dar sinal. Sem codigo de saida
    # nao da nenhum.
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
