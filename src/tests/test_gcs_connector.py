"""Tests for src/connectors/gcs.py — GCS as read-only tabular source."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.gcs import GCSConnector


def _config(**overrides):
    base = {
        "project_id": "my-project",
        "service_account_json": '{"type":"service_account","project_id":"my-project"}',
    }
    base.update(overrides)
    return base


def _fake_bucket(name, location="US", storage_class="STANDARD", time_created=None):
    b = MagicMock()
    b.name = name
    b.location = location
    b.storage_class = storage_class
    b.time_created = time_created or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return b


def _fake_blob(name, size=100, content_type="application/json", updated=None,
               md5_hash="abc", storage_class="STANDARD"):
    b = MagicMock()
    b.name = name
    b.size = size
    b.content_type = content_type
    b.updated = updated or datetime(2026, 4, 24, tzinfo=timezone.utc)
    b.md5_hash = md5_hash
    b.storage_class = storage_class
    return b


@pytest.mark.asyncio
async def test_test_connection_true_when_list_buckets_succeeds():
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_buckets.return_value = [_fake_bucket("a")]
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        ok = await conn.test_connection(_config())
    assert ok is True
    fake_client.list_buckets.assert_called_once()
    # max_results=1 keeps the probe cheap.
    assert fake_client.list_buckets.call_args.kwargs == {"max_results": 1}


@pytest.mark.asyncio
async def test_test_connection_false_on_exception():
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_buckets.side_effect = Exception("invalid_grant")
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        ok = await conn.test_connection(_config())
    assert ok is False


@pytest.mark.asyncio
async def test_get_metadata_exposes_declared_objects_as_tables():
    conn = GCSConnector()
    config = _config(objects=[
        {"name": "ingest", "object_type": "objects", "bucket": "sky-ingest", "prefix": "2026/04/"},
        {"name": "all_buckets", "object_type": "buckets"},
    ])
    meta = await conn.get_metadata(config)
    names = [t["name"] for t in meta["tables"]]
    assert names == ["ingest", "all_buckets"]
    assert meta["tables"][0]["metadata"]["bucket"] == "sky-ingest"
    assert meta["tables"][0]["metadata"]["prefix"] == "2026/04/"
    assert meta["tables"][0]["kind"] == "gcs_object"
    obj_cols = [c["name"] for c in meta["tables"][0]["columns"]]
    assert "name" in obj_cols and "size" in obj_cols and "md5_hash" in obj_cols


@pytest.mark.asyncio
async def test_execute_query_buckets_returns_flattened_rows():
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_buckets.return_value = [
        _fake_bucket("sky-ingest"),
        _fake_bucket("sky-warehouse", location="EU"),
    ]
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        rows = await conn.execute_query(_config(), "buckets")
    assert len(rows) == 2
    assert rows[0]["name"] == "sky-ingest"
    assert rows[1]["location"] == "EU"
    # Datetime → ISO string for JSON-friendly downstream consumption.
    assert rows[0]["created"].startswith("2026-01-01")


@pytest.mark.asyncio
async def test_execute_query_empty_string_defaults_to_buckets():
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_buckets.return_value = []
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        await conn.execute_query(_config(), "")
    fake_client.list_buckets.assert_called_once()


@pytest.mark.asyncio
async def test_execute_query_objects_lists_with_prefix_and_limit():
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_blobs.return_value = [
        _fake_blob("2026/04/24/event-1.json", size=1234),
        _fake_blob("2026/04/24/event-2.json", size=5678),
    ]
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"objects","bucket":"sky-ingest","prefix":"2026/04/","limit":50}',
        )
    fake_client.list_blobs.assert_called_once()
    args, kwargs = fake_client.list_blobs.call_args
    # First positional arg is the bucket name.
    assert args[0] == "sky-ingest"
    assert kwargs["prefix"] == "2026/04/"
    assert kwargs["max_results"] == 50
    assert len(rows) == 2
    assert rows[0]["bucket"] == "sky-ingest"
    assert rows[0]["name"] == "2026/04/24/event-1.json"
    assert rows[0]["size"] == 1234


@pytest.mark.asyncio
async def test_execute_query_objects_requires_bucket():
    conn = GCSConnector()
    with patch("src.connectors.gcs._build_client", return_value=MagicMock()):
        with pytest.raises(ValueError, match="bucket"):
            await conn.execute_query(_config(), '{"object_type":"objects"}')


@pytest.mark.asyncio
async def test_execute_query_unknown_object_type_raises():
    conn = GCSConnector()
    with patch("src.connectors.gcs._build_client", return_value=MagicMock()):
        with pytest.raises(ValueError, match="Unknown GCS object_type"):
            await conn.execute_query(_config(), "blocks")


@pytest.mark.asyncio
async def test_execute_query_invalid_json_raises_value_error():
    conn = GCSConnector()
    with pytest.raises(ValueError, match="Invalid GCS query JSON"):
        await conn.execute_query(_config(), '{"object_type":"objects",')


@pytest.mark.asyncio
async def test_objects_limit_clamped_to_1000():
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_blobs.return_value = []
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        await conn.execute_query(
            _config(),
            '{"object_type":"objects","bucket":"x","limit":99999}',
        )
    assert fake_client.list_blobs.call_args.kwargs["max_results"] == 1000


@pytest.mark.asyncio
async def test_sync_data_returns_rows_by_object():
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_buckets.return_value = [_fake_bucket("a"), _fake_bucket("b")]
    fake_client.list_blobs.return_value = [_fake_blob("x.json")]
    config = _config(objects=[
        {"name": "buckets", "object_type": "buckets"},
        {"name": "logs", "object_type": "objects", "bucket": "sky-logs", "prefix": "2026/"},
    ])
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        result = await conn.sync_data(config)
    assert result["success"] is True
    assert result["rows_by_object"]["buckets"] == 2
    assert result["rows_by_object"]["logs"] == 1


@pytest.mark.asyncio
async def test_service_account_json_can_be_dict_or_string():
    """Both BigQuery and GCS connectors accept the service account either
    pre-parsed (dict) or raw (JSON string) — keep the surface symmetric."""
    conn = GCSConnector()
    fake_client = MagicMock()
    fake_client.list_buckets.return_value = []
    with patch("src.connectors.gcs._build_client", return_value=fake_client):
        await conn.execute_query(
            {"project_id": "p", "service_account_json": {"project_id": "p"}},
            "buckets",
        )
    fake_client.list_buckets.assert_called_once()
