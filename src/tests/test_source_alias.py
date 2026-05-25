"""Pin the DataSource alias contract — Phase 1c.

These tests are tiny on purpose. They guarantee that the new
``DataSource`` / ``SourceMetadata`` names import to the same classes
as the legacy connection names, so callers can switch progressively.
"""

from __future__ import annotations


def test_data_source_is_data_connection_alias():
    from src.models.connection import DataConnection
    from src.models.source import DataSource

    assert DataSource is DataConnection


def test_source_metadata_is_connection_metadata_alias():
    from src.models.connection import ConnectionMetadata
    from src.models.source import SourceMetadata

    assert SourceMetadata is ConnectionMetadata


def test_table_column_metadata_re_exported():
    from src.models.connection import ColumnMetadata, TableMetadata
    from src.models.source import ColumnMetadata as ASrcColumn, TableMetadata as ASrcTable

    assert ASrcTable is TableMetadata
    assert ASrcColumn is ColumnMetadata
