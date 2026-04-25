"""Tests for src/connectors/s3.py — S3 as read-only tabular source."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.s3 import S3Connector


def _config(**overrides):
    base = {
        "auth": {
            "type": "aws_keys",
            "aws_access_key_id": "AKIAFAKE",
            "aws_secret_access_key": "secret",
        },
        "region_name": "us-east-1",
    }
    base.update(overrides)
    return base


def _fake_client(**responses):
    client = MagicMock()
    if "list_buckets" in responses:
        client.list_buckets.return_value = responses["list_buckets"]
    if "list_objects_v2" in responses:
        client.list_objects_v2.return_value = responses["list_objects_v2"]
    if "list_buckets_raises" in responses:
        client.list_buckets.side_effect = responses["list_buckets_raises"]
    return client


@pytest.mark.asyncio
async def test_test_connection_true_when_list_buckets_succeeds():
    conn = S3Connector()
    fake = _fake_client(list_buckets={"Buckets": []})
    with patch("src.connectors.s3._build_client", return_value=fake):
        ok = await conn.test_connection(_config())
    assert ok is True
    fake.list_buckets.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_false_on_exception():
    conn = S3Connector()
    fake = _fake_client(list_buckets_raises=Exception("InvalidAccessKeyId"))
    with patch("src.connectors.s3._build_client", return_value=fake):
        ok = await conn.test_connection(_config())
    assert ok is False


@pytest.mark.asyncio
async def test_get_metadata_exposes_declared_objects_as_tables():
    conn = S3Connector()
    config = _config(objects=[
        {"name": "ingest", "object_type": "objects", "bucket": "sky-ingest", "prefix": "2026/04/"},
        {"name": "all_buckets", "object_type": "buckets"},
    ])
    meta = await conn.get_metadata(config)
    names = [t["name"] for t in meta["tables"]]
    assert names == ["ingest", "all_buckets"]
    assert meta["tables"][0]["metadata"]["bucket"] == "sky-ingest"
    assert meta["tables"][0]["metadata"]["prefix"] == "2026/04/"
    assert meta["tables"][0]["kind"] == "s3_object"
    obj_cols = [c["name"] for c in meta["tables"][0]["columns"]]
    assert "key" in obj_cols and "size" in obj_cols and "etag" in obj_cols


@pytest.mark.asyncio
async def test_execute_query_buckets_returns_flattened_rows():
    conn = S3Connector()
    fake = _fake_client(list_buckets={
        "Buckets": [
            {"Name": "sky-ingest", "CreationDate": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            {"Name": "sky-warehouse", "CreationDate": datetime(2026, 2, 1, tzinfo=timezone.utc)},
        ]
    })
    with patch("src.connectors.s3._build_client", return_value=fake):
        rows = await conn.execute_query(_config(), "buckets")
    assert len(rows) == 2
    assert rows[0]["name"] == "sky-ingest"
    # Datetime → ISO string for JSON-friendly downstream consumption.
    assert rows[0]["creation_date"].startswith("2026-01-01")


@pytest.mark.asyncio
async def test_execute_query_empty_string_defaults_to_buckets():
    conn = S3Connector()
    fake = _fake_client(list_buckets={"Buckets": []})
    with patch("src.connectors.s3._build_client", return_value=fake):
        await conn.execute_query(_config(), "")
    fake.list_buckets.assert_called_once()


@pytest.mark.asyncio
async def test_execute_query_objects_lists_with_prefix_and_limit():
    conn = S3Connector()
    fake = _fake_client(list_objects_v2={
        "Contents": [
            {
                "Key": "2026/04/24/event-1.json",
                "Size": 1234,
                "LastModified": datetime(2026, 4, 24, tzinfo=timezone.utc),
                "StorageClass": "STANDARD",
                "ETag": '"abc123"',
            },
            {
                "Key": "2026/04/24/event-2.json",
                "Size": 5678,
                "LastModified": datetime(2026, 4, 24, tzinfo=timezone.utc),
                "StorageClass": "STANDARD",
                "ETag": '"def456"',
            },
        ],
    })
    with patch("src.connectors.s3._build_client", return_value=fake):
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"objects","bucket":"sky-ingest","prefix":"2026/04/","limit":50}',
        )
    fake.list_objects_v2.assert_called_once()
    call_kwargs = fake.list_objects_v2.call_args.kwargs
    assert call_kwargs["Bucket"] == "sky-ingest"
    assert call_kwargs["Prefix"] == "2026/04/"
    assert call_kwargs["MaxKeys"] == 50
    assert len(rows) == 2
    assert rows[0]["bucket"] == "sky-ingest"
    assert rows[0]["key"] == "2026/04/24/event-1.json"
    # ETag quotes stripped.
    assert rows[0]["etag"] == "abc123"


@pytest.mark.asyncio
async def test_execute_query_objects_requires_bucket():
    conn = S3Connector()
    with patch("src.connectors.s3._build_client", return_value=_fake_client()):
        with pytest.raises(ValueError, match="bucket"):
            await conn.execute_query(_config(), '{"object_type":"objects"}')


@pytest.mark.asyncio
async def test_execute_query_unknown_object_type_raises():
    conn = S3Connector()
    with patch("src.connectors.s3._build_client", return_value=_fake_client()):
        with pytest.raises(ValueError, match="Unknown S3 object_type"):
            await conn.execute_query(_config(), "blocks")


@pytest.mark.asyncio
async def test_execute_query_invalid_json_raises_value_error():
    conn = S3Connector()
    with pytest.raises(ValueError, match="Invalid S3 query JSON"):
        await conn.execute_query(_config(), '{"object_type":"objects",')


@pytest.mark.asyncio
async def test_objects_limit_clamped_to_1000():
    conn = S3Connector()
    fake = _fake_client(list_objects_v2={"Contents": []})
    with patch("src.connectors.s3._build_client", return_value=fake):
        await conn.execute_query(
            _config(),
            '{"object_type":"objects","bucket":"x","limit":99999}',
        )
    assert fake.list_objects_v2.call_args.kwargs["MaxKeys"] == 1000


@pytest.mark.asyncio
async def test_sync_data_returns_rows_by_object():
    conn = S3Connector()
    fake = _fake_client(
        list_buckets={"Buckets": [{"Name": "a"}, {"Name": "b"}]},
        list_objects_v2={"Contents": [{"Key": "x"}]},
    )
    config = _config(objects=[
        {"name": "buckets", "object_type": "buckets"},
        {"name": "logs", "object_type": "objects", "bucket": "sky-logs", "prefix": "2026/"},
    ])
    with patch("src.connectors.s3._build_client", return_value=fake):
        result = await conn.sync_data(config)
    assert result["success"] is True
    assert result["rows_by_object"]["buckets"] == 2
    assert result["rows_by_object"]["logs"] == 1


@pytest.mark.asyncio
async def test_continuation_token_passed_through():
    conn = S3Connector()
    fake = _fake_client(list_objects_v2={"Contents": []})
    with patch("src.connectors.s3._build_client", return_value=fake):
        await conn.execute_query(
            _config(),
            '{"object_type":"objects","bucket":"x","cursor":"abc-token"}',
        )
    assert fake.list_objects_v2.call_args.kwargs["ContinuationToken"] == "abc-token"
