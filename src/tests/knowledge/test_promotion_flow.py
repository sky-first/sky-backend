"""Knowledge — promotion + dependency resolver.

Phase 4. PROM-01..10. Personal → Crew → Space → Org.
"""

from __future__ import annotations

import pytest

PHASE = "Phase 4 — Promotion flow"


@pytest.mark.skip(reason=f"{PHASE} (PROM-01) — bare promote, no deps")
@pytest.mark.asyncio
async def test_prom_01_personal_to_crew_no_dependencies(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-02) — Source dependency auto-included")
@pytest.mark.asyncio
async def test_prom_02_source_dependency_resolved(db_session):
    """Promoting a Metric whose ``source_id`` points to a Source not
    yet shared at the target scope must include the Source as a
    dependency item in the request, not silently fail later."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-03) — Glossary dependency auto-included")
@pytest.mark.asyncio
async def test_prom_03_glossary_dependency_resolved(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-04) — Relationship crawls both sides")
@pytest.mark.asyncio
async def test_prom_04_relationship_dependency_crawls_both_sides(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-05) — cyclic dependencies handled")
@pytest.mark.asyncio
async def test_prom_05_cyclic_dependencies_no_infinite_loop(db_session):
    """Resolver depth-limited; cycles are detected and reported as
    a dependency item once. No infinite recursion."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-06) — atomic approval transaction")
@pytest.mark.asyncio
async def test_prom_06_approval_is_all_or_nothing(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-07) — reject creates nothing")
@pytest.mark.asyncio
async def test_prom_07_reject_creates_no_target_rows(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-08) — conflict at target")
@pytest.mark.asyncio
async def test_prom_08_target_conflict_marks_status_conflict_pending(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-09) — requester must own the dep")
@pytest.mark.asyncio
async def test_prom_09_promote_dep_requester_does_not_own_denied(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (PROM-10) — full chain")
@pytest.mark.asyncio
async def test_prom_10_chain_personal_to_crew_to_space_to_org(db_session):
    raise NotImplementedError
