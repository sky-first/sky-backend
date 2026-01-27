from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.models.ai import AIQuery
from src.models.connection import DataConnection
from src.models.dashboard import Dashboard, Widget
from src.models.space import Space, SpaceConnection
from src.models.user import User
from src.services.cache_warming_service import get_ai_cache_warm_candidates


@pytest.mark.asyncio
async def test_get_ai_cache_warm_candidates_basic(db_session):
    user_id = uuid4()
    space_id = uuid4()
    conn_id = uuid4()
    dashboard_id = uuid4()
    widget_id = uuid4()

    # Minimal user
    user = User(
        id=user_id,
        email="warm@example.com",
        password_hash="x",
        name="Warm User",
        role="user",
    )

    now = datetime.now(timezone.utc)

    # Connection + space mapping
    conn = DataConnection(
        id=conn_id,
        name="C1",
        connector_id="bigquery",
        status="active",
        config={},
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    space = Space(id=space_id, name="S1", created_by=user_id, created_at=now, updated_at=now)
    sc = SpaceConnection(space_id=space_id, connection_id=conn_id)

    # Dashboard + widget linked to connection
    dash = Dashboard(
        id=dashboard_id,
        name="D1",
        planet_id=uuid4(),  # not relevant for this test
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    w = Widget(
        id=widget_id,
        dashboard_id=dashboard_id,
        type="kpi",
        title="t",
        position={"x": 0, "y": 0},
        size={"width": 100, "height": 100},
        connection_id=conn_id,
        created_at=now,
        updated_at=now,
    )

    q1 = "Qual a receita de 2023?"
    q1_variant = "  qual   a   Receita de 2023?  "

    # Two completed queries (same normalized question) -> should group count=2
    aq1 = AIQuery(
        id=uuid4(),
        user_id=user_id,
        widget_id=widget_id,
        question=q1,
        status="completed",
        configure_data={"question": q1, "knowledge": [str(conn_id)]},
        created_at=now,
        updated_at=now - timedelta(minutes=5),
    )
    aq2 = AIQuery(
        id=uuid4(),
        user_id=user_id,
        widget_id=widget_id,
        question=q1_variant,
        status="completed",
        configure_data={"question": q1_variant, "knowledge": [str(conn_id)]},
        created_at=now,
        updated_at=now - timedelta(minutes=1),
    )

    db_session.add_all([user, conn, space, sc, dash, w, aq1, aq2])
    await db_session.commit()

    candidates = await get_ai_cache_warm_candidates(
        db_session,
        lookback_hours=48,
        top_n_per_connection=10,
        max_scan_rows=1000,
        max_total=50,
    )

    assert candidates
    c = candidates[0]
    assert c.space_id == str(space_id)
    assert c.connection_id == str(conn_id)
    assert c.count == 2
    # newest variant should win
    assert " ".join(c.question.strip().lower().split()).startswith("qual a receita")
