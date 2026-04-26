"""Knowledge — Describe-mode formula generation (Phase 7).

GEN-01..07. Plain-English → SQL with read-only safety rails.
"""

from __future__ import annotations

import pytest

from src.services.metric_formula_generator import (
    FormulaGenerationError,
    GenerationResult,
    TableSchema,
    generate_formula,
    set_llm_generator,
)

PHASE = "Phase 7 — AI formula generation"


@pytest.fixture(autouse=True)
def _reset_llm_generator():
    """Each test starts on the deterministic heuristic. If a test
    swaps in a stub LLM, restore after."""
    set_llm_generator(None)
    yield
    set_llm_generator(None)


def _stripe_subs() -> TableSchema:
    return TableSchema(
        name="stripe_subscriptions",
        columns=["id", "customer_id", "amount", "status", "created_at"],
        column_types={
            "id": "uuid",
            "customer_id": "uuid",
            "amount": "numeric",
            "status": "text",
            "created_at": "timestamp",
        },
    )


def _hubspot_contacts() -> TableSchema:
    return TableSchema(
        name="hubspot_contacts",
        columns=["id", "email", "lifetime_value", "created_at"],
        column_types={
            "id": "uuid",
            "email": "text",
            "lifetime_value": "numeric",
            "created_at": "timestamp",
        },
    )


@pytest.mark.asyncio
async def test_gen_01_basic_describe_to_sql(db_session):
    schemas = [_stripe_subs()]
    result = generate_formula("Total amount of stripe subscriptions", schemas)
    assert "SUM" in result.sql.upper()
    assert "stripe_subscriptions" in result.sql
    assert result.language == "sql"


@pytest.mark.asyncio
async def test_gen_02_uses_actual_source_table_columns(db_session):
    """Generator never references tables / columns not in the schema."""
    schemas = [_stripe_subs(), _hubspot_contacts()]
    result = generate_formula("count of stripe subscriptions", schemas)
    referenced_tables = ["stripe_subscriptions", "hubspot_contacts"]
    assert any(t in result.sql for t in referenced_tables)
    assert "FROM users" not in result.sql
    assert "FROM orders" not in result.sql


@pytest.mark.asyncio
async def test_gen_03_rejects_destructive_prompts(db_session):
    schemas = [_stripe_subs()]
    with pytest.raises(FormulaGenerationError):
        generate_formula(
            "delete all users where status = 'inactive'", schemas
        )


@pytest.mark.asyncio
async def test_gen_04_output_is_readonly_validated(db_session):
    """If a custom LLM returns destructive SQL, the guard rejects it."""
    schemas = [_stripe_subs()]

    def evil_llm(_text, _schemas):
        return GenerationResult(sql="DELETE FROM stripe_subscriptions")

    set_llm_generator(evil_llm)
    with pytest.raises(FormulaGenerationError):
        generate_formula("count subscriptions", schemas)


@pytest.mark.asyncio
async def test_gen_05_iterative_refinement(db_session):
    """Same generator called twice gives stable output — important
    for the user editing a description and re-running.
    """
    schemas = [_stripe_subs()]
    a = generate_formula("count of stripe subscriptions", schemas)
    b = generate_formula("count of stripe subscriptions", schemas)
    assert a.sql == b.sql

    c = generate_formula("sum of stripe subscriptions amount", schemas)
    assert "SUM" in c.sql.upper()
    assert c.sql != a.sql


@pytest.mark.asyncio
async def test_gen_06_save_persists_description_and_text(db_session, test_user):
    """When the FE saves the metric, both formula_description and
    formula_text are written. Pin the contract through MetricService."""
    from src.schemas.metric import MetricCreate
    from src.services.metric_service import MetricService

    user = test_user["user"]
    schemas = [_stripe_subs()]
    generated = generate_formula("count of stripe subscriptions", schemas)

    metric = await MetricService(db_session).create(
        user,
        MetricCreate(
            name="Stripe sub count",
            scope="personal",
            scope_id=user.id,
            formula_description="count of stripe subscriptions",
            formula_text=generated.sql,
            formula_language="sql",
        ),
    )
    assert metric.formula_description == "count of stripe subscriptions"
    assert metric.formula_text == generated.sql
    assert metric.formula_language == "sql"


@pytest.mark.asyncio
async def test_gen_07_sandbox_test_runs_against_readonly_role(db_session):
    """Pin the contract that the generator output is what gets sent
    to the sandbox runner. The sandbox driver is connection-bound
    (read-only role); here we ensure the SQL guard always greenlights
    the generator's output.
    """
    from src.ai.tools.sql_guard import guard_sql

    schemas = [_stripe_subs()]
    result = generate_formula("count of stripe subscriptions", schemas)
    guarded = guard_sql(result.sql, authorized_tables=[s.name for s in schemas])
    assert "SELECT" in guarded.sql.upper()
