"""Extract ``EvidenceChunkOut`` records from a Runpod AI response.

Master plan §8.1 + W7 follow-up. The AI engine on Runpod will populate
an ``evidence`` (or equivalent) field on its responses once the schema
ships there. Until then, our backend already speaks the structure —
this extractor recognises a handful of likely shapes so the moment
Runpod starts emitting them, evidence flows through to the frontend
without a backend deploy.

Recognised top-level keys (first match wins, case-insensitive):

  - ``evidence``      — preferred shape, list of dicts.
  - ``sources``       — common alternative, list of dicts or strings.
  - ``chunks``        — what some retrieval libs call them.
  - ``retrieved``     — RAG-pipeline naming.
  - ``citations``     — when the LLM is asked to cite via tool_use.

Per-chunk dicts may use any of these field names:

  - ``id`` | ``embedding_id`` | ``chunk_id`` | ``source_id``
  - ``kind`` | ``type``
  - ``source_label`` | ``label`` | ``title`` | ``name``
  - ``snippet`` | ``text`` | ``body`` | ``content``
  - ``score`` | ``similarity`` | ``relevance``
  - ``href`` | ``url`` | ``link``

Anything else is dropped silently. Pure function, no DB / network — safe
to call from any thread.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional

from src.schemas.ai_transparency import EvidenceChunkOut

_KEY_PRIORITY: tuple[str, ...] = (
    "evidence",
    "sources",
    "chunks",
    "retrieved",
    "citations",
)

_ID_KEYS = ("id", "embedding_id", "chunk_id", "source_id")
_KIND_KEYS = ("kind", "type")
_LABEL_KEYS = ("source_label", "label", "title", "name")
_SNIPPET_KEYS = ("snippet", "text", "body", "content", "preview")
_SCORE_KEYS = ("score", "similarity", "relevance")
_HREF_KEYS = ("href", "url", "link")
_SOURCE_ID_KEYS = ("source_row_id", "object_id", "row_id")

MAX_SNIPPET_CHARS = 400


def extract_evidence(payload: Optional[Mapping[str, Any]]) -> List[EvidenceChunkOut]:
    """Best-effort coercion of an AI engine response into our schema.

    Returns ``[]`` when ``payload`` is None, empty, or doesn't carry any
    recognised evidence container. Callers should treat empty as
    "nothing to show" — the W7 transparency UI already handles that
    case with a placeholder.
    """
    if not payload or not isinstance(payload, Mapping):
        return []

    raw = _find_evidence_container(payload)
    if not raw:
        return []

    out: List[EvidenceChunkOut] = []
    for item in raw:
        chunk = _coerce_chunk(item)
        if chunk is not None:
            out.append(chunk)
    return out


# ---------------------------------------------------------------------------
#  Internals
# ---------------------------------------------------------------------------


def _find_evidence_container(payload: Mapping[str, Any]) -> List[Any]:
    """Walk priority list of keys; return the first list-shaped value."""
    # Exact-key lookup first (cheap)
    for key in _KEY_PRIORITY:
        v = payload.get(key)
        if isinstance(v, list) and v:
            return v
    # Case-insensitive fallback
    lowered = {k.lower(): k for k in payload.keys() if isinstance(k, str)}
    for key in _KEY_PRIORITY:
        original = lowered.get(key)
        if original:
            v = payload.get(original)
            if isinstance(v, list) and v:
                return v

    # Some Runpod responses nest the evidence inside a metadata object.
    nested_keys = ("meta", "metadata", "trace", "trace_data")
    for nk in nested_keys:
        nv = payload.get(nk)
        if isinstance(nv, Mapping):
            inner = _find_evidence_container(nv)
            if inner:
                return inner
    return []


def _coerce_chunk(item: Any) -> Optional[EvidenceChunkOut]:
    """Map one raw element into EvidenceChunkOut — or drop it silently."""
    # Plain string — treat as snippet only.
    if isinstance(item, str):
        if not item.strip():
            return None
        return EvidenceChunkOut(
            id="",
            kind="unknown",
            source_label="(unlabelled)",
            snippet=_truncate(item),
        )

    if not isinstance(item, Mapping):
        return None

    snippet = _first_str(item, _SNIPPET_KEYS) or ""
    label = _first_str(item, _LABEL_KEYS) or "(unlabelled)"
    if not snippet and label == "(unlabelled)":
        # Nothing usable — drop silently rather than pollute the UI.
        return None

    cid = _first_str(item, _ID_KEYS) or ""
    kind = _first_str(item, _KIND_KEYS) or "unknown"
    href = _first_str(item, _HREF_KEYS)
    source_id = _first_str(item, _SOURCE_ID_KEYS)
    score = _first_float(item, _SCORE_KEYS) or 0.0

    # Clamp score to [0, 1] — some libs emit cosine distance instead of
    # similarity (1 - cosine). We can't tell apart in this layer; just
    # don't let an outlandish value reach the UI.
    if score < 0:
        score = 0.0
    if score > 1:
        score = min(score / 100.0, 1.0) if score > 1 else score

    return EvidenceChunkOut(
        id=str(cid),
        kind=str(kind),
        source_id=source_id,
        source_label=label,
        snippet=_truncate(snippet),
        score=float(score),
        href=href,
    )


def _first_str(d: Mapping[str, Any], keys: Iterable[str]) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _first_float(d: Mapping[str, Any], keys: Iterable[str]) -> Optional[float]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return None


def _truncate(text: str) -> str:
    if len(text) <= MAX_SNIPPET_CHARS:
        return text
    return text[: MAX_SNIPPET_CHARS - 1].rstrip() + "…"
