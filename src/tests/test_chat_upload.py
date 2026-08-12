"""Chat attachment upload + text extraction.

Covers POST /ai/chat/upload (the "+" attach in mobile chat) and the
best-effort extractor behind it. The chat-stream injection of the
extracted text is exercised end-to-end against the live engine, not here.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.services.file_extract import extract_text


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Extractor unit tests ────────────────────────────────────────────────────
def test_extract_plain_text():
    assert extract_text("notes.txt", "text/plain", b"374 clients in Q3") == "374 clients in Q3"


def test_extract_pdf():
    import fitz  # PyMuPDF — available in the backend venv

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sky reads PDFs")
    data = doc.tobytes()
    out = extract_text("report.pdf", "application/pdf", data)
    assert "Sky reads PDFs" in out


def test_extract_unknown_binary_never_raises():
    out = extract_text("blob.bin", "application/octet-stream", b"\xff\xfe\x00\x01")
    assert isinstance(out, str)  # best-effort — returns a (possibly empty) string


# ─── Endpoint tests ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_upload_txt_returns_file_id_and_extracts(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    content = b"Revenue was up. We now have 374 clients."
    resp = await async_client.post(
        "/api/v1/ai/chat/upload",
        headers=_auth(test_user_with_tokens["access_token"]),
        files={"file": ("q3.txt", content, "text/plain")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["file_id"]
    assert body["filename"] == "q3.txt"
    assert body["extracted"] is True
    assert body["chars"] == len(content.decode())


@pytest.mark.asyncio
async def test_upload_requires_auth(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/v1/ai/chat/upload",
        files={"file": ("x.txt", b"hi", "text/plain")},
    )
    assert resp.status_code == 401
