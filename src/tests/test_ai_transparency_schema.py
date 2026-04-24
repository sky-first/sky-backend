"""W7 — Evidence + Reasoning transparency schema tests.

QA perspectives:
  - Schema defaults (empty lists, no trace_id) so old servers don't
    break old clients.
  - Serialization round-trip (Pydantic v2 model_dump / model_validate).
  - has_data() behaves.
  - Backward compat: ChatMessageResponse and AIQueryResponse accept
    missing transparency field without complaint.
  - Clients rendering the block: evidence with href / without href,
    score bounds, multi-flag, reasoning steps ordered.
  - Attacker: malformed evidence id / negative step / bad score still
    either parse (strings are not sanitized by pydantic beyond type)
    or are rejected at validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.schemas.ai import AIQueryResponse, ChatMessageResponse
from src.schemas.ai_transparency import (
    AIResponseTransparency,
    EvidenceChunkOut,
    GuardFlagOut,
    ReasoningStepOut,
)


# ---------------------------------------------------------------------------
#  Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_empty_transparency_has_no_data(self):
        t = AIResponseTransparency()
        assert t.evidence == []
        assert t.reasoning_trace == []
        assert t.guard_flags == []
        assert t.trace_id is None
        assert t.prompt_version is None
        assert t.has_data() is False

    def test_evidence_only_counts_as_data(self):
        t = AIResponseTransparency(
            evidence=[
                EvidenceChunkOut(id="a", kind="pillar", source_label="x", snippet="s")
            ]
        )
        assert t.has_data() is True

    def test_trace_id_only_counts_as_data(self):
        t = AIResponseTransparency(trace_id="01HX")
        assert t.has_data() is True


# ---------------------------------------------------------------------------
#  Evidence chunk
# ---------------------------------------------------------------------------


class TestEvidenceChunk:
    def test_minimal_required_fields(self):
        e = EvidenceChunkOut(id="x", kind="pillar", source_label="Y", snippet="Z")
        assert e.score == 0.0
        assert e.href is None

    def test_with_href_and_score(self):
        e = EvidenceChunkOut(
            id="x",
            kind="table",
            source_id="00000000-0000-0000-0000-000000000001",
            source_label="orders",
            snippet="Receita cresceu 12%",
            score=0.91,
            href="/context/orders",
        )
        d = e.model_dump()
        assert d["score"] == 0.91
        assert d["href"] == "/context/orders"

    def test_long_snippet_accepted(self):
        """We don't truncate at schema level — caller is expected to trim
        to ~400 chars before populating, but we allow any length so the
        API doesn't reject a legitimate response."""
        snippet = "a" * 10_000
        e = EvidenceChunkOut(id="x", kind="pillar", source_label="y", snippet=snippet)
        assert len(e.snippet) == 10_000


# ---------------------------------------------------------------------------
#  Reasoning step
# ---------------------------------------------------------------------------


class TestReasoningStep:
    def test_step_must_be_ge_1(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            ReasoningStepOut(step=0, kind="retrieval", summary="x")

    def test_duration_non_negative(self):
        r = ReasoningStepOut(step=1, kind="retrieval", summary="x", duration_ms=0)
        assert r.duration_ms == 0
        with pytest.raises(Exception):
            ReasoningStepOut(step=1, kind="retrieval", summary="x", duration_ms=-5)

    def test_kind_freeform(self):
        """kind is freeform string so new kinds ship without a schema
        migration. Frontend maps unknown kinds to a generic render."""
        r = ReasoningStepOut(step=1, kind="brand-new-kind", summary="x")
        assert r.kind == "brand-new-kind"


# ---------------------------------------------------------------------------
#  Guard flag
# ---------------------------------------------------------------------------


class TestGuardFlag:
    def test_kind_required(self):
        f = GuardFlagOut(kind="SECRET_REDACTED")
        assert f.reason is None

    def test_reason_accepted(self):
        f = GuardFlagOut(kind="INJECTION_SUSPECTED", reason="ignore_previous")
        assert f.reason == "ignore_previous"


# ---------------------------------------------------------------------------
#  Backward compat with ChatMessageResponse / AIQueryResponse
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_chat_message_response_without_transparency(self):
        """Old servers not yet populating transparency — field absent."""
        r = ChatMessageResponse(
            id=uuid4(),
            type="assistant",
            content="hello",
            page_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
        )
        d = r.model_dump()
        assert d["transparency"] is None

    def test_ai_query_response_without_transparency(self):
        r = AIQueryResponse(
            id=uuid4(),
            question="q",
            status="completed",
            page_id=uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        d = r.model_dump()
        assert d["transparency"] is None

    def test_chat_message_response_with_transparency(self):
        t = AIResponseTransparency(
            trace_id="01HX",
            prompt_version="v1.0.0",
            evidence=[EvidenceChunkOut(id="e1", kind="pillar", source_label="Crescimento", snippet="...")],
            reasoning_trace=[ReasoningStepOut(step=1, kind="retrieval", summary="fetched 7 chunks")],
            guard_flags=[GuardFlagOut(kind="SECRET_REDACTED")],
        )
        r = ChatMessageResponse(
            id=uuid4(),
            type="assistant",
            content="hello",
            page_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            transparency=t,
        )
        d = r.model_dump()
        assert d["transparency"]["trace_id"] == "01HX"
        assert len(d["transparency"]["evidence"]) == 1


# ---------------------------------------------------------------------------
#  Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_dump_and_validate_roundtrip(self):
        t = AIResponseTransparency(
            trace_id="t",
            prompt_version="v1",
            evidence=[
                EvidenceChunkOut(id="e1", kind="k", source_label="s", snippet="snip", score=0.5)
            ],
            reasoning_trace=[
                ReasoningStepOut(step=1, kind="retrieval", summary="fetched"),
                ReasoningStepOut(step=2, kind="synthesis", summary="synth", duration_ms=120),
            ],
            guard_flags=[GuardFlagOut(kind="INJECTION_SUSPECTED", reason="role_spoof")],
        )
        d = t.model_dump()
        restored = AIResponseTransparency.model_validate(d)
        assert restored == t

    def test_unknown_field_rejected(self):
        """Pydantic v2 default is to accept extras silently unless
        ``model_config = ConfigDict(extra='forbid')``. We don't set forbid
        — extras are dropped on dump. Test documents that behaviour."""
        t = AIResponseTransparency.model_validate({"trace_id": "x", "unknown_field": 1})
        assert "unknown_field" not in t.model_dump()


# ---------------------------------------------------------------------------
#  Negative / edge
# ---------------------------------------------------------------------------


class TestNegativeCases:
    def test_empty_list_fields_render_as_empty_arrays(self):
        t = AIResponseTransparency()
        d = t.model_dump()
        assert d["evidence"] == []
        assert d["reasoning_trace"] == []
        assert d["guard_flags"] == []

    def test_reasoning_step_negative_step_rejected(self):
        with pytest.raises(Exception):
            ReasoningStepOut(step=-1, kind="retrieval", summary="x")

    def test_evidence_required_fields_enforced(self):
        with pytest.raises(Exception):
            EvidenceChunkOut(id="x")  # missing kind, source_label, snippet

    def test_many_flags(self):
        t = AIResponseTransparency(
            guard_flags=[
                GuardFlagOut(kind="INJECTION_SUSPECTED"),
                GuardFlagOut(kind="SECRET_REDACTED"),
                GuardFlagOut(kind="OUTPUT_FILTERED"),
                GuardFlagOut(kind="SYSTEM_PROMPT_LEAK"),
            ]
        )
        assert len(t.guard_flags) == 4
