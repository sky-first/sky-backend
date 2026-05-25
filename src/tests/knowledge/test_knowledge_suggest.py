"""Knowledge — AI suggestion engine (Phase 7).

SUG-01..06. Passive discovery + active assist.
"""

from __future__ import annotations

import pytest

from src.services.knowledge_suggest_service import Suggestion, suggest_metrics
from src.services.metric_formula_generator import TableSchema

PHASE = "Phase 7 — AI suggest"


def _subs_schema() -> TableSchema:
    return TableSchema(
        name="stripe_subscriptions",
        columns=["id", "customer_id", "amount", "status", "created_at"],
        column_types={"amount": "numeric", "customer_id": "uuid"},
    )


def _users_schema() -> TableSchema:
    return TableSchema(
        name="users",
        columns=["id", "email", "last_seen", "created_at"],
        column_types={"email": "text", "last_seen": "timestamp"},
    )


def _orders_schema() -> TableSchema:
    return TableSchema(
        name="orders",
        columns=["id", "customer_id", "order_total", "created_at"],
        column_types={"order_total": "numeric"},
    )


@pytest.mark.asyncio
async def test_sug_01_no_sources_returns_empty(db_session):
    assert suggest_metrics([]) == []


@pytest.mark.asyncio
async def test_sug_02_source_implies_canonical_metric(db_session):
    """An ``amount`` column triggers the canonical MRR suggestion."""
    out = suggest_metrics([_subs_schema()])
    slugs = {s.slug for s in out}
    assert "mrr" in slugs


@pytest.mark.asyncio
async def test_sug_03_suggestion_carries_confidence_score(db_session):
    out = suggest_metrics([_subs_schema()])
    assert all(0.5 <= s.confidence <= 0.95 for s in out)


@pytest.mark.asyncio
async def test_sug_04_does_not_leak_across_visible_scopes(db_session):
    """Pin the contract: existing slugs are filtered. (Cross-scope
    visibility is enforced upstream when the caller filters
    ``existing_metric_slugs`` to those the user can see.)"""
    out = suggest_metrics(
        [_subs_schema()], existing_metric_slugs=["mrr"]
    )
    assert all(s.slug != "mrr" for s in out)


@pytest.mark.asyncio
async def test_sug_05_dismissed_suggestions_excluded(db_session):
    """The dismissal pipeline lives in the FE store + a future
    dismissed_suggestions table. The pure suggest engine here just
    accepts the same ``existing_metric_slugs`` filter — pin the
    contract that filtered slugs are never re-served.
    """
    out_first = suggest_metrics([_subs_schema()])
    assert any(s.slug == "mrr" for s in out_first)
    out_after_dismiss = suggest_metrics(
        [_subs_schema()], existing_metric_slugs=["mrr", "customer-count"]
    )
    slugs = {s.slug for s in out_after_dismiss}
    assert "mrr" not in slugs
    assert "customer-count" not in slugs


@pytest.mark.skip(
    reason=f"{PHASE} (SUG-06) — relationship-fanout suggestions land with the AI rewire phase"
)
@pytest.mark.asyncio
async def test_sug_06_email_fanout_suggested_as_single_relationship(db_session):
    """The user's master-users example: 4 sources sharing an email
    column → one suggestion proposing a many_to_many relationship.
    Phase 7 ships metric suggestions; the relationship fan-out path
    lands when the AI service starts emitting suggestions in the
    chat sidebar (Phase 9).
    """
    raise NotImplementedError
