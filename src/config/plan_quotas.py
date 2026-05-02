"""Plan quotas — beat budgets, window length and per-event costs.

The whole quota system speaks ONE currency (beats). 1 beat ==
cost-equivalent of one gpt-4o-mini call (the cheapest LLM tier we
ship). Everything that consumes AI cost translates into beats via
``KIND_COSTS``; everything that limits cost translates into beats
via ``PLAN_QUOTAS``.

Why beats and not dollars:
  • Hides OpenAI/RunPod price volatility from customers.
  • Lets us swap providers (OpenAI → Ollama on RunPod) without
    re-pricing.
  • Allows clean math on agent tier-routers: 1 L3 deep dive ≈ 20 L2
    triage calls ≈ 100 L1 delta checks.

The KIND values listed here MUST match the strings written into
``beat_consumption.kind``. Adding a new kind: register it in
``KIND_COSTS`` (cost → beats) and the agent/chat call site that
emits it. Reading a kind that's not in the table costs 1 beat (so
the system stays available even if a deploy drifts).

Plan resolution:
  • A demo user (``user.is_demo``) gets the DEMO plan regardless of
    tenant.
  • Otherwise the tenant ships its own plan (Phase 3 wires Stripe);
    until then everyone falls back to STARTER.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Literal


# ─── Event kinds and their beat cost ────────────────────────────────────────

# L2-normalized: 1 beat = 1 gpt-4o-mini call.
KIND_COSTS: dict[str, Decimal] = {
    # Interactive chat — every user-typed question runs the L3 ReAct
    # loop with recursion=6. About 20× the cost of an L2 triage.
    "chat": Decimal("20"),
    # /ai/suggest-title — single gpt-4o-mini call (no ReAct), much
    # cheaper than chat.
    "suggest_title": Decimal("5"),
    # Agent tiers — wired in by the tier-router PR (sibling to this
    # one). Reserved here so the schema is final and FE can render
    # them in the breakdown today.
    "agent_l1": Decimal("0.2"),    # delta-check, no LLM
    "agent_l2": Decimal("1"),      # gpt-4o-mini triage
    "agent_l3": Decimal("20"),     # gpt-4o ReAct
    "agent_run": Decimal("0"),     # synthetic roll-up only — actual
                                    # cost is the sum of l1+l2+l3 rows
}

# Default cost when an unknown kind shows up (defensive — keeps the
# meter running even if a deploy adds a new kind without registering it).
DEFAULT_KIND_COST = Decimal("1")


# ─── Plan tiers ─────────────────────────────────────────────────────────────

PlanTier = Literal["demo", "free", "starter", "pro", "enterprise"]


@dataclass(frozen=True)
class PlanQuota:
    tier: PlanTier
    beats_per_period: Decimal
    period: timedelta
    label: str
    upgrade_cta: str

    @property
    def period_days(self) -> int:
        return int(self.period.total_seconds() // 86400)


# Period defs:
#   • Demo: rolling 7 days from signup. Match user.demo_expires_at TTL.
#   • Free / Starter / Pro / Enterprise: rolling 30 days from now.
#     Rolling (not calendar-month) avoids the "huge spike on the
#     1st" pattern and means the on-demand counter works without a
#     reset cron.
PLAN_QUOTAS: dict[PlanTier, PlanQuota] = {
    "demo": PlanQuota(
        tier="demo",
        beats_per_period=Decimal("500"),
        period=timedelta(days=7),
        label="Demo",
        upgrade_cta="Talk to us to extend your sandbox",
    ),
    "free": PlanQuota(
        tier="free",
        beats_per_period=Decimal("200"),
        period=timedelta(days=30),
        label="Free",
        upgrade_cta="Upgrade to Starter for 25× more capacity",
    ),
    "starter": PlanQuota(
        tier="starter",
        beats_per_period=Decimal("5000"),
        period=timedelta(days=30),
        label="Starter",
        upgrade_cta="Upgrade to Pro for 6× more capacity",
    ),
    "pro": PlanQuota(
        tier="pro",
        beats_per_period=Decimal("30000"),
        period=timedelta(days=30),
        label="Pro",
        upgrade_cta="Upgrade to Enterprise for unlimited capacity",
    ),
    "enterprise": PlanQuota(
        tier="enterprise",
        beats_per_period=Decimal("200000"),
        period=timedelta(days=30),
        label="Enterprise",
        upgrade_cta="Contact your account team to expand capacity",
    ),
}


def cost_for_kind(kind: str) -> Decimal:
    """Return the beat cost of one event of the given kind."""
    return KIND_COSTS.get(kind, DEFAULT_KIND_COST)


def plan_for_user(*, is_demo: bool, tenant_tier: str | None = None) -> PlanQuota:
    """Resolve which plan applies to a user.

    Demo users always get the DEMO plan regardless of tenant — even
    if their tenant happens to be on Pro, the visitor's TTL sandbox
    is its own bucket. Once the demo expires the user is removed,
    so this is a closed system.

    Tenant tier resolution will read from a future ``tenant.plan_tier``
    column populated by Stripe. Until that ships, we default every
    non-demo user to STARTER (the cheapest paid plan), which gives
    the dev environment a real budget and prevents accidental
    burn during testing.
    """
    if is_demo:
        return PLAN_QUOTAS["demo"]
    if tenant_tier and tenant_tier in PLAN_QUOTAS:
        return PLAN_QUOTAS[tenant_tier]  # type: ignore[index]
    return PLAN_QUOTAS["starter"]
