"""First-setup Glossary + Metrics derived faithfully from real schema.

Pins the hard requirement (Lucas / GBT): suggestions reflect the actual
discovered dataset — real table + column names as evidence — and never
fabricate. Empty / undiscovered connection → empty output.

Two layers:
  * pure ``derive_suggestions`` — deterministic, no DB.
  * ``ConnectionKnowledgeSuggestService`` — reads seeded
    ``ConnectionMetadata`` and returns the same grounded proposals.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.connection import ConnectionMetadata, DataConnection
from src.repositories.user import UserRepository
from src.services.connection_knowledge_suggest_service import (
    ConnectionKnowledgeSuggestService,
    derive_suggestions,
)

PHASE = "First-setup — schema-grounded glossary + metrics"


# GBT-shaped fixture: people + people_types, the real tables behind
# "quantos candidatos". Mirrors the ConnectionMetadata.tables JSON shape.
def _gbt_tables() -> list[dict]:
    return [
        {
            "name": "people",
            "description": "Master record of every person known to the ATS.",
            "row_count": 41230,
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "full_name", "type": "text"},
                {
                    "name": "person_type_id",
                    "type": "integer",
                    "description": "FK to people_types — candidate, employee, …",
                },
                {"name": "salary_expectation", "type": "numeric"},
                {"name": "created_at", "type": "timestamp"},
            ],
        },
        {
            "name": "people_types",
            # No description on the table — must get a neutral definition.
            "row_count": 7,
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "person_type_name", "type": "text"},
            ],
        },
    ]


# ─── pure derivation ─────────────────────────────────────────────────


def test_empty_tables_returns_empty():
    """No discovered metadata → no suggestions. Never fabricate."""
    out = derive_suggestions([])
    assert out.glossary == []
    assert out.metrics == []


def test_glossary_term_per_real_table_with_provenance():
    out = derive_suggestions(_gbt_tables())
    by_table = {g.source_table for g in out.glossary if g.source_column is None}
    assert "people" in by_table
    assert "people_types" in by_table
    # Humanised labels, raw provenance.
    people_term = next(
        g for g in out.glossary if g.source_table == "people" and g.source_column is None
    )
    assert people_term.term == "People"
    assert people_term.source == "auto"
    assert people_term.reviewed is False


def test_table_description_is_used_verbatim_when_present():
    out = derive_suggestions(_gbt_tables())
    people_term = next(
        g for g in out.glossary if g.source_table == "people" and g.source_column is None
    )
    assert people_term.definition == "Master record of every person known to the ATS."


def test_undescribed_table_gets_neutral_definition_not_invented():
    out = derive_suggestions(_gbt_tables())
    pt = next(
        g for g in out.glossary if g.source_table == "people_types" and g.source_column is None
    )
    # Neutral, fact-only: names the table + row count, defers meaning.
    assert "people_types" in pt.definition
    assert "pending review" in pt.definition.lower()
    assert "7" in pt.definition


def test_documented_column_becomes_glossary_term():
    out = derive_suggestions(_gbt_tables())
    col_terms = [g for g in out.glossary if g.source_column is not None]
    pt = next(g for g in col_terms if g.source_column == "person_type_id")
    assert pt.source_table == "people"
    assert pt.definition == "FK to people_types — candidate, employee, …"


def test_undocumented_columns_do_not_get_invented_terms():
    """full_name / salary_expectation have no description → no term."""
    out = derive_suggestions(_gbt_tables())
    col_names = {g.source_column for g in out.glossary if g.source_column is not None}
    assert "full_name" not in col_names
    assert "salary_expectation" not in col_names  # numeric, but undocumented


def test_count_metric_per_table_with_real_sql():
    out = derive_suggestions(_gbt_tables())
    counts = {m.source_table: m for m in out.metrics if m.aggregation == "COUNT"}
    assert counts["people"].formula_text == "SELECT COUNT(*) FROM people"
    assert counts["people_types"].formula_text == "SELECT COUNT(*) FROM people_types"


def test_sum_avg_only_over_real_numeric_non_id_columns():
    out = derive_suggestions(_gbt_tables())
    sums = {(m.source_table, m.source_column) for m in out.metrics if m.aggregation == "SUM"}
    # salary_expectation is numeric and not an id → SUM + AVG candidates.
    assert ("people", "salary_expectation") in sums
    # person_type_id is numeric but an id → excluded from SUM/AVG.
    assert ("people", "person_type_id") not in sums
    # people_types.id is numeric but an id → excluded.
    assert ("people_types", "id") not in sums

    sal = next(
        m for m in out.metrics if m.aggregation == "SUM" and m.source_column == "salary_expectation"
    )
    assert sal.formula_text == "SELECT SUM(salary_expectation) FROM people"


def test_all_suggestions_flagged_auto_and_unreviewed():
    out = derive_suggestions(_gbt_tables())
    assert all(g.source == "auto" and g.reviewed is False for g in out.glossary)
    assert all(m.source == "auto" and m.reviewed is False for m in out.metrics)


# ─── DB-backed service ───────────────────────────────────────────────


async def _seed_connection_with_metadata(db: AsyncSession, tables: list[dict]) -> DataConnection:
    repo = UserRepository(db)
    user = await repo.create(
        email="ckss@example.com",
        password_hash=get_password_hash("pw"),
        name="ckss",
        role="admin",
    )
    conn = DataConnection(
        name="gbt_source",
        connector_id="postgresql",
        config={},
        created_by=user.id,
    )
    db.add(conn)
    await db.flush()
    md = ConnectionMetadata(connection_id=conn.id, tables=tables)
    db.add(md)
    await db.commit()
    await db.refresh(conn)
    return conn


@pytest.mark.asyncio
async def test_service_derives_from_seeded_metadata(db_session: AsyncSession):
    conn = await _seed_connection_with_metadata(db_session, _gbt_tables())
    out = await ConnectionKnowledgeSuggestService(db_session).suggest_for_connection(conn.id)
    assert any(g.source_table == "people" for g in out.glossary)
    assert any(m.aggregation == "COUNT" and m.source_table == "people_types" for m in out.metrics)


@pytest.mark.asyncio
async def test_service_returns_empty_when_no_metadata(db_session: AsyncSession):
    """Connection discovered nothing yet → no fabricated suggestions."""
    conn = await _seed_connection_with_metadata(db_session, [])
    out = await ConnectionKnowledgeSuggestService(db_session).suggest_for_connection(conn.id)
    assert out.glossary == []
    assert out.metrics == []
