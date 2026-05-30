"""Pricing tier registry (Projeto B It3 — B#16).

Single source of truth for the five tiers defined in the customer-
facing pricing model (``~/Downloads/SkyFirst-Docs/01-customer-facing/
04-pricing-model.md``). The Console reads from here whenever it:

* lists available tiers in the create-tenant form,
* shows tier details in the Settings tab,
* applies preset capacity limits when a tier is upgraded / downgraded.

When the pricing doc changes, this file is the **only** place that
needs to be touched on the backend side. The Internal Console UI
reads the registry over the wire, so a single edit propagates.

The numbers below mirror the pricing doc verbatim. The rate-limit
columns (rpm/tpm) are inferred from the tier description and are
the only fields not directly visible to customers — they are the
operational ceilings the platform enforces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TierPreset:
    """One row in the pricing table."""

    slug: str  # canonical lowercase identifier — matches Tenant.tier
    display_name: str  # human-friendly label rendered in the UI
    headline_price_eur: Optional[int]  # annual list price; None = "custom"
    setup_fee_eur: Optional[int]
    pricing_unit: str  # "year" / "custom"

    # Capacity defaults applied when a tenant is moved to this tier.
    # The Tenant.capacity_limits JSONB column gets these keys.
    capacity_limits: Dict[str, int]

    # Operational ceilings the runtime enforces.
    rate_limit_rpm: int
    rate_limit_tpm: int

    # Universe-Intelligence + AI Processing Profile descriptors.
    universe_intelligence_mode: str
    ai_processing_profile: str
    monitored_entities_cap: Optional[int]
    concurrent_sessions_cap: Optional[int]

    # Marketing-side descriptors (rendered in the create-tenant form).
    target_audience: str
    onboarding_scope: str
    support_sla: str

    # Bedrock cost-tracking opt-in. Strategic + Advanced get dedicated
    # Application Inference Profiles; smaller tiers share defaults.
    bedrock_dedicated_profile: bool = False

    # Inclusions (bullet points). Free-form to keep this flexible.
    inclusions: List[str] = field(default_factory=list)


# Order matters — UIs iterate in this sequence (cheapest first).
TIER_REGISTRY: Dict[str, TierPreset] = {
    "starter": TierPreset(
        slug="starter",
        display_name="Starter",
        headline_price_eur=15_000,
        setup_fee_eur=0,
        pricing_unit="12 months",
        capacity_limits={
            "agents": 3,
            "sources": 3,
            "indexed_gb": 50,
        },
        rate_limit_rpm=60,
        rate_limit_tpm=50_000,
        universe_intelligence_mode="programmed",
        ai_processing_profile="shared",
        monitored_entities_cap=50,
        concurrent_sessions_cap=5,
        target_audience=(
            "Partnership pilots, early customers, first-year deployments "
            "validating fit before full Enterprise commitment."
        ),
        onboarding_scope="1-day provisioning + single 2h training session",
        support_sla="Email · next-business-day",
        bedrock_dedicated_profile=False,
        inclusions=[
            "Provisioning & onboarding (1 day)",
            "Initial training session (2 hours, remote)",
            "Email support · next-business-day response",
            "Quarterly review call",
        ],
    ),
    "foundation": TierPreset(
        slug="foundation",
        display_name="Foundation",
        headline_price_eur=60_000,
        setup_fee_eur=5_000,
        pricing_unit="year",
        capacity_limits={
            "agents": 10,
            "sources": 10,
            "indexed_gb": 200,
        },
        rate_limit_rpm=120,
        rate_limit_tpm=100_000,
        universe_intelligence_mode="programmed + smart_trigger",
        ai_processing_profile="shared",
        monitored_entities_cap=200,
        concurrent_sessions_cap=10,
        target_audience=(
            "Mid-market companies (50-500 employees) with active BI / "
            "data teams using Sky as their coordination layer."
        ),
        onboarding_scope="2-day setup + 4h training, recorded",
        support_sla="Slack Connect · 8 business hours",
        bedrock_dedicated_profile=False,
        inclusions=[
            "Provisioning & onboarding (2 days)",
            "Initial training (4 hours, remote + recorded)",
            "Slack Connect support channel (SLA: 8 business hours)",
            "Monthly review call",
            "Quarterly strategic review",
        ],
    ),
    "core": TierPreset(
        slug="core",
        display_name="Enterprise Core",
        headline_price_eur=120_000,
        setup_fee_eur=10_000,
        pricing_unit="year",
        capacity_limits={
            "agents": 30,
            "sources": 30,
            "indexed_gb": 500,
        },
        rate_limit_rpm=300,
        rate_limit_tpm=300_000,
        universe_intelligence_mode="programmed + smart_trigger",
        ai_processing_profile="standard",
        monitored_entities_cap=300,
        concurrent_sessions_cap=20,
        target_audience=(
            "Organisations structuring their collective intelligence "
            "layer with operational maturity."
        ),
        onboarding_scope=(
            "White-glove provisioning (1-week setup + integration support)"
        ),
        support_sla="Dedicated CSM · 4h response · 99.5% uptime",
        bedrock_dedicated_profile=True,
        inclusions=[
            "White-glove provisioning (1-week setup)",
            "Comprehensive training programme (full-day or 8h remote)",
            "Dedicated Customer Success Manager",
            "SLA Enterprise standard (4h response, 99.5% uptime)",
            "Impact-aware Query Model (source-system protection)",
        ],
    ),
    "advanced": TierPreset(
        slug="advanced",
        display_name="Enterprise Advanced",
        headline_price_eur=180_000,
        setup_fee_eur=15_000,
        pricing_unit="year",
        capacity_limits={
            "agents": 100,
            "sources": 100,
            "indexed_gb": 1_500,
        },
        rate_limit_rpm=600,
        rate_limit_tpm=750_000,
        universe_intelligence_mode="continuous",
        ai_processing_profile="high_throughput",
        monitored_entities_cap=1_500,
        concurrent_sessions_cap=100,
        target_audience=(
            "Organisations requiring continuous intelligence and "
            "operational intensity at scale."
        ),
        onboarding_scope="2-week white-glove with architecture review",
        support_sla="Priority · 1h response · 99.9% uptime",
        bedrock_dedicated_profile=True,
        inclusions=[
            "All Core inclusions",
            "Continuous Universe Intelligence mode",
            "Up to 100 concurrent sessions",
            "AI Processing Profile: High Throughput",
            "Configurable Data Source Impact Throttling",
            "Priority SLA (1h response, 99.9% uptime)",
            "Dedicated technical account team",
            "Quarterly executive business review (QBR)",
        ],
    ),
    "strategic": TierPreset(
        slug="strategic",
        display_name="Enterprise Strategic",
        headline_price_eur=None,
        setup_fee_eur=None,
        pricing_unit="custom",
        capacity_limits={
            # Strategic is "unlimited" — we use sentinel 999_999 so DB
            # comparisons still work without special-casing.
            "agents": 999_999,
            "sources": 999_999,
            "indexed_gb": 999_999,
        },
        rate_limit_rpm=10_000,
        rate_limit_tpm=10_000_000,
        universe_intelligence_mode="continuous + custom",
        ai_processing_profile="reserved",
        monitored_entities_cap=None,
        concurrent_sessions_cap=None,
        target_audience=(
            "Organisations where collective intelligence is mission-"
            "critical infrastructure."
        ),
        onboarding_scope="Custom — negotiated per contract",
        support_sla="24/7 priority · named on-call engineers",
        bedrock_dedicated_profile=True,
        inclusions=[
            "Everything in Advanced",
            "Unlimited agents, sources, indexed context",
            "AI Processing Profile: Reserved Capacity",
            "Custom concurrency limits",
            "High-frequency continuous signal propagation",
            "Custom query orchestration rules",
            "Advanced source impact guardrails",
            "Custom SLA negotiated per contract",
            "Reserved infrastructure (optional separate AWS account)",
            "Custom compliance support (HIPAA, PCI, FedRAMP)",
            "24/7 priority support with named on-call engineers",
        ],
    ),
}


def get_tier(slug: str) -> Optional[TierPreset]:
    """Lookup. Returns None for unknown slugs."""
    return TIER_REGISTRY.get(slug.lower())


def list_tiers() -> List[TierPreset]:
    """Tier presets in ascending price order."""
    return list(TIER_REGISTRY.values())


def apply_preset_to_capacity_limits(
    tier_slug: str, existing_limits: Optional[Dict[str, int]] = None
) -> Dict[str, int]:
    """Return the capacity_limits dict for a tier upgrade / downgrade.

    Policy: applying a tier preset replaces all three dimension
    ceilings. Custom overrides set later via the PATCH endpoint
    survive UNLESS the user explicitly asks for "apply preset", which
    is what this function represents.

    ``existing_limits`` is accepted for future use (per-customer
    contractual overrides on top of a tier baseline) but is currently
    ignored — Iteration 3 ships the strict preset application.
    """
    preset = get_tier(tier_slug)
    if preset is None:
        raise ValueError(f"unknown tier: {tier_slug!r}")
    return dict(preset.capacity_limits)


__all__ = [
    "TIER_REGISTRY",
    "TierPreset",
    "apply_preset_to_capacity_limits",
    "get_tier",
    "list_tiers",
]
