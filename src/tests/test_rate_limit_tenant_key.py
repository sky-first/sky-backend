from __future__ import annotations

from src.rate_limit.core import resolve_tenant_key


def test_resolve_tenant_key_single_crew() -> None:
    assert (
        resolve_tenant_key(
            user_id="u1",
            crew_ids=["c1"],
            space_id="s1",
            is_personal=False,
        )
        == "crew:c1"
    )


def test_resolve_tenant_key_multiple_crews_prefers_space() -> None:
    assert (
        resolve_tenant_key(
            user_id="u1",
            crew_ids=["c1", "c2"],
            space_id="s1",
            is_personal=False,
        )
        == "space:s1"
    )


def test_resolve_tenant_key_multiple_crews_no_space_falls_back_to_personal() -> None:
    assert (
        resolve_tenant_key(
            user_id="u1",
            crew_ids=["c1", "c2"],
            space_id=None,
            is_personal=False,
        )
        == "personal:u1"
    )


def test_resolve_tenant_key_no_crews_personal() -> None:
    assert (
        resolve_tenant_key(
            user_id="u1",
            crew_ids=[],
            space_id="s1",
            is_personal=True,
        )
        == "personal:u1"
    )


def test_resolve_tenant_key_no_crews_space() -> None:
    assert (
        resolve_tenant_key(
            user_id="u1",
            crew_ids=[],
            space_id="s1",
            is_personal=False,
        )
        == "space:s1"
    )


def test_resolve_tenant_key_no_context_falls_back_to_user() -> None:
    assert (
        resolve_tenant_key(
            user_id="u1",
            crew_ids=[],
            space_id=None,
            is_personal=False,
        )
        == "user:u1"
    )
