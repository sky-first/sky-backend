"""W7 — Evidence + Reasoning transparency contract.

Master plan §8. Shape of the response the backend returns when chat /
agent answers, letting the frontend show "how was this generated" with:

  - evidence[]       : which context chunks were used
  - reasoning_trace[]: step-by-step synthesis (retrieval → tool → output)
  - trace_id         : correlation id for support
  - prompt_version   : which LAYER_1 was in force
  - guard_flags[]    : output guard flags (SECRET_REDACTED, etc.)

Backward compat: the embedding field on chat/query responses
(``transparency``) is **optional**; callers that don't populate it see
no change in payload shape.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class EvidenceChunkOut(BaseModel):
    """One chunk of retrieved context used to answer the question."""

    id: str = Field(..., description="Embedding id — clickable source link")
    kind: str = Field(..., description="schema_table|pillar|event|...")
    source_id: Optional[str] = Field(
        default=None,
        description="Original source row id (table/pillar/event) — used to navigate",
    )
    source_label: str = Field(..., description="Human label (e.g. 'orders table')")
    snippet: str = Field(..., description="Preview — up to 400 chars")
    score: float = Field(default=0.0, description="Cosine similarity 0..1")
    href: Optional[str] = Field(
        default=None,
        description="Optional deep link to open the source in the UI",
    )

    model_config = ConfigDict(from_attributes=True)


class ReasoningStepOut(BaseModel):
    """One step in the chain-of-thought the backend decided to expose.

    These are coarse — we never expose raw LLM chain-of-thought. Each
    step is a high-level explanation (retrieval, tool call, synthesis)."""

    step: int = Field(..., ge=1)
    kind: str = Field(
        ...,
        description="retrieval|tool_call|synthesis|guard|moderation",
    )
    summary: str = Field(..., description="One-line explanation")
    duration_ms: Optional[int] = Field(default=None, ge=0)

    model_config = ConfigDict(from_attributes=True)


class GuardFlagOut(BaseModel):
    """One flag raised by an input/output guard during processing.

    kind:
      INJECTION_SUSPECTED: input guard flagged a payload as likely
                          prompt-injection (W3 platform prompt handled it).
      SECRET_REDACTED:    output guard found and redacted a secret.
      OUTPUT_FILTERED:    soft filter triggered — partial answer shipped.
      SYSTEM_PROMPT_LEAK: output swapped for canned refusal (hard stop).
    """

    kind: str = Field(...)
    reason: Optional[str] = Field(default=None)


class AIResponseTransparency(BaseModel):
    """Bundle returned alongside chat/query answers.

    ALL fields optional so older clients keep working unchanged. A client
    that receives this block is expected to render the "Ver como foi
    gerado" affordance."""

    trace_id: Optional[str] = None
    prompt_version: Optional[str] = None
    evidence: List[EvidenceChunkOut] = Field(default_factory=list)
    reasoning_trace: List[ReasoningStepOut] = Field(default_factory=list)
    guard_flags: List[GuardFlagOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    def has_data(self) -> bool:
        return bool(
            self.trace_id
            or self.evidence
            or self.reasoning_trace
            or self.guard_flags
        )
