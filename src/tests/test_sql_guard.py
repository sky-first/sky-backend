"""W8 — SQL AST guard tests.

Thinking as a QA tester + attacker:

A. Benign SELECT variants (joins, WHERE, GROUP BY, ORDER BY, subqueries).
B. Table whitelist — referenced tables must be authorised.
C. DML / DDL / TCL / DCL rejected at every keyword.
D. Multi-statement attack (stacked queries) rejected.
E. Comment-based obfuscation rejected.
F. LIMIT auto-appended when missing; clamped when too high; respected
   when already safe.
G. Registry: lookup, unknown tool, enumeration.
H. Edge cases: empty SQL, whitespace-only, unicode identifiers, tables
   with schema prefix + quotes.
"""

from __future__ import annotations

import pytest

from src.ai.tools.registry import (
    TOOL_REGISTRY,
    ToolNotAllowed,
    ToolSpec,
    all_tool_names,
    get_tool,
)
from src.ai.tools.sql_guard import (
    DEFAULT_MAX_ROWS,
    GuardedSQL,
    SQLGuardViolation,
    SQLMalformed,
    guard_sql,
)


AUTH = ("orders", "customers", "line_items")


# ---------------------------------------------------------------------------
#  A — Benign SELECT variants
# ---------------------------------------------------------------------------


class TestBenignSelects:
    def test_plain_select(self):
        g = guard_sql("SELECT id, total FROM orders", authorized_tables=AUTH)
        assert "FROM orders" in g.sql
        assert g.rewrote_limit is True  # auto-appended
        assert g.tables_referenced == ["orders"]

    def test_select_with_where_and_order(self):
        g = guard_sql(
            "SELECT id FROM orders WHERE total > 100 ORDER BY id DESC",
            authorized_tables=AUTH,
        )
        assert "orders" in g.tables_referenced
        assert "LIMIT" in g.sql.upper()

    def test_select_with_join(self):
        g = guard_sql(
            "SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id",
            authorized_tables=AUTH,
        )
        assert set(g.tables_referenced) == {"orders", "customers"}

    def test_select_with_left_join(self):
        g = guard_sql(
            "SELECT * FROM orders LEFT JOIN line_items ON line_items.order_id = orders.id",
            authorized_tables=AUTH,
        )
        assert set(g.tables_referenced) == {"orders", "line_items"}

    def test_group_by_having(self):
        g = guard_sql(
            "SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id HAVING COUNT(*) > 5",
            authorized_tables=AUTH,
        )
        assert g.tables_referenced == ["orders"]


# ---------------------------------------------------------------------------
#  B — Table whitelist
# ---------------------------------------------------------------------------


class TestWhitelist:
    def test_unauthorised_table_rejected(self):
        with pytest.raises(SQLGuardViolation, match="users"):
            guard_sql("SELECT id FROM users", authorized_tables=AUTH)

    def test_unauthorised_table_in_join_rejected(self):
        with pytest.raises(SQLGuardViolation, match="secrets"):
            guard_sql(
                "SELECT o.id FROM orders o JOIN secrets s ON s.id = o.id",
                authorized_tables=AUTH,
            )

    def test_unauthorised_subquery_table_rejected(self):
        with pytest.raises(SQLGuardViolation):
            guard_sql(
                "SELECT * FROM orders WHERE id IN (SELECT id FROM forbidden_table)",
                authorized_tables=AUTH,
            )

    def test_schema_qualified_names_stripped(self):
        """``public.orders`` → whitelist matches ``orders``."""
        g = guard_sql("SELECT id FROM public.orders", authorized_tables=AUTH)
        assert "orders" in g.tables_referenced

    def test_quoted_identifiers_stripped(self):
        g = guard_sql('SELECT id FROM "orders"', authorized_tables=AUTH)
        assert "orders" in g.tables_referenced

    def test_empty_whitelist_means_nothing_allowed(self):
        with pytest.raises(SQLGuardViolation):
            guard_sql("SELECT id FROM orders", authorized_tables=())


# ---------------------------------------------------------------------------
#  C — DML / DDL / TCL / DCL rejected
# ---------------------------------------------------------------------------


class TestForbiddenStatements:
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO orders VALUES (1, 2)",
            "UPDATE orders SET total = 0",
            "DELETE FROM orders WHERE id = 1",
            "DROP TABLE orders",
            "TRUNCATE TABLE orders",
            "ALTER TABLE orders ADD COLUMN x INT",
            "CREATE TABLE x (id INT)",
            "GRANT SELECT ON orders TO anon",
            "REVOKE ALL ON orders FROM anon",
            "COMMIT",
            "BEGIN",
            "SET search_path TO public",
            "COPY orders TO '/tmp/x'",
            "CALL my_procedure()",
            "EXPLAIN SELECT * FROM orders",
        ],
    )
    def test_forbidden_rejected(self, sql):
        with pytest.raises(SQLGuardViolation):
            guard_sql(sql, authorized_tables=AUTH)

    def test_hidden_dml_in_select_rejected(self):
        """Attacker puts forbidden keyword inside a subquery or CTE."""
        with pytest.raises(SQLGuardViolation):
            guard_sql(
                "WITH t AS (DELETE FROM orders RETURNING *) SELECT * FROM t",
                authorized_tables=AUTH,
            )


