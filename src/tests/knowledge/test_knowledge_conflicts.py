"""Knowledge — conflict detection at promotion time.

Phase 4. CONF-01..09. The Single-Source-of-Truth gate.
"""

from __future__ import annotations

import pytest

PHASE = "Phase 4 — Conflict detection"


@pytest.mark.skip(reason=f"{PHASE} (CONF-01) — identical name in target")
@pytest.mark.asyncio
async def test_conf_01_identical_name_flagged(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-02) — alias overlap")
@pytest.mark.asyncio
async def test_conf_02_alias_overlap_flagged(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-03) — fuzzy similarity 75 percent")
@pytest.mark.asyncio
async def test_conf_03_similar_names_flagged_at_threshold(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-04) — formula diff surfaced")
@pytest.mark.asyncio
async def test_conf_04_different_formulas_same_name(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-05) — keep canonical decision")
@pytest.mark.asyncio
async def test_conf_05_keep_canonical_demotes_proposed(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-06) — replace decision")
@pytest.mark.asyncio
async def test_conf_06_replace_decision_archives_canonical(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-07) — merge as alias")
@pytest.mark.asyncio
async def test_conf_07_merge_decision_keeps_proposed_as_alias(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-08) — below threshold, no flag")
@pytest.mark.asyncio
async def test_conf_08_below_threshold_no_flag(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (CONF-09) — resolved conflict status persisted")
@pytest.mark.asyncio
async def test_conf_09_resolution_persists_status(db_session):
    raise NotImplementedError
