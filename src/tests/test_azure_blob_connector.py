"""Tests for src/connectors/azure_blob.py — Azure Blob as read-only tabular source."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.azure_blob import AzureBlobConnector


def _config(**overrides):
    base = {
        "account_name": "skyingest",
        "account_key": "fake-key==",
    }
    base.update(overrides)
    return base


def _fake_container(name, etag='"abc"', last_modified=None, public_access=None):
    c = MagicMock()
    c.name = name
    c.etag = etag
    c.last_modified = last_modified or datetime(2026, 1, 1, tzinfo=timezone.utc)
    c.public_access = public_access
    c.lease = MagicMock(state="available")
    return c


def _fake_blob(name, size=100, content_type="application/json", last_modified=None,
               etag='"def"', blob_tier="Hot"):
    b = MagicMock()
    b.name = name
    b.size = size
    cs = MagicMock()
    cs.content_type = content_type
    b.content_settings = cs
    b.last_modified = last_modified or datetime(2026, 4, 24, tzinfo=timezone.utc)
    b.etag = etag
    b.blob_tier = blob_tier
    return b


@pytest.mark.asyncio
async def test_test_connection_true_when_list_containers_succeeds():
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    fake_client.list_containers.return_value = iter([_fake_container("a")])
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        ok = await conn.test_connection(_config())
    assert ok is True
    fake_client.list_containers.assert_called_once()
    assert fake_client.list_containers.call_args.kwargs == {"results_per_page": 1}


@pytest.mark.asyncio
async def test_test_connection_false_on_exception():
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    fake_client.list_containers.side_effect = Exception("AuthenticationFailed")
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        ok = await conn.test_connection(_config())
    assert ok is False


@pytest.mark.asyncio
async def test_get_metadata_exposes_declared_objects_as_tables():
    conn = AzureBlobConnector()
    config = _config(objects=[
        {"name": "ingest", "object_type": "blobs", "container": "events", "prefix": "2026/04/"},
        {"name": "all_containers", "object_type": "containers"},
    ])
    meta = await conn.get_metadata(config)
    names = [t["name"] for t in meta["tables"]]
    assert names == ["ingest", "all_containers"]
    assert meta["tables"][0]["metadata"]["container"] == "events"
    assert meta["tables"][0]["metadata"]["prefix"] == "2026/04/"
    assert meta["tables"][0]["kind"] == "azure_blob_object"
    cols = [c["name"] for c in meta["tables"][0]["columns"]]
    assert "name" in cols and "size" in cols and "blob_tier" in cols


@pytest.mark.asyncio
async def test_execute_query_containers_returns_flattened_rows():
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    fake_client.list_containers.return_value = iter([
        _fake_container("events"),
        _fake_container("logs", public_access="blob"),
    ])
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        rows = await conn.execute_query(_config(), "containers")
    assert len(rows) == 2
    assert rows[0]["name"] == "events"
    assert rows[1]["public_access"] == "blob"
    # Lease state surfaces on the row.
    assert rows[0]["lease_state"] == "available"
    assert rows[0]["last_modified"].startswith("2026-01-01")


@pytest.mark.asyncio
async def test_execute_query_empty_string_defaults_to_containers():
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    fake_client.list_containers.return_value = iter([])
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        await conn.execute_query(_config(), "")
    fake_client.list_containers.assert_called_once()


@pytest.mark.asyncio
async def test_execute_query_blobs_lists_with_prefix_and_limit():
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    container_client = MagicMock()
    fake_client.get_container_client.return_value = container_client
    container_client.list_blobs.return_value = iter([
        _fake_blob("2026/04/24/event-1.json", size=1234),
        _fake_blob("2026/04/24/event-2.json", size=5678),
    ])
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"blobs","container":"events","prefix":"2026/04/","limit":50}',
        )
    fake_client.get_container_client.assert_called_once_with("events")
    container_client.list_blobs.assert_called_once()
    kwargs = container_client.list_blobs.call_args.kwargs
    assert kwargs["name_starts_with"] == "2026/04/"
    assert kwargs["results_per_page"] == 50
    assert len(rows) == 2
    assert rows[0]["container"] == "events"
    assert rows[0]["name"] == "2026/04/24/event-1.json"
    assert rows[0]["content_type"] == "application/json"


@pytest.mark.asyncio
async def test_execute_query_blobs_requires_container():
    conn = AzureBlobConnector()
    with patch("src.connectors.azure_blob._build_client", return_value=MagicMock()):
        with pytest.raises(ValueError, match="container"):
            await conn.execute_query(_config(), '{"object_type":"blobs"}')


@pytest.mark.asyncio
async def test_execute_query_unknown_object_type_raises():
    conn = AzureBlobConnector()
    with patch("src.connectors.azure_blob._build_client", return_value=MagicMock()):
        with pytest.raises(ValueError, match="Unknown Azure Blob object_type"):
            await conn.execute_query(_config(), "files")


@pytest.mark.asyncio
async def test_execute_query_invalid_json_raises_value_error():
    conn = AzureBlobConnector()
    with pytest.raises(ValueError, match="Invalid Azure Blob query JSON"):
        await conn.execute_query(_config(), '{"object_type":"blobs",')


@pytest.mark.asyncio
async def test_blobs_limit_clamped_to_5000():
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    container_client = MagicMock()
    fake_client.get_container_client.return_value = container_client
    container_client.list_blobs.return_value = iter([])
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        await conn.execute_query(
            _config(),
            '{"object_type":"blobs","container":"x","limit":99999}',
        )
    assert container_client.list_blobs.call_args.kwargs["results_per_page"] == 5000


@pytest.mark.asyncio
async def test_limit_caps_total_rows_returned_not_just_page_size():
    """results_per_page only sets the page size; we still need to stop
    at the user-requested ``limit``. Otherwise an unbounded iterator
    would dump the entire container even if the user asked for 10."""
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    container_client = MagicMock()
    fake_client.get_container_client.return_value = container_client
    container_client.list_blobs.return_value = iter([
        _fake_blob(f"blob-{i}") for i in range(50)
    ])
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"blobs","container":"x","limit":10}',
        )
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_sync_data_returns_rows_by_object():
    conn = AzureBlobConnector()
    fake_client = MagicMock()
    fake_client.list_containers.return_value = iter([
        _fake_container("a"), _fake_container("b")
    ])
    container_client = MagicMock()
    fake_client.get_container_client.return_value = container_client
    container_client.list_blobs.return_value = iter([_fake_blob("x.json")])
    config = _config(objects=[
        {"name": "containers", "object_type": "containers"},
        {"name": "logs", "object_type": "blobs", "container": "events", "prefix": "2026/"},
    ])
    with patch("src.connectors.azure_blob._build_client", return_value=fake_client):
        result = await conn.sync_data(config)
    assert result["success"] is True
    assert result["rows_by_object"]["containers"] == 2
    assert result["rows_by_object"]["logs"] == 1


@pytest.mark.asyncio
async def test_build_client_uses_connection_string_when_provided():
    """Connection string takes precedence over account_name/key path."""
    conn = AzureBlobConnector()
    config = {"connection_string": "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=y"}
    with patch("src.connectors.azure_blob._import_azure") as mock_imp:
        BlobSvc = MagicMock()
        BlobSvc.from_connection_string.return_value = MagicMock()
        mock_imp.return_value = BlobSvc
        from src.connectors.azure_blob import _build_client
        _build_client(config)
    BlobSvc.from_connection_string.assert_called_once()


def test_build_client_raises_when_no_credentials():
    """Refuses to construct an unauthenticated client — fails fast at
    config time rather than letting a 401 surface from the first list."""
    conn = AzureBlobConnector()  # noqa: F841
    from src.connectors.azure_blob import _build_client
    with patch("src.connectors.azure_blob._import_azure") as mock_imp:
        mock_imp.return_value = MagicMock()
        with pytest.raises(ValueError, match="account_name"):
            _build_client({})


def test_build_client_supports_sas_token_with_or_without_leading_question_mark():
    from src.connectors.azure_blob import _build_client
    with patch("src.connectors.azure_blob._import_azure") as mock_imp:
        BlobSvc = MagicMock()
        mock_imp.return_value = BlobSvc

        # With "?".
        _build_client({"account_name": "x", "sas_token": "?sv=1&sig=abc"})
        first_url = BlobSvc.call_args.kwargs.get("account_url") or BlobSvc.call_args.args[0]
        assert "?sv=1&sig=abc" in first_url
        # No double "?".
        assert first_url.count("?") == 1

        BlobSvc.reset_mock()
        # Without "?".
        _build_client({"account_name": "x", "sas_token": "sv=1&sig=abc"})
        second_url = BlobSvc.call_args.kwargs.get("account_url") or BlobSvc.call_args.args[0]
        assert "?sv=1&sig=abc" in second_url
        assert second_url.count("?") == 1