# ---------------------------------------------------------------------------
#  D — Multi-statement / comment obfuscation
# ---------------------------------------------------------------------------


class TestObfuscation:
    def test_stacked_statements_rejected(self):
        with pytest.raises(SQLGuardViolation):
            guard_sql(
                "SELECT * FROM orders; DROP TABLE orders",
                authorized_tables=AUTH,
            )

    def test_embedded_semicolon_rejected(self):
        """Two-statement payload that a naive parser might miss."""
        with pytest.raises(SQLGuardViolation):
            guard_sql(
                "SELECT * FROM orders ; SELECT 1",
                authorized_tables=AUTH,
            )

    def test_line_comment_rejected(self):
        with pytest.raises(SQLGuardViolation, match="comments"):
            guard_sql(
                "SELECT * FROM orders -- DROP TABLE orders",
                authorized_tables=AUTH,
            )

    def test_block_comment_rejected(self):
        with pytest.raises(SQLGuardViolation, match="comments"):
            guard_sql(
                "SELECT /* UNION SELECT password FROM users */ * FROM orders",
                authorized_tables=AUTH,
            )


# ---------------------------------------------------------------------------
#  E — LIMIT handling
# ---------------------------------------------------------------------------


class TestLimit:
    def test_missing_limit_appended(self):
        g = guard_sql("SELECT id FROM orders", authorized_tables=AUTH)
        assert g.rewrote_limit is True
        assert f"LIMIT {DEFAULT_MAX_ROWS}" in g.sql

    def test_existing_safe_limit_preserved(self):
        g = guard_sql(
            "SELECT id FROM orders LIMIT 50",
            authorized_tables=AUTH,
        )
        assert g.rewrote_limit is False
        assert "LIMIT 50" in g.sql

    def test_too_high_limit_clamped(self):
        g = guard_sql(
            "SELECT id FROM orders LIMIT 999999",
            authorized_tables=AUTH,
        )
        assert g.rewrote_limit is True
        assert f"LIMIT {DEFAULT_MAX_ROWS}" in g.sql
        assert "999999" not in g.sql

    def test_custom_max_rows(self):
        g = guard_sql(
            "SELECT id FROM orders",
            authorized_tables=AUTH,
            max_rows=10,
        )
        assert "LIMIT 10" in g.sql

    def test_limit_preserved_when_exactly_equal(self):
        g = guard_sql(
            "SELECT id FROM orders LIMIT 1000",
            authorized_tables=AUTH,
        )
        assert g.rewrote_limit is False


# ---------------------------------------------------------------------------
#  F — Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_sql(self):
        with pytest.raises(SQLMalformed):
            guard_sql("", authorized_tables=AUTH)

    def test_whitespace_only(self):
        with pytest.raises(SQLMalformed):
            guard_sql("   \n\t  ", authorized_tables=AUTH)

    def test_unparseable(self):
        with pytest.raises(SQLGuardViolation):
            guard_sql(")))", authorized_tables=AUTH)

    def test_returns_guarded_sql(self):
        g = guard_sql("SELECT 1 FROM orders", authorized_tables=AUTH)
        assert isinstance(g, GuardedSQL)
        assert isinstance(g.tables_referenced, list)


# ---------------------------------------------------------------------------
#  G — Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_known_tool_returns_spec(self):
        spec = get_tool("sql.select")
        assert isinstance(spec, ToolSpec)
        assert spec.permissions == ("connection.read",)
        assert spec.rate_limit == (60, "minute")

    def test_unknown_tool_raises(self):
        with pytest.raises(ToolNotAllowed):
            get_tool("sql.delete")

    def test_all_tools_listed(self):
        names = all_tool_names()
        assert "sql.select" in names
        assert "widget.create" in names
        # sorted
        assert names == sorted(names)

    def test_registry_is_frozen_in_effect(self):
        """Editing the returned spec shouldn't affect the registry."""
        spec = get_tool("sql.select")
        with pytest.raises(Exception):
            spec.name = "hax"  # type: ignore[misc]

    def test_every_tool_has_validator_or_scope(self):
        """Sanity: no orphan tools without some form of scoping."""
        for name, spec in TOOL_REGISTRY.items():
            assert spec.permissions, f"{name}: no permissions declared"
            assert spec.scope, f"{name}: no scope declared"
            assert spec.rate_limit[0] > 0, f"{name}: rate_limit must be positive"

    def test_sql_select_validator_adapts(self):
        spec = get_tool("sql.select")
        assert callable(spec.validator)
        # Direct call — the executor will invoke this as
        # ``spec.validator(sql=..., authorized_tables=...)``
        result = spec.validator("SELECT id FROM orders", AUTH)  # type: ignore[misc]
        assert isinstance(result, GuardedSQL)
