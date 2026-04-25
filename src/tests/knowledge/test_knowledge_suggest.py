"""Knowledge — AI suggestion engine.

Phase 6. SUG-01..06. Passive discovery + active assist.
"""

from __future__ import annotations

import pytest

PHASE = "Phase 6 — AI suggest"


@pytest.mark.skip(reason=f"{PHASE} (SUG-01) — empty workspace, empty suggestions")
@pytest.mark.asyncio
async def test_sug_01_no_sources_returns_empty(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (SUG-02) — common-pattern metric implied by source")
@pytest.mark.asyncio
async def test_sug_02_source_implies_canonical_metric(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (SUG-03) — suggestion includes confidence")
@pytest.mark.asyncio
async def test_sug_03_suggestion_carries_confidence_score(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (SUG-04) — respects ACL")
@pytest.mark.asyncio
async def test_sug_04_does_not_leak_across_visible_scopes(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (SUG-05) — dismissed not re-served")
@pytest.mark.asyncio
async def test_sug_05_dismissed_suggestions_excluded(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (SUG-06) — N↔N relationship suggestion")
@pytest.mark.asyncio
async def test_sug_06_email_fanout_suggested_as_single_relationship(db_session):
    """The user's master-users example: 4 sources sharing an email
    column → one suggestion proposing a many_to_many relationship
    with 4 targets, not 4 separate one_to_one suggestions."""
    raise NotImplementedError
