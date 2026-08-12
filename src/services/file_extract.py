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
        # txt / csv / md / json / tsv / log … anything UTF-8-decodable.
        return data.decode("utf-8", errors="ignore")[:MAX_CHARS]
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        logger.warning("file_extract failed for %r (%s): %s", filename, ct, exc)
        return ""


def _from_pdf(data: bytes) -> str:
    import fitz  # PyMuPDF

    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc).strip()


def _from_docx(data: bytes) -> str:
    import docx  # python-docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs).strip()
