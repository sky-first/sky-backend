"""BE-03 · Structured scan findings — backend acceptance suite.

Covers the backend half of BE-03: strict validation of the notify contract
(T-03.6) and persistence of a first-class structured ``AgentFinding``
(T-03.1, T-03.4). The engine half — classification + series capture (T-03.2,
T-03.5) — is tested in ``sky-poc-ai/tests/unit/test_insight_structurer.py``.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.models.agent import AgentFinding  # noqa: F401 — registers table
from src.schemas.scan_insight import ScanInsightNotifyRequest
from src.services.scan_insight_service import record_scan_finding


def _valid(**overrides) -> dict:
    base = dict(
        space_id=str(uuid.uuid4()),
        agent_name="Revenue scan",
        title="North sales down 18%",
        summary="Sales fell 18% vs the 4-week average; 3 lapsed clients.",
        severity="risk",
        severity_level="high",
        series=[{"t": "W1", "v": 100.0}, {"t": "W2", "v": 82.0}],
        stat_tiles=[{"label": "Change", "value": "-18%"}],
    )
    base.update(overrides)
    return base


# ─── T-03.6 · strict validation → 422 (Pydantic raises → FastAPI 422) ────────


def test_t03_6_missing_severity_rejected():
    bad = {k: v for k, v in _valid().items() if k != "severity"}
    with pytest.raises(ValidationError):
        ScanInsightNotifyRequest(**bad)


def test_t03_6_out_of_enum_severity_rejected():
    with pytest.raises(ValidationError):
        ScanInsightNotifyRequest(**_valid(severity="urgent"))


def test_t03_6_out_of_enum_level_rejected():
    # 'medium' is not a valid level — must be 'med'.
    with pytest.raises(ValidationError):
        ScanInsightNotifyRequest(**_valid(severity_level="medium"))


def test_t03_6_more_than_three_tiles_rejected():
    tiles = [{"label": f"l{i}", "value": str(i)} for i in range(4)]
    with pytest.raises(ValidationError):
        ScanInsightNotifyRequest(**_valid(stat_tiles=tiles))


def test_t03_6_empty_title_rejected():
    with pytest.raises(ValidationError):
        ScanInsightNotifyRequest(**_valid(title=""))


# ─── T-03.1 · a valid structured finding persists with the right mapping ─────


@pytest.mark.asyncio
async def test_t03_1_records_structured_finding(db_session):
    payload = ScanInsightNotifyRequest(**_valid())
    finding = await record_scan_finding(db_session, payload)
    await db_session.commit()

    assert finding.source == "scan"
    assert finding.agent_id is None  # scan findings are agent-less
    assert finding.type == "risk"  # severity        → type
    assert finding.severity == "high"  # severity_level  → severity
    assert finding.title == "North sales down 18%"
    assert finding.viz_kind == "line"  # has a series → line
    assert len(finding.series) == 2
    assert finding.stat_tiles[0]["label"] == "Change"
    assert str(finding.space_id) == payload.space_id

    # Round-trips from the DB unchanged.
    row = await db_session.get(AgentFinding, finding.id)
    assert row is not None
    assert row.source == "scan"
    assert row.type == "risk"


# ─── T-03.4 · aggregate-only finding: empty series still persists ────────────


@pytest.mark.asyncio
async def test_t03_4_empty_series_persists(db_session):
    payload = ScanInsightNotifyRequest(
        **_valid(series=[], severity="opportunity", severity_level="low")
    )
    finding = await record_scan_finding(db_session, payload)
    await db_session.commit()

    assert finding.series == []
    assert finding.viz_kind == "big_number"  # no series → single number
    assert finding.type == "opportunity"
    assert finding.severity == "low"
