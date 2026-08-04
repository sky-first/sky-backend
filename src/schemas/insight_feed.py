"""Schemas for the unified mobile Insights feed (BE-02, Sky Mobile).

The feed serves one machine-readable object per finding — agent-produced or
scan-produced — with the two typed axes the mobile UI renders (``severity``
dot + ``severity_level``), the sparkline ``series``, and the caller's own
``reviewed``/``pinned`` state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

# The five filter chips the design ships.
INSIGHT_FILTERS = ("all", "latest", "featured", "risk", "opportunity")


class InsightItem(BaseModel):
    id: str
    severity: str  # AgentFinding.type: risk | opportunity | insight
    severity_level: str  # AgentFinding.severity: high | med | low
    agent_name: Optional[str] = None
    title: str
    summary: str
    is_live: bool
    series: List[Dict[str, Any]] = []
    created_at: datetime
    reviewed: bool = False
    pinned: bool = False
    deep_link: str


class InsightFeedResponse(BaseModel):
    items: List[InsightItem]
    next_cursor: Optional[str] = None
    # Per-filter counts over the caller's full scope, so the chips are exact.
    counts: Dict[str, int]


class InsightDetail(InsightItem):
    description: str
    stat_tiles: List[Dict[str, Any]] = []
    viz_kind: Optional[str] = None


class ReviewRequest(BaseModel):
    reviewed: bool


class PinRequest(BaseModel):
    pinned: bool
