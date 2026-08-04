"""First-setup Glossary + Metrics derivation from a connection's real schema.

This service produces a **first-pass** glossary and metric suggestions
derived *faithfully* from the connection's already-discovered metadata —
the real table names, column names, types, descriptions and row counts
stored in ``ConnectionMetadata.tables`` (populated by the sync / discover
pipeline). It never invents business vocabulary.

Hard rule (Lucas / GBT requirement): every suggestion must be grounded
in something that actually exists in the customer's schema. We do not
fabricate canonical SaaS metrics (MRR, Churn, AOV, …) the way the older
``knowledge_suggest_service`` pattern matcher does — that engine guesses
business meaning from column-name overlap and is *not* used here.

What we derive, and the evidence behind it:

  * **Glossary term per table** — ``term`` is the humanised table name,
    ``definition`` is the table's real ``description`` when the sync
    captured one, otherwise a minimal neutral sentence built from the
    table name (and row count, if known). Provenance: ``source_table``.

  * **Glossary term per documented column** — only for columns that
    carry a real ``description`` from the source. We never make up a
    meaning for an undocumented column; we leave it for the user.

  * **Row-count metric per table** — ``SELECT COUNT(*) FROM <table>``.
    This is always true for a real table, regardless of its columns.

  * **SUM / AVG candidate metrics** over real *numeric* columns —
    ``SELECT SUM(<col>) FROM <table>`` etc. The column and table are
    real; the aggregation is a candidate the user can keep or discard.

Every suggestion is marked ``source="auto"`` and ``reviewed=False`` so
the UI presents them as unreviewed proposals the user must curate before
they become certified knowledge. Nothing here writes to the DB — the
caller decides what to persist via the existing Glossary / Metric
services.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.connection import ConnectionMetadataRepository

# Type hints that mark a column as numeric — only these are eligible for
# SUM / AVG candidate metrics. Anything else (text, uuid, timestamp,
# boolean, json) is skipped so we never propose summing a non-number.
_NUMERIC_TYPE_HINTS = (
    "int",
    "integer",
    "bigint",
    "smallint",
    "numeric",
    "decimal",
    "float",
    "double",
    "real",
    "money",
)

# Column names that are numerically typed but are *identifiers*, not
# measures. Summing or averaging an id is meaningless, so we exclude
# them from SUM/AVG candidates (a COUNT over the table still covers the
# "how many rows" question).
_ID_COLUMN_RE = re.compile(r"(^id$|_id$|^pk$|_pk$|uuid)", re.IGNORECASE)


@dataclass
class GlossarySuggestion:
    """A proposed glossary term grounded in a real table or column."""

    term: str
    definition: str
    source_table: str
    source_column: Optional[str] = None
    source: str = "auto"
    reviewed: bool = False


@dataclass
class MetricSuggestion:
    """A proposed metric grounded in a real table / numeric column.

    ``formula_text`` is real, runnable SQL referencing only the actual
    table/column. ``aggregation`` mirrors the Metric model's field so the
    caller can persist it directly.
    """

    name: str
    aggregation: str
    formula_text: str
    source_table: str
    source_column: Optional[str] = None
    description: Optional[str] = None
    source: str = "auto"
    reviewed: bool = False


@dataclass
class ConnectionKnowledgeSuggestions:
    glossary: List[GlossarySuggestion] = field(default_factory=list)
    metrics: List[MetricSuggestion] = field(default_factory=list)


# ─── helpers ─────────────────────────────────────────────────────────


def _humanise(identifier: str) -> str:
    """Turn ``people_types`` / ``peopleTypes`` into ``People Types``.

    Pure cosmetic — used for the *label* only. The provenance fields
    always keep the raw identifier so the SQL stays exact.
    """
    if not identifier:
        return identifier
    # snake_case → spaces
    s = identifier.replace("_", " ")
    # camelCase → spaced
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.title() if s else identifier


def _is_numeric(col_type: Optional[str]) -> bool:
    if not col_type:
        return False
    low = col_type.lower()
    return any(h in low for h in _NUMERIC_TYPE_HINTS)


def _table_field(table: Any, key: str, default: Any = None) -> Any:
    """Read a field from a table entry that may be a dict or an object.

    ``ConnectionMetadata.tables`` is JSON, so entries are normally dicts.
    We tolerate objects too (e.g. ``TableMetadataSchema``) for callers
    that pre-validate.
    """
    if isinstance(table, dict):
        return table.get(key, default)
    return getattr(table, key, default)


def _neutral_table_definition(name: str, row_count: Optional[int]) -> str:
    """Minimal, non-fabricated definition for a table with no description.

    We state only what we can prove: it's a data table from the source,
    its real name, and (if known) its size. No invented business meaning.
    """
    base = f'Data table "{name}" from the connected source.'
    if isinstance(row_count, int) and row_count >= 0:
        base += f" Approximately {row_count:,} rows at last sync."
    base += " Definition pending review."
    return base


# ─── pure derivation (no DB) ─────────────────────────────────────────


def derive_suggestions(
    tables: Sequence[Any],
) -> ConnectionKnowledgeSuggestions:
    """Derive glossary + metric suggestions from real table metadata.

    ``tables`` is the ``ConnectionMetadata.tables`` JSON list (dicts) or
    an equivalent sequence of objects exposing ``name`` / ``description``
    / ``row_count`` / ``columns``. Empty input → empty output; we never
    fabricate.
    """
    result = ConnectionKnowledgeSuggestions()
    if not tables:
        return result

    seen_terms: set[str] = set()

    for table in tables:
        name = _table_field(table, "name")
        if not name or not isinstance(name, str):
            continue

        description = _table_field(table, "description")
        row_count = _table_field(table, "row_count")
        columns = _table_field(table, "columns") or []

        # ── Glossary term per table ──────────────────────────────────
        term_label = _humanise(name)
        term_key = term_label.lower()
        if term_key not in seen_terms:
            seen_terms.add(term_key)
            definition = (
                description.strip()
                if isinstance(description, str) and description.strip()
                else _neutral_table_definition(name, row_count)
            )
            result.glossary.append(
                GlossarySuggestion(
                    term=term_label,
                    definition=definition,
                    source_table=name,
                )
            )

        # ── Row-count metric per table ───────────────────────────────
        # Always valid for a real table; answers "how many <table>".
        result.metrics.append(
            MetricSuggestion(
                name=f"{term_label} count",
                aggregation="COUNT",
                formula_text=f"SELECT COUNT(*) FROM {name}",
                source_table=name,
                source_column=None,
                description=f"Total number of rows in {name}.",
            )
        )

        # ── Column-level derivations ─────────────────────────────────
        for col in columns:
            col_name = _table_field(col, "name")
            if not col_name or not isinstance(col_name, str):
                continue
            col_type = _table_field(col, "type")
            col_desc = _table_field(col, "description")

            # Glossary term only for *documented* columns — never invent
            # a meaning for an undocumented one.
            if isinstance(col_desc, str) and col_desc.strip():
                col_term_label = f"{term_label} · {_humanise(col_name)}"
                col_term_key = col_term_label.lower()
                if col_term_key not in seen_terms:
                    seen_terms.add(col_term_key)
                    result.glossary.append(
                        GlossarySuggestion(
                            term=col_term_label,
                            definition=col_desc.strip(),
                            source_table=name,
                            source_column=col_name,
                        )
                    )

            # SUM / AVG candidate metrics over real numeric, non-id cols.
            if _is_numeric(col_type) and not _ID_COLUMN_RE.search(col_name):
                col_label = _humanise(col_name)
                result.metrics.append(
                    MetricSuggestion(
                        name=f"Total {col_label} ({term_label})",
                        aggregation="SUM",
                        formula_text=f"SELECT SUM({col_name}) FROM {name}",
                        source_table=name,
                        source_column=col_name,
                        description=f"Sum of {col_name} across {name}.",
                    )
                )
                result.metrics.append(
                    MetricSuggestion(
                        name=f"Average {col_label} ({term_label})",
                        aggregation="AVG",
                        formula_text=f"SELECT AVG({col_name}) FROM {name}",
                        source_table=name,
                        source_column=col_name,
                        description=f"Average {col_name} across {name}.",
                    )
                )

    return result


# ─── DB-backed entry point ───────────────────────────────────────────


class ConnectionKnowledgeSuggestService:
    """Reads a connection's discovered metadata and derives suggestions.

    Stateless apart from the DB session. Performs no writes — it only
    *reads* ``ConnectionMetadata`` and returns proposals. Persisting the
    accepted ones goes through the existing Glossary / Metric services so
    all the scope + RBAC rules stay in one place.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.metadata_repo = ConnectionMetadataRepository(db)

    async def suggest_for_connection(self, connection_id: UUID) -> ConnectionKnowledgeSuggestions:
        """Derive glossary + metric suggestions for a connection.

        Returns empty suggestions when the connection has no discovered
        metadata yet (rather than fabricating). The caller is responsible
        for the access check before invoking this.
        """
        metadata = await self.metadata_repo.get_by_connection_id(connection_id)
        if metadata is None or not metadata.tables:
            return ConnectionKnowledgeSuggestions()
        return derive_suggestions(metadata.tables)
