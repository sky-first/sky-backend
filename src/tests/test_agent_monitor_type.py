"""Tests for explicit monitor_type validation — Phase 4.2.

Regression pinning for the tuple of supported values + the legacy
alias rules. If someone changes the set (e.g. drops `datasource`
thinking it's dead) these tests surface the impact on every call-site.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.agent import (
    MONITOR_TYPE_VALUES,
    AgentCreate,
    AgentUpdate,
)


# ─── canonical + legacy ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value",
    ["question", "sql", "scan", "datasource", "context", "insight"],
)
def test_agent_create_accepts_known_monitor_types(value: str):
    a = AgentCreate(
        name="X",
        scope_id=str(uuid4()),
        monitor_type=value,
    )
    assert a.monitor_type == value


def test_agent_create_default_is_question():
    a = AgentCreate(name="X", scope_id=str(uuid4()))
    assert a.monitor_type == "question"


def test_monitor_type_is_normalised_to_lowercase():
    a = AgentCreate(name="X", scope_id=str(uuid4()), monitor_type="SQL")
    assert a.monitor_type == "sql"


def test_monitor_type_is_trimmed():
    a = AgentCreate(name="X", scope_id=str(uuid4()), monitor_type="  scan  ")
    assert a.monitor_type == "scan"


# ─── rejection ────────────────────────────────────────────────────────────
def test_agent_create_rejects_unknown_monitor_type():
    with pytest.raises(ValidationError) as ei:
        AgentCreate(name="X", scope_id=str(uuid4()), monitor_type="whatever")
    assert "monitor_type must be one of" in str(ei.value)


def test_update_rejects_unknown_monitor_type():
    with pytest.raises(ValidationError):
        AgentUpdate(monitor_type="lol")


# ─── update with None is fine ─────────────────────────────────────────────
def test_update_with_none_monitor_type_passes():
    u = AgentUpdate(monitor_type=None)
    assert u.monitor_type is None


def test_update_with_known_monitor_type_passes():
    u = AgentUpdate(monitor_type="scan")
    assert u.monitor_type == "scan"


# ─── the set itself ───────────────────────────────────────────────────────
def test_the_supported_set_is_exactly_these_values():
    """If this test fails the frontend / SDK contract changed —
    bump the API version and update the public docs first."""
    assert MONITOR_TYPE_VALUES == (
        "question", "sql", "scan", "datasource", "context", "insight",
    )
