"""Knowledge — CRUD baseline for Metric + GlossaryTerm.

Phase 2. Basic create / read / update / delete + listing.
Wraps the ACL contract; CRUD without ACL would be a regression
hazard, so these are interleaved with visibility tests in CI.
"""

from __future__ import annotations

import pytest

PHASE = "Phase 2 — CRUD baseline"


@pytest.mark.skip(reason=f"{PHASE} (CRUD-01) — create metric")
@pytest.mark.asyncio
async def test_crud_01_create_metric(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-02) — read metric by id")
@pytest.mark.asyncio
async def test_crud_02_get_metric(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-03) — list metrics in scope")
@pytest.mark.asyncio
async def test_crud_03_list_metrics_in_scope(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-04) — update metric")
@pytest.mark.asyncio
async def test_crud_04_update_metric(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-05) — soft-delete")
@pytest.mark.asyncio
async def test_crud_05_soft_delete_sets_deleted_at(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-06) — slug uniqueness within scope")
@pytest.mark.asyncio
async def test_crud_06_slug_unique_per_scope(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-07) — tags array")
@pytest.mark.asyncio
async def test_crud_07_tags_persisted(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-08) — target + threshold set")
@pytest.mark.asyncio
async def test_crud_08_target_and_threshold_persisted(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-09) — glossary term create")
@pytest.mark.asyncio
async def test_crud_09_create_glossary_term(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-10) — glossary term aliases")
@pytest.mark.asyncio
async def test_crud_10_glossary_aliases_persisted(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-11) — link glossary to metric and source")
@pytest.mark.asyncio
async def test_crud_11_glossary_relates_to_metric_and_source(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CRUD-12) — formula description and text both stored")
@pytest.mark.asyncio
async def test_crud_12_metric_stores_both_formula_text_and_description(db_session):
    raise NotImplementedError
