"""Knowledge — Relationships N↔N (Phase 6).

REL-01..06. Multi-source fan-out + multi-key joins + AI provenance.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.models.enterprise_relationship import EnterpriseRelationship

PHASE = "Phase 6 — Relationships N↔N"


def _make_relationship(*, user, **overrides) -> EnterpriseRelationship:
    """Construct a relationship with the legacy columns filled."""
    defaults = dict(
        name=overrides.pop("name", "users → users_master"),
        sources=[{"id": "stripe.customers", "type": "table"}],
        target_id="warehouse.users_master",
        target_type="table",
        relationship_type="maps_to",
        created_by=user.id,
    )
    defaults.update(overrides)
    return EnterpriseRelationship(**defaults)


@pytest.mark.asyncio
async def test_rel_01_one_to_one_persists(db_session, test_user):
    user = test_user["user"]
    rel = _make_relationship(user=user)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    assert rel.id is not None
    assert rel.target_id == "warehouse.users_master"
    # Phase 6 fields default empty.
    assert rel.targets == []
    assert rel.keys == []
    assert rel.ai_inferred is False


@pytest.mark.asyncio
async def test_rel_02_one_to_many_single_row(db_session, test_user):
    """One source row, multiple targets — Phase 6 ``targets`` array."""
    user = test_user["user"]
    rel = _make_relationship(
        user=user,
        sources=[{"id": "hubspot.contacts", "type": "table"}],
        targets=[
            {"id": "warehouse.users_master", "type": "table", "weight": 0.9},
            {"id": "stripe.customers", "type": "table", "weight": 0.6},
            {"id": "intercom.users", "type": "table", "weight": 0.4},
        ],
    )
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)

    assert len(rel.targets) == 3
    assert rel.targets[0]["id"] == "warehouse.users_master"
    assert rel.targets[0]["weight"] == 0.9


@pytest.mark.asyncio
async def test_rel_03_many_to_many_multi_key_join(db_session, test_user):
    """The user's master-table-of-users example: links by email
    primary, name secondary, IBAN tertiary.
    """
    user = test_user["user"]
    rel = _make_relationship(
        user=user,
        sources=[
            {"id": "stripe.customers", "type": "table"},
            {"id": "hubspot.contacts", "type": "table"},
            {"id": "intercom.users", "type": "table"},
        ],
        targets=[{"id": "warehouse.users_master", "type": "table", "weight": 1.0}],
        keys=[
            {"primary": "email", "secondary": "name", "tertiary": "iban"},
        ],
    )
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)

    assert len(rel.sources) == 3
    assert rel.keys[0]["primary"] == "email"
    assert rel.keys[0]["tertiary"] == "iban"


@pytest.mark.asyncio
async def test_rel_04_ai_inferred_relationship_carries_confidence(db_session, test_user):
    user = test_user["user"]
    rel = _make_relationship(
        user=user,
        ai_inferred=True,
        confidence=Decimal("0.84"),
    )
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)

    assert rel.ai_inferred is True
    assert rel.confidence == Decimal("0.84")


@pytest.mark.asyncio
async def test_rel_05_cross_sibling_crew_isolated(db_session, test_user):
    """scope/scope_id columns round-trip — full visibility query
    follow-up lives in the EnterpriseRelationshipService.
    """
    user = test_user["user"]
    crew_a = uuid.uuid4()
    rel = _make_relationship(user=user, scope="crew", scope_id=crew_a)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    assert rel.scope == "crew"
    assert rel.scope_id == crew_a


@pytest.mark.asyncio
async def test_rel_06_supports_metric_and_glossary_resource_types(db_session, test_user):
    """Targets array accepts arbitrary resource types — ``metric`` and
    ``glossary_term`` are first-class so the AI graph can express
    Source ↔ Metric and Source ↔ Glossary edges.
    """
    user = test_user["user"]
    rel = _make_relationship(
        user=user,
        targets=[
            {"id": "<metric-uuid>", "type": "metric", "weight": 1.0},
            {"id": "<glossary-uuid>", "type": "glossary_term", "weight": 1.0},
        ],
    )
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    types = {t["type"] for t in rel.targets}
    assert {"metric", "glossary_term"}.issubset(types)
