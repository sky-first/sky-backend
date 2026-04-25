"""Knowledge — Describe-mode formula generation (AI).

Phase 6. GEN-01..07. Plain-English → SQL with safety rails.
"""

from __future__ import annotations

import pytest

PHASE = "Phase 6 — AI formula generation"


@pytest.mark.skip(reason=f"{PHASE} (GEN-01) — basic describe → SQL with aggregation")
@pytest.mark.asyncio
async def test_gen_01_basic_describe_to_sql(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (GEN-02) — uses real schema metadata, not hallucinated")
@pytest.mark.asyncio
async def test_gen_02_uses_actual_source_table_columns(db_session):
    """The AI prompt receives the user's connected sources + schemas
    + glossary as context. Generated SQL must reference real tables
    only (no hallucinated tables/columns)."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (GEN-03) — destructive ops rejected")
@pytest.mark.asyncio
async def test_gen_03_rejects_destructive_prompts(db_session):
    """Prompt: "delete all users where status = 'inactive'" must
    return an error, never SQL. Belt-and-suspenders with the
    Wave 8 AST guard."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (GEN-04) — output passes Wave 8 AST guard")
@pytest.mark.asyncio
async def test_gen_04_output_is_readonly_validated(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (GEN-05) — re-generate from edited prompt")
@pytest.mark.asyncio
async def test_gen_05_iterative_refinement(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (GEN-06) — both prompt + SQL stored")
@pytest.mark.asyncio
async def test_gen_06_save_persists_description_and_text(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (GEN-07) — sandbox uses readonly DB role")
@pytest.mark.asyncio
async def test_gen_07_sandbox_test_runs_against_readonly_role(db_session):
    raise NotImplementedError
