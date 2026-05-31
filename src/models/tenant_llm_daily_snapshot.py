"""Daily LLM cost / usage snapshots per tenant.

Langfuse keeps the raw trace data, but querying it for every Console
page load adds latency + burns through Langfuse Cloud's API quota.
The :mod:`src.workers.llm_metrics_worker` Celery task runs daily and
materialises a row per (tenant, day) here so:

* The Console can render a 30-day trend line without hitting Langfuse.
* The CEO dashboard's ``llm_cost_30d_eur`` field has a fallback path
  if the live Langfuse call times out.
* Historical analysis (year-over-year, cohort comparisons) doesn't
  depend on Langfuse retention — which is 90 days on the free tier.

One row per (tenant_id, snapshot_date). The Celery task is idempotent
(upserts) so re-running for the same day is safe.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from src.config.database import Base


# Same JSONB / SQLite shim used across the codebase — the test suite
# uses SQLite for schema fixtures and that dialect has no JSONB type.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

# Generic SQLAlchemy ``Uuid`` round-trips through CHAR(32) on SQLite.
_UUID_TYPE = Uuid(as_uuid=True)


class TenantLlmDailySnapshot(Base):
    """One row per tenant per day, recording LLM usage + cost.

    ``tenant_id`` here is the same UUID as ``tenant_registry.id``; the
    snapshot worker is responsible for the lookup from Langfuse's
    ``tenant:<slug>`` trace tag back to the registry row.

    ``by_model_json`` stores the per-model breakdown the live API
    already returns so historical drill-downs (per-model cost over
    time) work without re-querying Langfuse. Shape:

    .. code-block:: json

        {
            "qwen2.5-coder:32b": {"input_tokens": 12000, "output_tokens": 2300,
                                  "requests": 18, "cost_usd": 0.04},
            "gpt-4o": {...}
        }
    """

    __tablename__ = "tenant_llm_daily_snapshots"

    id = Column(_UUID_TYPE, primary_key=True)
    tenant_id = Column(_UUID_TYPE, nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)

    # Headline counters — denormalised so the Console can render the
    # trend chart without unpacking ``by_model_json`` row by row.
    total_requests = Column(Integer, nullable=False, default=0)
    total_input_tokens = Column(BigInteger, nullable=False, default=0)
    total_output_tokens = Column(BigInteger, nullable=False, default=0)
    total_cost_usd = Column(Float, nullable=False, default=0.0)
    total_cost_eur = Column(Float, nullable=False, default=0.0)
    cache_hit_rate_pct = Column(Float, nullable=False, default=0.0)
    avg_latency_ms = Column(Float, nullable=False, default=0.0)

    # Per-model breakdown — see class docstring for the shape.
    by_model_json = Column(_JSONB_OR_JSON, nullable=False, default=dict)

    # Provenance: which Langfuse host produced the data, so a snapshot
    # taken against Cloud doesn't get mixed with one taken against the
    # self-hosted instance during migration.
    langfuse_host = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "snapshot_date",
            name="uq_tenant_llm_daily_snapshots_tenant_date",
        ),
    )


__all__ = ["TenantLlmDailySnapshot"]
