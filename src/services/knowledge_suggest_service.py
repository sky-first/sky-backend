"""Knowledge suggest engine — Phase 7.

Surfaces canonical metric / glossary suggestions based on the user's
visible Sources + existing Knowledge graph. Keeps the suggestions
**passive** (drawn from schema patterns + name overlap) rather than
LLM-driven so the unit-tested path is deterministic; the LLM-backed
path lands when production demand justifies it.

Each suggestion carries a confidence score (0..1) that the UI uses to
rank the list. Confidence is heuristic — column-name + table-name
overlap bumps it; missing context drops it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from src.services.metric_formula_generator import TableSchema


# Canonical patterns. Each one says: \"if any visible source has a
# column named X (case-insensitive), suggest a metric Y\". Tuned for
# the analytics surface every B2B SaaS demos in the first hour.
_PATTERNS = (
    {
        "name": "Monthly Recurring Revenue",
        "slug": "mrr",
        "match_columns": ("amount", "mrr", "subscription_amount"),
        "agg": "SUM",
        "kind": "metric",
        "rationale": "you have a subscription-amount column — MRR is the canonical roll-up",
    },
    {
        "name": "Customer Count",
        "slug": "customer-count",
        "match_columns": ("customer_id", "user_id", "account_id"),
        "agg": "COUNT_DISTINCT",
        "kind": "metric",
        "rationale": "an id column that looks like customer/user/account",
    },
    {
        "name": "Active Users",
        "slug": "active-users",
        "match_columns": ("last_seen", "last_login", "active_at"),
        "agg": "COUNT_DISTINCT_LAST_30D",
        "kind": "metric",
        "rationale": "an activity timestamp — 30-day rolling unique count is the canonical metric",
    },
    {
        "name": "Churn Rate",
        "slug": "churn-rate",
        "match_columns": ("cancelled_at", "canceled_at", "churned_at"),
        "agg": "RATIO",
        "kind": "metric",
        "rationale": "a churn timestamp — monthly cancellations over base",
    },
    {
        "name": "Average Order Value",
        "slug": "aov",
        "match_columns": ("order_total", "amount", "total"),
        "agg": "AVG",
        "kind": "metric",
        "rationale": "an order-amount column — AOV ties product strategy to revenue",
    },
)


@dataclass
class Suggestion:
    name: str
    slug: str
    kind: str
    rationale: str
    confidence: float
    bound_table: Optional[str] = None
    bound_column: Optional[str] = None


def suggest_metrics(
    schemas: Sequence[TableSchema],
    existing_metric_slugs: Sequence[str] = (),
) -> List[Suggestion]:
    """Return ranked suggestions based on the user's schemas.

    Suggestions whose ``slug`` already exists in
    ``existing_metric_slugs`` are filtered out — we don't want to
    propose a metric the user already created.
    """
    if not schemas:
        return []

    existing = {s.lower() for s in existing_metric_slugs if s}
    out: List[Suggestion] = []

    for pattern in _PATTERNS:
        if pattern["slug"] in existing:
            continue
        match = _find_match(schemas, pattern["match_columns"])
        if match is None:
            continue
        table_name, column_name = match
        confidence = _score(table_name, column_name, pattern)
        out.append(
            Suggestion(
                name=pattern["name"],
                slug=pattern["slug"],
                kind=pattern["kind"],
                rationale=pattern["rationale"],
                confidence=confidence,
                bound_table=table_name,
                bound_column=column_name,
            )
        )

    # Higher confidence first; stable order on ties via slug.
    out.sort(key=lambda s: (-s.confidence, s.slug))
    return out


# ─── helpers ─────────────────────────────────────────────────────


def _find_match(
    schemas: Sequence[TableSchema], target_columns: Sequence[str]
) -> Optional[tuple[str, str]]:
    targets = {c.lower() for c in target_columns}
    for s in schemas:
        for col in s.columns:
            if col.lower() in targets:
                return s.name, col
    return None


def _score(table_name: str, column_name: str, pattern: Dict) -> float:
    """Confidence score in [0.5, 0.95].

    Direct column name match → 0.7. Bonus +0.1 if the table name also
    shares a token with the canonical metric (e.g. ``subscriptions``
    table for MRR). Bonus +0.15 if the column is an exact match
    (vs. fuzzy alias).
    """
    score = 0.7
    if column_name.lower() == pattern["match_columns"][0].lower():
        score += 0.15
    table_tokens = set(table_name.lower().replace("_", " ").split())
    if any(t in pattern["name"].lower() for t in table_tokens):
        score += 0.10
    return min(0.95, max(0.5, score))
