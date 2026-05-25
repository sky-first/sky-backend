"""W-wire — chat pipeline orchestrator.

Wraps the existing AI call (real or mock) with the security primitives
shipped in W3/W4/W5/W6/W7/W10:

  - Input guard (W4) — runs FIRST. Hard fail raises CHAT_* errors.
  - Output guard (W5) — secret redaction + system-prompt-leak +
    fail-closed on ACL breach.
  - Transparency bundle (W7) — assembled from what we know locally
    (trace_id, prompt_version, guard_flags, basic reasoning_trace).
    Evidence chunks are populated by the AI engine when it cooperates;
    until Runpod returns them we ship an empty list.
  - Metrics (W10) — request, guard decisions, upstream latency.
  - Errors (W6) — every failure becomes a ``ChatError`` with a stable
    code and a trace_id the support team can quote.

Usage::

    pipeline = ChatPipeline(user_id=user.id, endpoint="/ai/chat")
    guarded_input = pipeline.preflight(message)        # raises on policy
    try:
        raw_answer = await call_ai(guarded_input.text)
    except Exception as exc:
        raw_answer = pipeline.on_upstream_error(exc)   # ChatUpstream*
    response = pipeline.finalize(
        raw_answer,
        evidence=ai_evidence,
        evidence_count=len(ai_evidence),
        authorized_evidence_ids=auth_ids,
    )

The pipeline is **stateful** for one chat turn. Construct a fresh one
per request — never reuse across users.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence
from uuid import UUID

from src.ai.input_guard import (
    ChatInputError,
    ChatMessageEmpty,
    ChatMessageTooLong,
    ChatPolicyViolation as _InputPolicyViolation,
    GuardedInput,
    guard_user_input,
)
from src.ai.metrics import (
    observe_upstream_latency,
    record_input_guard,
    record_output_guard,
    record_request,
)
from src.ai.output_guard import (
    GuardedOutput,
    OutputACLBreach,
    guard_model_output,
)
from src.ai.prompt_templates import PROMPT_VERSION
from src.core.errors.chat_errors import (
    ChatContextDenied,
    ChatError,
    ChatInternalError,
    ChatMalformedInput,
    ChatOutputACLBreach,
    ChatOutputFiltered,
    ChatPolicyViolation,
    ChatUpstreamError,
    ChatUpstreamTimeout,
    wrap_as_chat_error,
)
from src.schemas.ai_transparency import (
    AIResponseTransparency,
    EvidenceChunkOut,
    GuardFlagOut,
    ReasoningStepOut,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Result envelope
# ---------------------------------------------------------------------------


@dataclass
class FinalizedChatResponse:
    answer: str
    transparency: AIResponseTransparency
    safe: bool
    raised: Optional[ChatError] = None


# ---------------------------------------------------------------------------
#  Pipeline
# ---------------------------------------------------------------------------


class ChatPipeline:
    """Orchestrator for one chat turn.

    Lifecycle:
      1. ``__init__`` — generate trace_id, start timer.
      2. ``preflight(message)`` — input guard. May raise.
      3. (caller invokes the AI service)
      4. ``finalize(answer, ...)`` — output guard + transparency. May
         raise on ACL breach.
    """

    def __init__(
        self,
        *,
        user_id: UUID,
        endpoint: str = "/ai/chat",
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.user_id = user_id
        self.endpoint = endpoint
        self.prompt_version = prompt_version
        self.trace_id: str = uuid.uuid4().hex
        self._reasoning: List[ReasoningStepOut] = []
        self._guard_flags: List[GuardFlagOut] = []
        self._started_at = time.monotonic()
        self._guarded_input: Optional[GuardedInput] = None

    # ------------------------------------------------------------------
    #  Step 1 — Input
    # ------------------------------------------------------------------

    def preflight(self, message: str) -> GuardedInput:
        """Run the input guard. Returns the sanitised text + flags.

        On hard fail (empty / too-long / policy block) raises a
        ``ChatError`` subclass with the right code attached and the
        trace_id pre-populated.
        """
        try:
            guarded = guard_user_input(message, user_id=self.user_id)
        except ChatInputError as exc:
            self._record_input_decision(decision="block", reason=type(exc).__name__)
            raise self._wrap(exc) from exc

        self._guarded_input = guarded
        self._record_input_decision(
            decision="flag" if guarded.injection_suspected else "pass",
            reason="injection" if guarded.injection_suspected else "none",
            injection_patterns=guarded.injection_reasons or None,
        )

        if guarded.injection_suspected:
            for label in guarded.injection_reasons or []:
                self._guard_flags.append(
                    GuardFlagOut(kind="INJECTION_SUSPECTED", reason=label)
                )

        self._reasoning.append(
            ReasoningStepOut(
                step=len(self._reasoning) + 1,
                kind="guard",
                summary=(
                    f"Input guard: ok ({len(guarded.text)} chars"
                    + (f", {len(guarded.injection_reasons)} injection signal"
                       if guarded.injection_suspected else "")
                    + ")"
                ),
            )
        )
        return guarded

    # ------------------------------------------------------------------
    #  Step 2 — Around the AI call (helpers)
    # ------------------------------------------------------------------

    def note_retrieval(self, *, evidence_count: int, duration_ms: int) -> None:
        """Optional — call from the AI service when it returns retrieval
        metadata. Used to populate the reasoning trace."""
        self._reasoning.append(
            ReasoningStepOut(
                step=len(self._reasoning) + 1,
                kind="retrieval",
                summary=f"Retrieved {evidence_count} chunks",
                duration_ms=duration_ms,
            )
        )

    def note_synthesis(self, *, duration_ms: int, model: Optional[str] = None) -> None:
        self._reasoning.append(
            ReasoningStepOut(
                step=len(self._reasoning) + 1,
                kind="synthesis",
                summary=f"LLM synthesis{f' ({model})' if model else ''}",
                duration_ms=duration_ms,
            )
        )

    def on_upstream_error(self, exc: Exception) -> ChatError:
        """Map a raw upstream exception to a ``ChatUpstream*`` error.

        Caller decides whether to re-raise or fallback. We DO NOT raise
        here — the existing chat flow may still produce a mock answer.
        Returns the ChatError so it can be attached to the response.
        """
        text = (str(exc) or "").lower()
        if "timeout" in text or "deadline" in text:
            err: ChatError = ChatUpstreamTimeout(trace_id=self.trace_id)
        elif "5" in text and ("503" in text or "502" in text or "504" in text):
            err = ChatUpstreamError(trace_id=self.trace_id)
        else:
            err = ChatUpstreamError(trace_id=self.trace_id)
        record_request(self.endpoint, "upstream_error")
        return err

    # ------------------------------------------------------------------
    #  Step 3 — Output
    # ------------------------------------------------------------------

    def finalize(
        self,
        answer: str,
        *,
        evidence: Optional[Sequence[EvidenceChunkOut]] = None,
        evidence_count: Optional[int] = None,
        authorized_evidence_ids: Iterable[str] = (),
    ) -> FinalizedChatResponse:
        """Run the output guard + assemble the transparency bundle.

        Raises ``ChatOutputACLBreach`` on a breach (the answer NEVER
        ships in that case).
        """
        elapsed = max(0.0, time.monotonic() - self._started_at)
        observe_upstream_latency(stage=self.endpoint.lstrip("/").replace("/", "."), seconds=elapsed)

        try:
            guarded_out: GuardedOutput = guard_model_output(
                answer or "",
                authorized_evidence_ids=authorized_evidence_ids,
                user_id=self.user_id,
                evidence_count=evidence_count if evidence_count is not None else len(evidence or []),
            )
        except OutputACLBreach as exc:
            self._record_output_decision(
                decision="block",
                reason="acl_breach",
                acl_breach_kind=str(exc) or "citation_outside_authorised",
            )
            record_request(self.endpoint, "acl_breach")
            self._guard_flags.append(GuardFlagOut(kind="OUTPUT_ACL_BREACH", reason=str(exc)))
            self._reasoning.append(
                ReasoningStepOut(
                    step=len(self._reasoning) + 1,
                    kind="guard",
                    summary="Output guard blocked: ACL breach",
                )
            )
            raise ChatOutputACLBreach(trace_id=self.trace_id) from exc

        # Translate output flags into transparency entries
        for label in guarded_out.redactions:
            self._guard_flags.append(GuardFlagOut(kind="SECRET_REDACTED", reason=label))
        for f in guarded_out.flags:
            if f == "SECRET_REDACTED":
                continue  # already added
            self._guard_flags.append(GuardFlagOut(kind=f))

        decision = "block" if not guarded_out.safe else (
            "filter" if guarded_out.redactions or guarded_out.flags else "pass"
        )
        self._record_output_decision(
            decision=decision,
            reason="leak" if "SYSTEM_PROMPT_LEAK" in guarded_out.flags else (
                "redaction" if guarded_out.redactions else "none"
            ),
        )

        self._reasoning.append(
            ReasoningStepOut(
                step=len(self._reasoning) + 1,
                kind="guard",
                summary=(
                    "Output guard: " + (
                        "leak refusal" if "SYSTEM_PROMPT_LEAK" in guarded_out.flags
                        else f"{len(guarded_out.redactions)} redaction(s)"
                        if guarded_out.redactions
                        else "pass"
                    )
                ),
            )
        )

        record_request(self.endpoint, "200" if guarded_out.safe else "filtered")

        transparency = AIResponseTransparency(
            trace_id=self.trace_id,
            prompt_version=self.prompt_version,
            evidence=list(evidence or []),
            reasoning_trace=list(self._reasoning),
            guard_flags=list(self._guard_flags),
        )

        return FinalizedChatResponse(
            answer=guarded_out.text,
            transparency=transparency,
            safe=guarded_out.safe,
        )

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    def _wrap(self, exc: ChatInputError) -> ChatError:
        """Translate W4 input-guard exceptions to W6 ChatError variants
        carrying the trace_id."""
        wrapped = wrap_as_chat_error(exc, trace_id=self.trace_id)
        return wrapped

    def _record_input_decision(
        self,
        *,
        decision: str,
        reason: str,
        injection_patterns: Optional[List[str]] = None,
        policy_category: Optional[str] = None,
    ) -> None:
        record_input_guard(
            decision=decision,
            reason=reason,
            injection_patterns=injection_patterns,
            policy_category=policy_category,
        )

    def _record_output_decision(
        self,
        *,
        decision: str,
        reason: str,
        acl_breach_kind: Optional[str] = None,
    ) -> None:
        record_output_guard(
            decision=decision,
            reason=reason,
            acl_breach_kind=acl_breach_kind,
        )
