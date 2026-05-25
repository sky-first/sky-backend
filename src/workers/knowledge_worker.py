"""Knowledge Library Celery tasks.

process_file_for_context — PDF/TXT/DOCX/CSV parsing + chunking + embedding.
delete_file_and_chunks   — cleanup on file deletion.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Tuple

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# ── Chunking config ───────────────────────────────────────────────────────────
_CHUNK_TOKENS = 500
_OVERLAP_TOKENS = 50
_TIKTOKEN_ENCODING = "cl100k_base"  # works for both GPT-4 and nomic-embed-text


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_pdf(data: bytes) -> List[Tuple[str, int]]:
    """Return list of (text, page_number) using PyMuPDF."""
    import fitz  # pymupdf

    pages: List[Tuple[str, int]] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append((text, i))
    return pages


def _extract_docx(data: bytes) -> List[Tuple[str, int]]:
    from docx import Document

    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(text, 1)] if text else []


def _extract_csv(data: bytes) -> List[Tuple[str, int]]:
    text_lines = []
    reader = csv.reader(io.StringIO(data.decode("utf-8", errors="replace")))
    for row in reader:
        line = " | ".join(cell.strip() for cell in row if cell.strip())
        if line:
            text_lines.append(line)
    return [("\n".join(text_lines), 1)] if text_lines else []


def _extract_text(data: bytes) -> List[Tuple[str, int]]:
    return [(data.decode("utf-8", errors="replace").strip(), 1)]


def _extract(mime_type: str, data: bytes) -> List[Tuple[str, int]]:
    if mime_type == "application/pdf":
        return _extract_pdf(data)
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx(data)
    if mime_type in ("text/csv", "application/vnd.ms-excel"):
        return _extract_csv(data)
    return _extract_text(data)


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str, page_number: int) -> List[Tuple[str, int, int]]:
    """Yield (chunk_text, chunk_index, page_number) using tiktoken."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding(_TIKTOKEN_ENCODING)
        tokens = enc.encode(text)
        step = _CHUNK_TOKENS - _OVERLAP_TOKENS
        chunks = []
        idx = 0
        i = 0
        while i < len(tokens):
            window = tokens[i: i + _CHUNK_TOKENS]
            chunk_text = enc.decode(window).strip()
            if chunk_text:
                chunks.append((chunk_text, idx, page_number))
                idx += 1
            i += step
        return chunks
    except Exception:
        # Fallback: character-based (~4 chars per token)
        char_size = _CHUNK_TOKENS * 4
        overlap = _OVERLAP_TOKENS * 4
        step = char_size - overlap
        chunks = []
        idx = 0
        i = 0
        while i < len(text):
            piece = text[i: i + char_size].strip()
            if piece:
                chunks.append((piece, idx, page_number))
                idx += 1
            i += step
        return chunks


# ── Embedding via AI service ──────────────────────────────────────────────────

async def _embed_batch(texts: List[str], ai_service_url: str) -> List[List[float]]:
    import httpx

    url = f"{ai_service_url.rstrip('/')}/embeddings/batch"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json={"texts": texts})
        resp.raise_for_status()
        return resp.json()["embeddings"]


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def _process(file_id: str) -> None:
    from sqlalchemy import select, update

    from src.azure.blob_helper import download_blob_stream
    from src.config.database import AsyncSessionLocal
    from src.config.settings import settings
    from src.models.knowledge import KnowledgeFile, KnowledgeFileChunk

    ai_url = getattr(settings, "AI_SERVICE_URL", "http://localhost:8001")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(KnowledgeFile).where(KnowledgeFile.id == uuid.UUID(file_id))
        )
        file = result.scalar_one_or_none()
        if not file or file.deleted_at:
            logger.warning("knowledge.process_file: file %s not found or deleted", file_id)
            return

        try:
            # 1. Download blob into memory
            chunks_bytes = []
            async for chunk in download_blob_stream(file.blob_path):
                chunks_bytes.append(chunk)
            data = b"".join(chunks_bytes)

            # 2. Extract text segments (list of (text, page_number))
            segments = _extract(file.mime_type, data)
            if not segments:
                raise ValueError("No extractable text found in file.")

            # 3. Chunk each segment
            all_chunks: List[Tuple[str, int, int]] = []
            for text, page_num in segments:
                all_chunks.extend(_chunk_text(text, page_num))

            if not all_chunks:
                raise ValueError("File produced zero chunks after splitting.")

            # 4. Embed in batches of 32
            batch_size = 32
            all_embeddings: List[List[float]] = []
            for i in range(0, len(all_chunks), batch_size):
                batch_texts = [c[0] for c in all_chunks[i: i + batch_size]]
                vecs = await _embed_batch(batch_texts, ai_url)
                all_embeddings.extend(vecs)
                logger.info(
                    "knowledge.process_file: embedded %d/%d chunks for %s",
                    min(i + batch_size, len(all_chunks)),
                    len(all_chunks),
                    file_id,
                )

            # 5. Bulk insert chunks (replace any previous processing attempt)
            from sqlalchemy import delete
            await db.execute(
                delete(KnowledgeFileChunk).where(KnowledgeFileChunk.file_id == uuid.UUID(file_id))
            )

            now = datetime.now(timezone.utc)
            for (chunk_text, chunk_index, page_number), embedding in zip(all_chunks, all_embeddings):
                db.add(KnowledgeFileChunk(
                    id=uuid.uuid4(),
                    file_id=uuid.UUID(file_id),
                    chunk_index=chunk_index,
                    page_number=page_number,
                    text=chunk_text,
                    embedding=embedding,
                    created_at=now,
                ))

            # 6. Mark file ready
            await db.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == uuid.UUID(file_id))
                .values(
                    status="ready",
                    chunks_count=len(all_chunks),
                    processing_error=None,
                    updated_at=now,
                )
            )
            await db.commit()
            logger.info(
                "knowledge.process_file: %s ready — %d chunks", file_id, len(all_chunks)
            )

        except Exception as exc:
            logger.exception("knowledge.process_file: failed for %s", file_id)
            await db.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == uuid.UUID(file_id))
                .values(
                    status="error",
                    processing_error=str(exc)[:500],
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            raise


# ── Celery task wrappers ──────────────────────────────────────────────────────

@celery_app.task(
    name="knowledge.process_file",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    time_limit=300,
    soft_time_limit=270,
    queue="knowledge",
)
def process_file_for_context(self, file_id: str) -> None:
    """Parse, chunk, embed, and store knowledge file chunks."""
    try:
        asyncio.run(_process(file_id))
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(
    name="knowledge.delete_file",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    queue="knowledge",
)
def delete_file_and_chunks(self, file_id: str) -> None:
    """Remove chunks and blob on file deletion."""
    async def _cleanup() -> None:
        from sqlalchemy import delete, select

        from src.azure.blob_helper import delete_blob
        from src.config.database import AsyncSessionLocal
        from src.models.knowledge import KnowledgeFile, KnowledgeFileChunk

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(KnowledgeFile).where(KnowledgeFile.id == uuid.UUID(file_id))
            )
            file = result.scalar_one_or_none()

            await db.execute(
                delete(KnowledgeFileChunk).where(
                    KnowledgeFileChunk.file_id == uuid.UUID(file_id)
                )
            )

            if file and file.blob_path:
                try:
                    delete_blob(file.blob_path)
                except Exception:
                    pass

            await db.commit()

    try:
        asyncio.run(_cleanup())
        logger.info("knowledge.delete_file: cleaned up %s", file_id)
    except Exception as exc:
        logger.exception("knowledge.delete_file failed for %s", file_id)
        self.retry(exc=exc)
