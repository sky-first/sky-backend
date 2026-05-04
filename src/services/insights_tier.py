"""Tier classifier for the Insights-Analytics product surface.

Every chat answer and agent execution gets stamped with a tier:

  L1 — Delta / trivial. Free interaction (greeting, single-fact lookup,
       agent run that produced no finding). Doesn't count against the
       customer's monthly insight allowance.
  L2 — Triage. Real work: retrieval against the knowledge layer, agent
       run that surfaced a finding. Counts as 1 insight.
  L3 — Deep dive. Multi-step planning, cross-source correlation,
       sustained reasoning. Counts as 3 insights.

The classifier is intentionally simple — token count + retrieval-flag +
step-count — so it's predictable and explainable in the UI. We can
swap in a smarter model later (e.g. content-based classifier) without
changing the call sites because the contract is just "give me the
tier for this run".

Customer-visible motivation: stops the Analytics page from looking
like a token meter ("you used $X of compute") and frames it instead
as a value meter ("you produced X dense insights"). Without tiering,
a 1-token greeting would look identical to a 50k-token deep dive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Tier = Literal["l1", "l2", "l3"]


# Above this many output tokens, even a single-step answer is treated
# as L2 — it's clearly substantive even without retrieval.
_L2_TOKEN_FLOOR = 4000

# Above this many input tokens (large context) AND retrieval-flag, we
# treat the answer as a deep dive even without explicit multi-step.
_L3_INPUT_FLOOR = 16000

# Baseline hours saved by tier — used by the analytics aggregator to
# compute "hours of analyst time saved" relative to a traditional
# Jira → SQL → BI → Slack flow. Conservative defaults.
HOURS_SAVED_BY_TIER: dict[Tier, float] = {
    "l1": 0.25,  # 15min — quick lookup
    "l2": 3.0,   # 3h — what triage normally takes through a data team
    "l3": 8.0,   # full workday for a deep cross-source investigation
}

# Allowance weight — how the tier counts against a monthly insight cap.
# L1 is free (0), L2 is 1 unit, L3 is 3 units.
ALLOWANCE_WEIGHT_BY_TIER: dict[Tier, int] = {"l1": 0, "l2": 1, "l3": 3}


@dataclass
class ClassificationInput:
    """Inputs to the tier classifier. All fields optional — missing
    signal degrades gracefully toward L1."""

    retrieval_used: bool = False
    multi_step: bool = False
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    findings_count: Optional[int] = None  # for agent runs only
    error: bool = False  # failed runs default to L1 regardless of cost


def classify_tier(signal: ClassificationInput) -> Tier:
    """Map a run's signals onto an L1/L2/L3 tier.

    Order matters: L3 takes priority (most specific), then L2, then L1
    as the catch-all. We never return L1 if the signal genuinely
    indicates substantive work, but a degenerate signal (no retrieval,
    no plan, < threshold tokens) does land at L1 — that's the point.
    """
    if signal.error:
        return "l1"

    # Deep dive: explicit multi-step plan, OR very large input + retrieval.
    if signal.multi_step and signal.retrieval_used:
        return "l3"
    if (
        signal.retrieval_used
        and (signal.input_tokens or 0) >= _L3_INPUT_FLOOR
    ):
        return "l3"

    # Triage: retrieval used, substantive output, or agent surfaced
    # something material.
    if signal.retrieval_used:
        return "l2"
    if (signal.output_tokens or 0) >= _L2_TOKEN_FLOOR:
        return "l2"
    if signal.findings_count and signal.findings_count > 0:
        return "l2"

    return "l1"


def classify_agent_execution(
    *,
    findings_count: int = 0,
    delta_kind: Optional[str] = None,
    monitor_type: Optional[str] = None,
    retrieval_used: bool = False,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    error: bool = False,
) -> Tier:
    """Convenience wrapper for `agent_executions` — knows about delta_kind.

    A `material` delta means the run found something genuinely new —
    promotes the tier even when token counts are modest. `monitor_type`
    'scan' (full cross-source sweeps) is treated as multi-step, since
    the supervisor decomposes it into sub-queries internally.
    """
    multi_step = monitor_type == "scan" or delta_kind == "material"
    return classify_tier(
        ClassificationInput(
            retrieval_used=retrieval_used or multi_step,
            multi_step=multi_step,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            findings_count=findings_count,
            error=error,
        )
    )


def classify_chat_message(
    *,
    retrieval_used: bool = False,
    multi_step: bool = False,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    error: bool = False,
) -> Tier:
    """Convenience wrapper for `messages`."""
    return classify_tier(
        ClassificationInput(
            retrieval_used=retrieval_used,
            multi_step=multi_step,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error,
        )
    )
