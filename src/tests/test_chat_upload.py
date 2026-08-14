"""Chat attachment upload + text extraction.

Covers POST /ai/chat/upload (the "+" attach in mobile chat) and the
best-effort extractor behind it. The chat-stream injection of the
extracted text is exercised end-to-end against the live engine, not here.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.api.v1.ai import MAX_CHAT_ATTACHMENTS, attachment_ids
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


def test_extract_image_yields_nothing():
    """A photo must extract to "", not to the stray characters that survive a
    UTF-8 decode of JPEG bytes — those were reaching the model as "the
    document the user attached"."""
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + bytes(range(256)) * 4
    assert extract_text("foto.jpg", "image/jpeg", jpeg) == ""


def test_extract_image_without_a_content_type():
    # Some pickers hand us no MIME type at all; the extension still gives it away.
    assert extract_text("scan.png", None, b"\x89PNG\r\n\x1a\n" + bytes(range(256))) == ""


def test_extract_zip_container_yields_nothing():
    # .xlsx/.pptx are zips — decoding them as text produced pure noise.
    assert extract_text("plano.xlsx", None, b"PK\x03\x04" + bytes(range(256))) == ""


def test_extract_keeps_accented_text():
    # The binary guard must not mistake ordinary Portuguese for binary.
    text = "Relatório de vendas — Março. Ação concluída."
    assert extract_text("relatorio.txt", "text/plain", text.encode()) == text


# ─── Which attachments a chat message carries ────────────────────────────────
def test_attachment_ids_reads_the_list():
    assert attachment_ids({"file_ids": ["a", "b"]}) == ["a", "b"]


def test_attachment_ids_still_reads_the_single_field():
    # An older client only knows file_id; it must keep grounding on it.
    assert attachment_ids({"file_id": "a"}) == ["a"]


def test_attachment_ids_prefers_the_list_when_both_are_sent():
    # Mobile sends both so an older backend gets one document instead of none;
    # here the list wins, and the duplicated first id doesn't count twice.
    assert attachment_ids({"file_ids": ["a", "b"], "file_id": "a"}) == ["a", "b"]


def test_attachment_ids_drops_duplicates():
    assert attachment_ids({"file_ids": ["a", "a", "b"]}) == ["a", "b"]


def test_attachment_ids_caps_the_count():
    many = [str(i) for i in range(10)]
    assert len(attachment_ids({"file_ids": many})) == MAX_CHAT_ATTACHMENTS


def test_attachment_ids_survives_rubbish():
    assert attachment_ids(None) == []
    assert attachment_ids({}) == []
    assert attachment_ids({"file_ids": [None, "", "a"]}) == ["a"]


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
