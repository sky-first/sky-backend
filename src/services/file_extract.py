"""Best-effort text extraction for chat attachments.

Turns an uploaded document into plain text so it can be handed to the AI
engine as context. Supports PDF (PyMuPDF), DOCX (python-docx) and any
UTF-8-decodable text/CSV/Markdown/JSON. Unknown or binary formats yield
"" — the caller then simply has no file context rather than erroring.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# Cap the extracted text so a huge upload can't blow up the DB row or the
# LLM prompt. ~200k chars ≈ 50k tokens — plenty for a document Q&A.
MAX_CHARS = 200_000


def extract_text(filename: str | None, content_type: str | None, data: bytes) -> str:
    """Extract plain text from ``data``. Never raises — returns "" on failure."""
    name = (filename or "").lower()
    ct = (content_type or "").lower()

    try:
        if name.endswith(".pdf") or "pdf" in ct:
            return _from_pdf(data)[:MAX_CHARS]
        if name.endswith(".docx") or "wordprocessingml" in ct:
            return _from_docx(data)[:MAX_CHARS]
        if _is_binary(name, ct, data):
            return ""
        # txt / csv / md / json / tsv / log … anything UTF-8-decodable.
        return data.decode("utf-8", errors="ignore")[:MAX_CHARS]
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        logger.warning("file_extract failed for %r (%s): %s", filename, ct, exc)
        return ""


_BINARY_TYPES = ("image/", "audio/", "video/", "font/")
_BINARY_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif", ".webp", ".bmp", ".tiff",
    ".mp3", ".mp4", ".mov", ".wav", ".m4a", ".zip", ".gz", ".xlsx", ".pptx",
)


def _is_binary(name: str, content_type: str, data: bytes) -> bool:
    """Is this something we'd only turn into garbage by decoding it as text?

    ``bytes.decode(errors="ignore")`` never fails — it just throws away every
    byte it can't read. On a photo that leaves a page of stray characters, and
    that page was being handed to the model as "the document the user
    attached". The model then answers about nothing, confidently.

    Better to extract nothing: the caller reports the file as unreadable and
    the user attaches something we can actually read. (Reading images means
    OCR or a vision model — neither is wired up yet.)
    """
    if content_type.startswith(_BINARY_TYPES):
        return True
    if name.endswith(_BINARY_EXTENSIONS):
        return True
    # No usable name or type — judge by the bytes. A NUL byte doesn't occur in
    # UTF-8 text; a high share of undecodable bytes means it isn't text either.
    head = data[:4096]
    if b"\x00" in head:
        return True
    if not head:
        return False
    lost = sum(1 for b in head.decode("utf-8", errors="replace") if b == "�")
    return lost > len(head) * 0.1


def _from_pdf(data: bytes) -> str:
    import fitz  # PyMuPDF

    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc).strip()


def _from_docx(data: bytes) -> str:
    import docx  # python-docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs).strip()
