"""BE-08 · Chat SSE contract — T-08.1…T-08.6.

Pins the locked mobile SSE contract: every AI-engine event type is mapped to
exactly one client shape (or dropped), debug/unknown events never leak, and
idle connections get a heartbeat.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.schemas.chat_stream import (
    CLIENT_EVENT_TYPES,
    HEARTBEAT_COMMENT,
    chunk_event,
    done_event,
    error_event,
    meta_event,
    normalize_event,
    parse_sse_data_line,
    progress_event,
    sse,
    with_heartbeat,
)


# ─── T-08.1 · every engine event maps to the right locked shape ─────────────
def test_t08_1_engine_events_normalize():
    assert normalize_event({"type": "progress", "stage": "specialist", "message": "x"}) == {
        "type": "progress",
        "stage": "specialist",
        "message": "x",
    }
    assert normalize_event({"type": "chunk", "content": "hello"}) == {
        "type": "chunk",
        "content": "hello",
    }
    # engine's full-answer variant folds into chunk
    assert normalize_event({"type": "answer", "text": "final"}) == {
        "type": "chunk",
        "content": "final",
    }
    assert normalize_event({"type": "meta", "meta": {"lang": "pt"}, "data_sample": [1]}) == {
        "type": "meta",
        "meta": {"lang": "pt"},
        "data_sample": [1],
    }
    assert normalize_event({"type": "error", "message": "boom"}) == {
        "type": "error",
        "message": "boom",
    }


# ─── T-08.2 · debug / terminal / unknown events are dropped ─────────────────
@pytest.mark.parametrize(
    "raw",
    [
        {"type": "done"},  # endpoint owns the single terminal done
        {"type": "sql_generated", "sql": "SELECT 1"},  # debug — must not leak
        {"type": "datasets_selected", "datasets": ["a"]},  # debug — must not leak
        {"type": "totally_new_thing", "x": 1},  # unknown → dropped
        {"no_type": True},
        "not a dict",
        None,
    ],
)
def test_t08_2_dropped_events(raw):
    assert normalize_event(raw) is None


# ─── T-08.3 · missing fields degrade to safe defaults ───────────────────────
def test_t08_3_missing_fields_default():
    assert normalize_event({"type": "progress"}) == {
        "type": "progress",
        "stage": "",
        "message": "",
    }
    assert normalize_event({"type": "chunk"}) == {"type": "chunk", "content": ""}
    assert normalize_event({"type": "meta"}) == {
        "type": "meta",
        "meta": {},
        "data_sample": [],
    }


# ─── T-08.4 · raw SSE line parsing is robust ────────────────────────────────
def test_t08_4_parse_sse_line():
    assert parse_sse_data_line('data: {"type": "chunk", "content": "hi"}') == {
        "type": "chunk",
        "content": "hi",
    }
    assert parse_sse_data_line(": keepalive") is None  # comment
    assert parse_sse_data_line("") is None
    assert parse_sse_data_line("   ") is None
    assert parse_sse_data_line("data: not-json") is None
    assert parse_sse_data_line('data: "a-string"') is None  # valid JSON, not an object
    # bare JSON without the data: prefix still parses (defensive)
    assert parse_sse_data_line('{"type": "done"}') == {"type": "done"}


# ─── T-08.5 · a full engine stream yields only the locked contract ──────────
def test_t08_5_end_to_end_sequence():
    # A realistic engine stream, including debug events that must be stripped.
    engine_lines = [
        'data: {"type": "progress", "stage": "orchestrator", "message": "..."}',
        'data: {"type": "datasets_selected", "datasets": ["sales"]}',  # drop
        'data: {"type": "sql_generated", "sql": "SELECT 1"}',  # drop
        'data: {"type": "chunk", "content": "Rev "}',
        'data: {"type": "chunk", "content": "is up."}',
        'data: {"type": "meta", "meta": {"lang": "en"}, "data_sample": []}',
        'data: {"type": "done"}',  # engine done — dropped; endpoint owns it
        ": keepalive",  # a stray comment
        "",  # blank
    ]
    out = [normalize_event(parse_sse_data_line(l)) for l in engine_lines]
    out = [e for e in out if e is not None]

    types = [e["type"] for e in out]
    assert types == ["progress", "chunk", "chunk", "meta"]  # debug + done stripped
    # every surviving event is inside the locked contract
    assert all(e["type"] in CLIENT_EVENT_TYPES for e in out)


# ─── builder invariants: everything built is a valid client event ───────────
def test_builders_are_in_contract():
    events = [
        progress_event("starting", "thinking"),
        chunk_event("x"),
        meta_event({"a": 1}, [2]),
        error_event("nope"),
        done_event(),
    ]
    for e in events:
        assert e["type"] in CLIENT_EVENT_TYPES
        frame = sse(e)
        assert frame.startswith("data: ") and frame.endswith("\n\n")
        # round-trips as JSON
        assert json.loads(frame[len("data: ") :].strip())["type"] == e["type"]


# ─── T-08.6 · heartbeat is injected on idle, items preserved and ordered ────
@pytest.mark.asyncio
async def test_t08_6_heartbeat_on_idle():
    async def _slow_source():
        yield "data: a\n\n"
        await asyncio.sleep(0.05)  # idle gap >> interval → forces a heartbeat
        yield "data: b\n\n"

    out = []
    async for frame in with_heartbeat(_slow_source(), interval_seconds=0.01):
        out.append(frame)

    assert "data: a\n\n" in out and "data: b\n\n" in out  # items preserved
    assert HEARTBEAT_COMMENT in out  # idle gap produced a heartbeat
    assert out.index("data: a\n\n") < out.index("data: b\n\n")  # order kept


@pytest.mark.asyncio
async def test_heartbeat_passes_through_when_never_idle():
    async def _fast_source():
        yield "data: a\n\n"
        yield "data: b\n\n"

    out = [frame async for frame in with_heartbeat(_fast_source(), interval_seconds=5)]
    assert out == ["data: a\n\n", "data: b\n\n"]  # no spurious heartbeats
