"""BE-08 · Sky Mobile chat SSE contract — single source of truth.

The backend is a *normalizing gateway* for POST /ai/chat/stream: whatever the
AI engine emits internally, only the locked event types below ever reach a
client, always in a stable shape. Undocumented or debug engine events
(``sql_generated``, ``datasets_selected``, the engine's own ``done`` …) are
dropped here, so the mobile app can depend on this contract without coupling
to engine internals — and a future engine rename can't silently break mobile.

Locked client event types (each is a ``data: {...}`` SSE frame with ``type``)
----------------------------------------------------------------------------
- ``progress`` ``{stage: str, message: str}``     pipeline stage (spinner/label)
- ``chunk``    ``{content: str}``                  a piece of the answer, streaming
- ``meta``     ``{meta: dict, data_sample: list}`` post-answer metadata (charts, lang…)
- ``error``    ``{message: str}``                  failure; the stream ends after it
- ``done``     ``{}``                              terminal marker; nothing follows

Names are kept web-safe: the existing web client already consumes
``progress``/``chunk``/``meta``/``done``/``error``, so nothing there breaks.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional

# ─── Locked, client-facing event types (the contract) ───────────────────────
EVENT_PROGRESS = "progress"
EVENT_CHUNK = "chunk"
EVENT_META = "meta"
EVENT_ERROR = "error"
EVENT_DONE = "done"

CLIENT_EVENT_TYPES = frozenset({EVENT_PROGRESS, EVENT_CHUNK, EVENT_META, EVENT_ERROR, EVENT_DONE})

# Heartbeat — carrier/NAT timeouts reap idle SSE sockets on mobile networks.
# A line starting with ':' is an SSE comment (ignored by every compliant
# client), so it keeps the socket warm without polluting the event contract.
HEARTBEAT_COMMENT = ": keepalive\n\n"
HEARTBEAT_INTERVAL_SECONDS = 15


# ─── Frame builders (the only place client events are constructed) ──────────
def sse(event: Dict[str, Any]) -> str:
    """Serialize a locked event dict as an SSE ``data:`` frame."""
    return f"data: {json.dumps(event)}\n\n"


def progress_event(stage: str, message: str = "") -> Dict[str, Any]:
    return {"type": EVENT_PROGRESS, "stage": stage, "message": message}


def chunk_event(content: str) -> Dict[str, Any]:
    return {"type": EVENT_CHUNK, "content": content}


# BE-08 (T-08.2) — the locked citation shape. When the engine surfaces sources
# in a meta event, every citation is projected onto exactly these keys so the
# mobile client can rely on the shape regardless of what the engine adds.
_CITATION_FIELDS = (
    "file_id",
    "file_name",
    "chunk_index",
    "page_number",
    "excerpt",
    "score",
)


def normalize_citations(raw: Any) -> list:
    """Project each citation onto the locked field set; drop non-dict entries."""
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        if isinstance(c, dict):
            out.append({k: c.get(k) for k in _CITATION_FIELDS})
    return out


def meta_event(meta: Optional[dict] = None, data_sample: Optional[list] = None) -> Dict[str, Any]:
    meta = dict(meta or {})
    # Lock the citations sub-shape if the engine included any (T-08.2). Other
    # meta fields (language, transparency, …) pass through unchanged.
    if "citations" in meta:
        meta["citations"] = normalize_citations(meta.get("citations"))
    return {"type": EVENT_META, "meta": meta, "data_sample": data_sample or []}


def error_event(message: str, code: str = "stream_error") -> Dict[str, Any]:
    # BE-08 (T-08.5) — errors always carry a machine-readable ``code`` so the
    # client can branch without string-matching the human message.
    return {"type": EVENT_ERROR, "message": message, "code": code}


def done_event() -> Dict[str, Any]:
    return {"type": EVENT_DONE}


# ─── Upstream parsing + normalization ───────────────────────────────────────
def parse_sse_data_line(line: str) -> Optional[Dict[str, Any]]:
    """Extract the JSON object from a raw upstream ``data: {...}`` SSE line.

    Returns ``None`` for comments, blanks, non-JSON payloads, or JSON that
    isn't an object — the caller treats those as nothing to forward.
    """
    if not line:
        return None
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):  # blank or SSE comment
        return None
    if stripped.startswith("data:"):
        stripped = stripped[len("data:") :].strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def normalize_event(raw: Any) -> Optional[Dict[str, Any]]:
    """Map one raw AI-engine event onto the locked client contract.

    Returns the client-facing event dict, or ``None`` when the event must be
    dropped: the engine's own terminal ``done`` (the endpoint owns the single
    ``done``), debug events (``sql_generated``, ``datasets_selected``),
    unknown types, or malformed input.
    """
    if not isinstance(raw, dict):
        return None
    etype = raw.get("type")
    if etype == EVENT_PROGRESS:
        return progress_event(str(raw.get("stage", "")), str(raw.get("message", "")))
    if etype == EVENT_CHUNK:
        return chunk_event(str(raw.get("content", "")))
    if etype == "answer":  # engine's full-answer variant → fold into chunk
        return chunk_event(str(raw.get("text", "")))
    if etype == EVENT_META:
        return meta_event(raw.get("meta"), raw.get("data_sample"))
    if etype == EVENT_ERROR:
        return error_event(str(raw.get("message", "")), str(raw.get("code") or "stream_error"))
    # done / datasets_selected / sql_generated / anything unknown → dropped
    return None


# ─── Heartbeat wrapper ──────────────────────────────────────────────────────
async def with_heartbeat(
    source: AsyncIterator[str],
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Yield from an SSE string generator, injecting a heartbeat comment
    whenever ``interval_seconds`` pass with no upstream event.

    Keeps idle mobile SSE connections alive without touching the event
    contract (heartbeats are SSE comments). ``shield`` keeps the pending
    upstream item alive across a heartbeat timeout so nothing is lost.

    On abort (the client disconnects → GeneratorExit) or normal end, the
    upstream source is closed and any pending read cancelled, so no worker /
    generator leaks behind a dropped connection (BE-08 T-08.4).
    """
    agen = source.__aiter__()
    nxt = None
    try:
        while True:
            nxt = asyncio.ensure_future(agen.__anext__())
            while True:
                try:
                    item = await asyncio.wait_for(asyncio.shield(nxt), timeout=interval_seconds)
                    break
                except asyncio.TimeoutError:
                    yield HEARTBEAT_COMMENT
                    continue
                except StopAsyncIteration:
                    return
            yield item
    finally:
        if nxt is not None and not nxt.done():
            nxt.cancel()
        aclose = getattr(agen, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                pass
