"""Persist structured scan findings (BE-03, Sky Mobile).

Turns a validated :class:`ScanInsightNotifyRequest` from the AI engine into a
first-class ``AgentFinding`` row so it shows up in the mobile Insights feed
next to registered-agent findings.

Mapping (the model already carries the two typed axes):

    payload.severity        → AgentFinding.type      (risk|opportunity|insight)
    payload.severity_level  → AgentFinding.severity  (high|med|low)

Scan findings have no registered agent, so ``agent_id`` stays NULL and the
row carries ``source='scan'`` + ``space_id`` + ``agent_name`` directly. The
engine has already run its semantic-duplicate check (cosine ≥ 0.85) before
calling, so this layer just records — no second dedup here (test T-03.3).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import AgentFinding
from src.schemas.scan_insight import ScanInsightNotifyRequest


def _viz_kind_for(series_len: int) -> str:
    """A finding with a series renders as a line/sparkline; without one it is a
    single big number. Mirrors the FE chart-picker registry."""
    return "line" if series_len > 0 else "big_number"


async def record_scan_finding(db: AsyncSession, payload: ScanInsightNotifyRequest) -> AgentFinding:
    """Create and flush a scan ``AgentFinding`` from a validated payload.

    The caller owns the commit. ``is_live`` is *not* stored — it is derived at
    read time from the scan being active + recently executed (BE-02), so it
    never goes stale on the row.
    """
    series = [point.model_dump() for point in payload.series]
    stat_tiles = [tile.model_dump() for tile in payload.stat_tiles]

    finding = AgentFinding(
        agent_id=None,  # scan findings are not tied to a registered agent
        source="scan",
        space_id=UUID(payload.space_id),
        agent_name=payload.agent_name or "Autonomous scan",
        type=payload.severity,  # risk | opportunity | insight
        severity=payload.severity_level,  # high | med | low
        title=payload.title[:500],
        description=payload.summary or payload.title,
        series=series,
        stat_tiles=stat_tiles,
        viz_kind=_viz_kind_for(len(series)),
    )
    db.add(finding)
    await db.flush()  # populate the PK without forcing the caller's commit
    return finding
