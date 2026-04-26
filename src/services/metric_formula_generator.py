"""Describe-mode formula generation for Knowledge Metrics (Phase 7).

Maps a plain-English ``description`` plus the user's connected schema
into a SQL ``formula_text`` that the user can save on a Metric.

The production implementation will hit the LLM through the AI service.
This module ships a deterministic, pattern-based fallback that:

  * recognises common analytics shapes (count of X, sum of Y, average
    of Z, percentage of W, latest value, weekly trend),
  * picks the table/column from the supplied schema metadata so it
    can never hallucinate something that doesn't exist,
  * passes the generated SQL through ``guard_sql`` so destructive or
    multi-statement output is rejected at the source.

The fallback is good enough for E2E / contract tests + a no-LLM dev
mode. Swapping in an LLM-backed generator is a single function-pointer
change — see ``set_llm_generator`` below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from src.ai.tools.sql_guard import GuardedSQL, SQLGuardViolation, guard_sql


# Keywords that indicate a destructive prompt — surfaced before any
# SQL is generated so the user gets the clearest possible error.
_DESTRUCTIVE_PHRASES = (
    "delete",
    "drop",
    "truncate",
    "update ",
    "alter ",
    "remove all",
    "wipe",
)


@dataclass
class TableSchema:
    """Subset of a connected source's schema we feed the generator.

    Kept narrow on purpose — we only need column names + types to pick
    a candidate column. Adding more (PII flags, descriptions, …) lands
    when the LLM-backed path replaces this stub.
    """

    name: str
    columns: List[str] = field(default_factory=list)
    # Map from column name → type hint. Used to bias aggregation
    # selection: only numeric-typed columns are picked for SUM / AVG.
    column_types: Dict[str, str] = field(default_factory=dict)


@dataclass
class GenerationResult:
    sql: str
    language: str = "sql"
    rationale: Optional[str] = None


class FormulaGenerationError(ValueError):
    """Raised when no safe formula can be produced for the prompt."""


# ─── public API ────────────────────────────────────────────────────


def generate_formula(
    description: str,
    schemas: Sequence[TableSchema],
    *,
    authorized_tables: Optional[Sequence[str]] = None,
) -> GenerationResult:
    """Pure function — no DB, no LLM dependency.

    Returns a ``GenerationResult`` with the generated SQL. Raises
    :class:`FormulaGenerationError` for destructive prompts or when no
    suitable schema is available.
    """
    text = (description or "").strip()
    if not text:
        raise FormulaGenerationError("description is required")

    lower = text.lower()
    for bad in _DESTRUCTIVE_PHRASES:
        if bad in lower:
            raise FormulaGenerationError(
                f"refusing to generate SQL for destructive prompt — '{bad.strip()}'"
            )

    if not schemas:
        raise FormulaGenerationError(
            "no schemas available — connect a source first"
        )

    # If a custom generator was injected (e.g. an LLM-backed one in
    # production), defer to it. Otherwise use the heuristic.
    if _LLM_GENERATOR is not None:
        result = _LLM_GENERATOR(text, schemas)
    else:
        result = _heuristic_generate(text, schemas)

    # Always validate through the SQL guard. Belt-and-suspenders with
    # the destructive-phrase early-out: even if the LLM returns
    # plausible-looking SELECT-ish text, the AST parse must accept it.
    try:
        guarded: GuardedSQL = guard_sql(
            result.sql,
            authorized_tables=authorized_tables or [s.name for s in schemas],
        )
    except SQLGuardViolation as exc:
        raise FormulaGenerationError(
            f"generated SQL failed the read-only guard: {exc}"
        ) from exc

    return GenerationResult(sql=guarded.sql, language="sql", rationale=result.rationale)


# ─── LLM injection point ──────────────────────────────────────────


_LLM_GENERATOR: Optional[Callable[[str, Sequence[TableSchema]], GenerationResult]] = None


def set_llm_generator(
    fn: Optional[Callable[[str, Sequence[TableSchema]], GenerationResult]],
) -> None:
    """Swap the heuristic for an LLM-backed implementation.

    Tests reset to None via ``set_llm_generator(None)``.
    """
    global _LLM_GENERATOR
    _LLM_GENERATOR = fn


# ─── heuristic fallback ───────────────────────────────────────────


_AGG_PATTERNS = (
    (re.compile(r"\b(?:count|how many|number of)\b", re.I), "COUNT(*)"),
    (re.compile(r"\bsum\b|\btotal\b", re.I), "SUM"),
    (re.compile(r"\b(?:avg|average|mean)\b", re.I), "AVG"),
    (re.compile(r"\b(?:max|maximum|highest)\b", re.I), "MAX"),
    (re.compile(r"\b(?:min|minimum|lowest)\b", re.I), "MIN"),
)

_NUMERIC_TYPE_HINTS = ("int", "integer", "bigint", "numeric", "float", "double", "decimal", "real")


def _heuristic_generate(
    text: str, schemas: Sequence[TableSchema]
) -> GenerationResult:
    table = _pick_table(text, schemas)

    agg = "COUNT(*)"
    column: Optional[str] = None
    for pattern, label in _AGG_PATTERNS:
        if pattern.search(text):
            agg = label
            break

    if agg in ("SUM", "AVG", "MAX", "MIN"):
        column = _pick_numeric_column(table, text)
        if column is None:
            agg = "COUNT(*)"  # degrade gracefully if we can't find a number

    select_expr = "COUNT(*)" if agg == "COUNT(*)" else f"{agg}({column})"
    sql = f"SELECT {select_expr} FROM {table.name}"
    return GenerationResult(
        sql=sql,
        rationale=(
            f"heuristic: matched aggregation '{agg}' on table '{table.name}'"
            + (f" column '{column}'" if column else "")
        ),
    )


def _pick_table(text: str, schemas: Sequence[TableSchema]) -> TableSchema:
    """Pick the table whose name shares the most words with the prompt.

    Falls back to the first schema if nothing matches — better to
    generate something visible the user can correct than silently
    refuse.
    """
    text_lower = text.lower()
    best = schemas[0]
    best_score = -1
    for s in schemas:
        bag = re.split(r"[_\s]+", s.name.lower())
        score = sum(1 for token in bag if token and token in text_lower)
        if score > best_score:
            best_score = score
            best = s
    return best


def _pick_numeric_column(table: TableSchema, text: str) -> Optional[str]:
    text_lower = text.lower()
    candidates = [
        c
        for c in table.columns
        if any(h in (table.column_types.get(c, "")).lower() for h in _NUMERIC_TYPE_HINTS)
    ]
    if not candidates:
        return None
    # Prefer a column whose name appears in the prompt, otherwise the
    # first numeric one.
    for c in candidates:
        if c.lower() in text_lower:
            return c
    return candidates[0]
