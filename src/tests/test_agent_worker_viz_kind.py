"""agent_worker._infer_viz_kind — viz hint heuristic unit tests.

Sprint 1.17 round 7. The worker picks a viz_kind for every finding it
emits so the Pulse FE renders a coherent card variant + matching widget
kind on "Add to page". Round 7 retired the legacy strings ("delta",
"sparkline", "text") in favour of canonical CHART_REGISTRY kinds. This
file exercises the new heuristic:

    rows w/ 1 numeric + finite categories → "pie"
    rows w/ 1 numeric (continuous)        → "line"
    rows w/ ≥2 numeric columns            → "bar"
    title or answer carries "+N%"/"-N%"   → "big_number"
    short numeric answer                  → "kpi"
    otherwise                             → "callout"
"""

from __future__ import annotations

from src.workers.agent_worker import _infer_viz_kind


def test_big_number_from_percent_in_title():
    assert (
        _infer_viz_kind(
            response={"title": "CAC down 22%", "data": None},
            answer="campaign efficiency improved",
        )
        == "big_number"
    )


def test_big_number_from_percent_in_answer():
    assert (
        _infer_viz_kind(
            response=None,
            answer="Revenue is +18% over last quarter.",
        )
        == "big_number"
    )


def test_pie_from_finite_categories():
    rows = {
        "columns": ["channel", "share"],
        "data": [
            ["organic", 47],
            ["paid", 28],
            ["referral", 15],
            ["direct", 10],
        ],
    }
    assert (
        _infer_viz_kind(
            response={"title": "Channel share", "data": rows},
            answer="distribution",
        )
        == "pie"
    )


def test_line_from_continuous_single_numeric():
    # 9 distinct hour categories → exceeds the pie cap of 8 → line.
    rows = {
        "columns": ["hour", "p95"],
        "data": [
            ["00", 180], ["04", 220], ["08", 260], ["12", 300],
            ["16", 340], ["20", 420], ["24", 520], ["28", 540],
            ["32", 560],
        ],
    }
    assert (
        _infer_viz_kind(
            response={"title": "p95 latency by hour", "data": rows},
            answer="p95 trend",
        )
        == "line"
    )


def test_bar_from_multi_numeric():
    rows = {
        "columns": ["segment", "mrr", "headcount"],
        "data": [["enterprise", 45000, 12], ["mid-market", 22000, 6]],
    }
    assert (
        _infer_viz_kind(
            response={"title": "Segment breakdown", "data": rows},
            answer="segments",
        )
        == "bar"
    )


def test_kpi_short_numeric_answer():
    assert (
        _infer_viz_kind(
            response=None,
            answer="Net revenue retention stands at 118.",
        )
        == "kpi"
    )


def test_callout_fallback_when_no_signal():
    assert _infer_viz_kind(response=None, answer="") == "callout"
    assert (
        _infer_viz_kind(
            response={"title": "Audit", "data": None},
            answer="Cross-domain audit consolidates Revenue Pulse, Customer Health Watch and Operations Radar over the last seven days. Net growth is healthy. Top-five accounts approach the concentration guardrail."
            ,
        )
        == "callout"
    )
