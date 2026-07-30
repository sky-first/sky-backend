"""Schemas for the scan-insight notify contract (BE-03, Sky Mobile).

The AI engine's autonomous scan agent posts a *structured* finding here so it
lands in the mobile Insights feed as a machine-readable object (severity dot,
sparkline, stat tiles) instead of the markdown blob it produces today.

Validation is the acceptance gate for test T-03.6: a payload missing a
required field, or carrying an out-of-enum ``severity`` / ``severity_level``,
fails Pydantic validation → FastAPI returns **422**, and no partial row is
written.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# The two typed axes the mobile feed renders:
#   severity        → the category dot (risk / opportunity / insight)
#   severity_level  → how loud it is (high / med / low)
Severity = Literal["risk", "opportunity", "insight"]
SeverityLevel = Literal["high", "med", "low"]


class SeriesPoint(BaseModel):
    """One point of the sparkline behind the headline number."""

    t: str  # a label or ISO timestamp — kept as a string, the FE formats it
    v: float


class StatTile(BaseModel):
    """One of the up-to-3 key/value tiles on the insight detail."""

    label: str
    value: str


class ScanInsightNotifyRequest(BaseModel):
    """Engine → backend payload for a non-silent scan finding."""

    space_id: str
    agent_name: Optional[str] = None
    title: str = Field(min_length=1, max_length=500)
    summary: str = ""
    severity: Severity
    severity_level: SeverityLevel
    # May be empty — an aggregate-only finding has no series (test T-03.4).
    series: List[SeriesPoint] = Field(default_factory=list)
    stat_tiles: List[StatTile] = Field(default_factory=list)

    @field_validator("stat_tiles")
    @classmethod
    def _at_most_three_tiles(cls, value: List[StatTile]) -> List[StatTile]:
        if len(value) > 3:
            raise ValueError("stat_tiles: at most 3 are allowed")
        return value


class ScanInsightNotifyResponse(BaseModel):
    id: str
    source: str
    type: str
    severity: str
    is_live: bool
