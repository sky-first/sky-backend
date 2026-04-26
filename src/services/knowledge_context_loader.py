"""Knowledge context loader — feeds Metrics + Glossary into AI prompts.

The AI service used to answer questions without ever consulting the
Knowledge layer (Pillars / OKRs / Glossary in the old model;
Metrics + GlossaryTerm now). This loader returns the user's visible
Knowledge in a shape the system prompt can splice in directly:

    {
        "metrics":  [{name, definition, formula, scope, certified}, ...],
        "glossary": [{term, definition, aliases}, ...],
        "preferred_metrics": [...],   # Org-certified rows surface first
    }

The retrieval rule lifted from KNOWLEDGE_REFACTOR.md §7:

    When the question mentions a metric / term name that exists at
    multiple scopes, prefer the Org-certified definition over the
    user's Personal one. The transparency panel records which one
    was used so reviewers can audit the choice.

This helper is pure and DB-bound — no LLM call. The AI engine
consumes the dict via its own prompt template. Until the engine is
fully wired, callers can attach this output to ``configure_data``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.crew import CrewMember
from src.models.enterprise_relationship import EnterpriseRelationship
from src.models.glossary import GlossaryTerm
from src.models.metric import Metric
from src.models.space import SpaceMember
from src.models.user import User

logger = logging.getLogger(__name__)


async def _user_crew_ids(db: AsyncSession, user_id: UUID) -> List[UUID]:
    rows = await db.execute(select(CrewMember.crew_id).where(CrewMember.user_id == user_id))
    return [r[0] for r in rows.all()]


async def _user_space_ids(db: AsyncSession, user_id: UUID) -> List[UUID]:
    rows = await db.execute(select(SpaceMember.space_id).where(SpaceMember.user_id == user_id))
    return [r[0] for r in rows.all()]


def _serialize_metric(m: Metric) -> Dict:
    return {
        "id": str(m.id),
        "name": m.name,
        "slug": m.slug,
        "description": m.description,
        "scope": m.scope,
        "scope_id": str(m.scope_id) if m.scope_id else None,
        "status": m.status,
        "formula_text": m.formula_text,
        "formula_description": m.formula_description,
        "tags": list(m.tags or []),
        "certified": m.certified_by_user_id is not None,
        "unit": m.unit,
    }


def _serialize_relationship(r: EnterpriseRelationship) -> Dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "relationship_type": r.relationship_type,
        "sources": list(r.sources or []),
        "target_id": r.target_id,
        "target_type": r.target_type,
        "targets": list(getattr(r, "targets", None) or []),
        "ai_inferred": bool(getattr(r, "ai_inferred", False)),
        "confidence": (
            float(getattr(r, "confidence", 0) or 0)
            if getattr(r, "confidence", None) is not None
            else None
        ),
        "scope": getattr(r, "scope", None),
    }


def _serialize_term(g: GlossaryTerm) -> Dict:
    return {
        "id": str(g.id),
        "term": g.term,
        "slug": getattr(g, "slug", None),
        "definition": g.definition,
        "aliases": list(getattr(g, "aliases", []) or []),
        "scope": getattr(g, "scope", None),
        "certified": getattr(g, "certified_by_user_id", None) is not None,
    }


async def load_knowledge_context_for_user(
    db: AsyncSession, user: User, *, limit: int = 200
) -> Dict[str, List[Dict]]:
    """Return Metrics + Glossary the user can read.

    Org-certified metrics are surfaced separately so the prompt
    template can prefer them when the question matches multiple
    candidates by name (KNOWLEDGE_REFACTOR.md §7 — "AI prefers
    Org-certified over Personal").
    """
    crew_ids = await _user_crew_ids(db, user.id)
    space_ids = await _user_space_ids(db, user.id)

    metric_clauses = [
        Metric.scope == "org",
        (Metric.scope == "personal") & (Metric.scope_id == user.id),
    ]
    if crew_ids:
        metric_clauses.append((Metric.scope == "crew") & (Metric.scope_id.in_(crew_ids)))
    if space_ids:
        metric_clauses.append((Metric.scope == "space") & (Metric.scope_id.in_(space_ids)))

    metrics_stmt = (
        select(Metric)
        .where(Metric.deleted_at.is_(None))
        .where(Metric.status != "deprecated")
        .where(or_(*metric_clauses))
        .order_by(Metric.created_at.desc())
        .limit(limit)
    )
    metric_rows = (await db.execute(metrics_stmt)).scalars().all()
    metrics = [_serialize_metric(m) for m in metric_rows]
    preferred = [m for m in metrics if m["scope"] == "org" and m["certified"]]

    # Glossary — Phase 5 added scope columns but legacy callers still
    # use space_id/crew_id. Cover both: any term where (a) scope columns
    # match or (b) legacy space/crew columns match the user's set, or
    # (c) no scoping at all (org-wide vocabulary).
    glossary_stmt = select(GlossaryTerm).where(GlossaryTerm.deleted_at.is_(None))
    glossary_rows = (await db.execute(glossary_stmt)).scalars().all()
    visible_terms: List[GlossaryTerm] = []
    for g in glossary_rows:
        scope = getattr(g, "scope", None)
        scope_id = getattr(g, "scope_id", None)
        if scope == "org" or (scope is None and g.space_id is None and g.crew_id is None):
            visible_terms.append(g)
            continue
        if scope == "personal" and scope_id == user.id:
            visible_terms.append(g)
            continue
        if scope == "crew" and scope_id in crew_ids:
            visible_terms.append(g)
            continue
        if scope == "space" and scope_id in space_ids:
            visible_terms.append(g)
            continue
        if g.space_id and g.space_id in space_ids:
            visible_terms.append(g)
            continue
        if g.crew_id and g.crew_id in crew_ids:
            visible_terms.append(g)
            continue

    glossary = [_serialize_term(g) for g in visible_terms[:limit]]

    # Relationships — same 4-scope ACL as Metrics. AI-inferred rows
    # come last (lower-confidence than human-curated links).
    rel_clauses = [
        EnterpriseRelationship.scope == "org",
        EnterpriseRelationship.scope.is_(None),
        (EnterpriseRelationship.scope == "personal")
        & (EnterpriseRelationship.scope_id == user.id),
    ]
    if crew_ids:
        rel_clauses.append(
            (EnterpriseRelationship.scope == "crew")
            & (EnterpriseRelationship.scope_id.in_(crew_ids))
        )
    if space_ids:
        rel_clauses.append(
            (EnterpriseRelationship.scope == "space")
            & (EnterpriseRelationship.scope_id.in_(space_ids))
        )
    rel_stmt = (
        select(EnterpriseRelationship)
        .where(or_(*rel_clauses))
        .order_by(
            EnterpriseRelationship.ai_inferred.asc().nulls_first(),
            EnterpriseRelationship.created_at.desc(),
        )
        .limit(limit)
    )
    try:
        rel_rows = (await db.execute(rel_stmt)).scalars().all()
        relationships = [_serialize_relationship(r) for r in rel_rows]
    except Exception as exc:  # noqa: BLE001 — relationships are best-effort
        logger.debug("relationships load skipped: %s", exc)
        relationships = []

    return {
        "metrics": metrics,
        "glossary": glossary,
        "preferred_metrics": preferred,
        "relationships": relationships,
    }


def render_knowledge_for_prompt(ctx: Dict[str, List[Dict]]) -> str:
    """Render the loader output into a markdown block the system
    prompt can splice in directly.

    The format is intentionally compact — every line is a triplet of
    (name, scope/certification, formula description). Long SQL is
    truncated so the prompt budget doesn't blow up on hundreds of
    metrics. The AI engine layers this above its own retrieval —
    Knowledge here is the curated, governed surface; raw rows still
    come from the embedding ACL.
    """
    out: List[str] = []
    metrics = ctx.get("preferred_metrics") or ctx.get("metrics") or []
    if metrics:
        out.append("# Trusted metrics (prefer these over ad-hoc derivations)")
        for m in metrics[:50]:
            tag = "[ORG-CERTIFIED]" if m.get("certified") else f"[{(m.get('scope') or '').upper()}]"
            line = f"- {m['name']} {tag}"
            desc = m.get("formula_description") or m.get("description")
            if desc:
                line += f" — {desc}"
            unit = m.get("unit")
            if unit:
                line += f" (unit: {unit})"
            out.append(line)

    terms = ctx.get("glossary") or []
    if terms:
        out.append("\n# Glossary")
        for g in terms[:50]:
            tag = "[ORG-CERTIFIED]" if g.get("certified") else ""
            out.append(f"- **{g['term']}** {tag} — {g.get('definition', '')}".rstrip())

    rels = ctx.get("relationships") or []
    if rels:
        out.append(
            "\n# Enterprise relationships (use these to join across data sources)"
        )
        for r in rels[:50]:
            srcs = r.get("sources") or []
            src_names = ", ".join(
                str(s.get("name") or s.get("id", "?")) for s in srcs[:3]
            ) or "?"
            tgts = r.get("targets") or []
            if tgts:
                tgt_names = ", ".join(
                    str(t.get("id", "?")) for t in tgts[:3]
                )
            else:
                tgt_names = r.get("target_id", "?")
            tag_bits = [r.get("relationship_type", "")]
            if r.get("ai_inferred"):
                conf = r.get("confidence")
                conf_str = (
                    f" {int(conf * 100)}%"
                    if isinstance(conf, (int, float)) and conf <= 1
                    else ""
                )
                tag_bits.append(f"AI-inferred{conf_str}")
            tag = " · ".join(t for t in tag_bits if t)
            out.append(
                f"- **{r['name']}**: {src_names} → {tgt_names}"
                + (f" [{tag}]" if tag else "")
            )

    return "\n".join(out)
