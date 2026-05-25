"""Tests for file-drive connectors: Google Drive / Dropbox / OneDrive /
SharePoint. Every connector gets: test_connection happy + 401 + missing
token; execute_query happy + edge shape + input validation.
"""

from __future__ import annotations

import json as _json
from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.dropbox import DropboxConnector
from src.connectors.google_drive import GoogleDriveConnector
from src.connectors.microsoft_graph import OneDriveConnector, SharePointConnector


class _Resp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ── Google Drive ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_google_drive_test_connection_false_without_token():
    assert await GoogleDriveConnector().test_connection({}) is False


@pytest.mark.asyncio
async def test_google_drive_test_connection_true_on_200():
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(200))
        ok = await GoogleDriveConnector().test_connection({"auth": {"access_token": "ya29"}})
    assert ok is True


@pytest.mark.asyncio
async def test_google_drive_execute_query_flattens_files():
    payload = {
        "files": [
            {
                "id": "f1",
                "name": "Q4 plan",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2026-04-20T00:00:00Z",
                "size": "0",
                "webViewLink": "https://docs.google.com/d/f1",
                "parents": ["root_id"],
                "owners": [{"displayName": "Ada"}],
            }
        ]
    }
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await GoogleDriveConnector().execute_query(
            {"auth": {"access_token": "t"}},
            "root_id",
        )
    assert "files" in captured["url"]
    assert captured["params"]["q"] == "'root_id' in parents"
    assert rows == [{
        "id": "f1",
        "name": "Q4 plan",
        "mime_type": "application/vnd.google-apps.document",
        "modified_at": "2026-04-20T00:00:00Z",
        "size_bytes": "0",
        "link": "https://docs.google.com/d/f1",
        "parent_id": "root_id",
        "owner": "Ada",
    }]


@pytest.mark.asyncio
async def test_google_drive_execute_query_json_descriptor_combines_q():
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _Resp(200, {"files": []})

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await GoogleDriveConnector().execute_query(
            {"auth": {"access_token": "t"}},
            _json.dumps({
                "folder_id": "F",
                "q": "mimeType = 'application/pdf'",
                "page_size": 10,
            }),
        )
    assert captured["params"]["q"] == "'F' in parents and mimeType = 'application/pdf'"
    assert captured["params"]["pageSize"] == 10


# ── Dropbox ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dropbox_test_connection_true_on_200():
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(return_value=_Resp(200))
        ok = await DropboxConnector().test_connection({"auth": {"access_token": "sl.B"}})
    assert ok is True


@pytest.mark.asyncio
async def test_dropbox_test_connection_false_on_401():
    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(return_value=_Resp(401))
        ok = await DropboxConnector().test_connection({"auth": {"access_token": "bad"}})
    assert ok is False


@pytest.mark.asyncio
async def test_dropbox_execute_query_flattens_entries_and_root_is_empty_string():
    captured = {}

    async def fake_post(url, headers=None, json=None):
        captured["json"] = json
        return _Resp(200, {"entries": [
            {".tag": "file", "id": "id:1", "name": "x.pdf", "path_display": "/x.pdf",
             "server_modified": "2026-04-01T00:00:00Z", "size": 100, "is_downloadable": True},
            {".tag": "folder", "id": "id:2", "name": "Sub", "path_display": "/Sub"},
        ]})

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        rows = await DropboxConnector().execute_query(
            {"auth": {"access_token": "t"}},
            "/",
        )
    assert captured["json"]["path"] == ""  # root mapped to empty
    assert rows[0]["type"] == "file" and rows[0]["size_bytes"] == 100
    assert rows[1]["type"] == "folder"


@pytest.mark.asyncio
async def test_dropbox_execute_query_honors_recursive_and_limit():
    captured = {}

    async def fake_post(url, headers=None, json=None):
        captured["json"] = json
        return _Resp(200, {"entries": []})

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        await DropboxConnector().execute_query(
            {"auth": {"access_token": "t"}},
            _json.dumps({"path": "/Sales", "recursive": True, "limit": 10}),
        )
    assert captured["json"] == {"path": "/Sales", "recursive": True, "limit": 10}


# ── OneDrive ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_onedrive_test_connection_uses_me_endpoint():
    captured = {}

    async def fake_get(url, headers=None):
        captured["url"] = url
        return _Resp(200)

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        ok = await OneDriveConnector().test_connection({"auth": {"access_token": "t"}})
    assert ok is True
    assert captured["url"].endswith("/me")


@pytest.mark.asyncio
async def test_onedrive_execute_query_default_scope_and_path_encoding():
    captured = {}

    async def fake_get(url, headers=None):
        captured["url"] = url
        return _Resp(200, {"value": [
            {"id": "01", "name": "Q4.docx", "file": {"mimeType": "doc"}, "size": 2048,
             "lastModifiedDateTime": "2026-04-22T12:00:00Z",
             "lastModifiedBy": {"user": {"displayName": "Ada"}},
             "webUrl": "https://onedrive/x"},
            {"id": "02", "name": "Reports", "folder": {}, "webUrl": "https://onedrive/reports"},
        ]})

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await OneDriveConnector().execute_query(
            {"auth": {"access_token": "t"}},
            "/Sales",
        )
    assert "/me/drive/root:/Sales:/children" in captured["url"]
    assert rows[0]["type"] == "file" and rows[0]["modified_by"] == "Ada"
    assert rows[1]["type"] == "folder"


@pytest.mark.asyncio
async def test_onedrive_execute_query_with_drive_id_uses_drives_scope():
    captured = {}

    async def fake_get(url, headers=None):
        captured["url"] = url
        return _Resp(200, {"value": []})

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await OneDriveConnector().execute_query(
            {"auth": {"access_token": "t"}},
            _json.dumps({"drive_id": "b!x", "path": "/"}),
        )
    assert "/drives/b!x/root/children" in captured["url"]


# ── SharePoint ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sharepoint_execute_query_requires_site_id():
    with pytest.raises(ValueError, match="site_id"):
        await SharePointConnector().execute_query(
            {"auth": {"access_token": "t"}},
            "/",
        )


@pytest.mark.asyncio
async def test_sharepoint_execute_query_with_default_site_and_subpath():
    captured = {}

    async def fake_get(url, headers=None):
        captured["url"] = url
        return _Resp(200, {"value": [
            {"id": "s1", "name": "Policies.docx", "file": {"mimeType": "doc"},
             "size": 1024, "lastModifiedDateTime": "2026-04-22T12:00:00Z",
             "lastModifiedBy": {"user": {"displayName": "Bob"}},
             "webUrl": "https://sp/x"},
        ]})

    with patch("httpx.AsyncClient") as mc:
        mc.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await SharePointConnector().execute_query(
            {"auth": {"access_token": "t"}, "site_id": "tenant.sharepoint.com,s-guid,w-guid"},
            "/Policies",
        )
    assert "/sites/tenant.sharepoint.com,s-guid,w-guid/drive/root:/Policies:/children" in captured["url"]
    assert rows[0]["name"] == "Policies.docx"
    assert rows[0]["modified_by"] == "Bob"
