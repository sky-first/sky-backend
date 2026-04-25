"""Knowledge — Relationships N↔N.

Phase 5. REL-01..06. Multi-source fan-out + multi-key joins.
"""

from __future__ import annotations

import pytest

PHASE = "Phase 5 — Relationships N↔N"


@pytest.mark.skip(reason=f"{PHASE} (REL-01) — 1:1 baseline still works")
@pytest.mark.asyncio
async def test_rel_01_one_to_one_persists(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (REL-02) — one Source fans out to N targets in a single row")
@pytest.mark.asyncio
async def test_rel_02_one_to_many_single_row(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (REL-03) — multi-key join with weights")
@pytest.mark.asyncio
async def test_rel_03_many_to_many_multi_key_join(db_session):
    """The user's master-table-of-users example: links by email
    primary, name secondary, IBAN tertiary. Each pair has a
    weight that the AI uses to rank match confidence."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (REL-04) — AI-inferred provenance flag")
@pytest.mark.asyncio
async def test_rel_04_ai_inferred_relationship_carries_confidence(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (REL-05) — ACL applies same as metric")
@pytest.mark.asyncio
async def test_rel_05_cross_sibling_crew_isolated(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (REL-06) — Source ↔ Metric and Source ↔ Glossary")
@pytest.mark.asyncio
async def test_rel_06_supports_metric_and_glossary_resource_types(db_session):
    raise NotImplementedError
