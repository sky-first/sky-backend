"""Tests for the 'add finding to page' flow (Lucas QA 2026-05-30).

Before this work the FE "Add to page" CTA only sent the finding's
description as a text widget — chart/KPI viz was lost. The new endpoint
reads finding.viz_kind + finding.rows and constructs a typed Widget
(chart | kpi | table | insight) so the canvas renders the same view as
the Cockpit card.
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import (
    Agent,
    AgentFinding,
    AgentScope,
    AgentFrequency,
)
from src.models.page import Page
from src.models.widget import Widget
from src.services.agent_service import AgentService


# ─── helpers ──────────────────────────────────────────────────────────────


async def _make_personal_agent(db: AsyncSession, user_id) -> Agent:
    a = Agent(
        name="finding-source",
        archetype="custom",
        scope=AgentScope.PERSONAL,
        scope_id=str(user_id),
        status="active",
        frequency=AgentFrequency.DAILY,
        connection_ids=[],
        created_by=user_id,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _make_finding(
    db: AsyncSession,
    *,
    agent_id,
    viz_kind: str | None = "bar",
    rows: dict | None = None,
) -> AgentFinding:
    f = AgentFinding(
        agent_id=agent_id,
        type="insight",
        severity="medium",
        title="Revenue spike in Q4",
        description="Q4 revenue rose 12% vs Q3",
        confidence=0.83,
        viz_kind=viz_kind,
        rows=rows or {
            "columns": ["quarter", "revenue"],
            "data": [["Q3", 100], ["Q4", 112]],
        },
    )
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return f


async def _make_page(db: AsyncSession, owner_id) -> Page:
    p = Page(
        name="Target page",
        type="personal",
        color="#3b82f6",
        owner_id=owner_id,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


# ─── tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chart_finding_creates_chart_widget(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """A finding with viz_kind=bar should produce a chart widget with
    the rows + viz_kind preserved in data."""
    user = test_user_with_tokens["user"]
    agent = await _make_personal_agent(db_session, user.id)
    finding = await _make_finding(db_session, agent_id=agent.id, viz_kind="bar")
    page = await _make_page(db_session, user.id)

    svc = AgentService(db_session)
    result = await svc.add_finding_to_page(
        agent_id=agent.id,
        finding_id=finding.id,
        page_id=page.id,
        user=user,
    )

    assert result["widget_type"] == "chart"

    widget = (
        await db_session.execute(select(Widget).where(Widget.id == result["widget_id"]))
    ).scalar_one()
    assert widget.type == "chart"
    assert widget.page_id == page.id
    assert widget.source == "agent"
    assert widget.created_by_agent_id == agent.id
    # The chart spec the FE reads must include both viz_kind and rows.
    assert widget.data is not None
    assert widget.data["viz_kind"] == "bar"
    assert widget.data["rows"]["columns"] == ["quarter", "revenue"]
    assert widget.data["finding_id"] == str(finding.id)

    # The finding must remember which page it was added to.
    refreshed = (
        await db_session.execute(select(AgentFinding).where(AgentFinding.id == finding.id))
    ).scalar_one()
    assert refreshed.added_to_page_id == page.id


@pytest.mark.asyncio
async def test_kpi_finding_creates_kpi_widget(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """viz_kind=kpi must produce a kpi-type widget, not the default insight."""
    user = test_user_with_tokens["user"]
    agent = await _make_personal_agent(db_session, user.id)
    finding = await _make_finding(
        db_session,
        agent_id=agent.id,
        viz_kind="kpi",
        rows={"columns": ["total"], "data": [[123456]]},
    )
    page = await _make_page(db_session, user.id)

    svc = AgentService(db_session)
    result = await svc.add_finding_to_page(
        agent_id=agent.id,
        finding_id=finding.id,
        page_id=page.id,
        user=user,
    )

    assert result["widget_type"] == "kpi"
    widget = (
        await db_session.execute(select(Widget).where(Widget.id == result["widget_id"]))
    ).scalar_one()
    assert widget.type == "kpi"
    assert widget.data["rows"]["data"] == [[123456]]


@pytest.mark.asyncio
async def test_finding_must_belong_to_agent(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """A finding from a different agent must 404, not silently attach."""
    from fastapi import HTTPException

    user = test_user_with_tokens["user"]
    agent_a = await _make_personal_agent(db_session, user.id)
    agent_b = await _make_personal_agent(db_session, user.id)
    finding_for_b = await _make_finding(db_session, agent_id=agent_b.id)
    page = await _make_page(db_session, user.id)

    svc = AgentService(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.add_finding_to_page(
            agent_id=agent_a.id,
            finding_id=finding_for_b.id,
            page_id=page.id,
            user=user,
        )
    assert exc_info.value.status_code == 404
