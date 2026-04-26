"""Source aliases — Phase 1c of the Knowledge refactor.

The full table-rename `data_connection` → `data_source` is a coordinated
BE+AI+FE change that we're staging in instead of doing as a flag-day
cutover. The first step is to expose ``DataSource`` as an alias of
``DataConnection`` so callers can import either name. Phase 1c-bis
(separate PR) will rename internal references to the alias; Phase
1c-final renames the table itself once every caller is on the alias.

This file is intentionally tiny — a re-export, nothing more. The
plan in KNOWLEDGE_REFACTOR.md §6 calls for the new name to be
``data_source``; this is the first step.
"""

from __future__ import annotations

from src.models.connection import (
    ColumnMetadata,
    ConnectionMetadata as SourceMetadata,
    DataConnection as DataSource,
    TableMetadata,
)

__all__ = [
    "DataSource",
    "SourceMetadata",
    "TableMetadata",
    "ColumnMetadata",
]
