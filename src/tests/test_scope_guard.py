"""Unit tests for src.core.scope_guard.

Personal context is a read-only aggregate; mutations must target a
Space or Crew. The FE hides the affordance, but the guard is what stops
attackers/scripts from creating Personal-owned resources by hitting
the API directly.
"""

from __future__ import annotations

import pytest

from src.core.exceptions import ForbiddenError
from src.core.scope_guard import (
    assert_not_personal_flag,
    assert_not_personal_scope,
)


class TestAssertNotPersonalScope:
    def test_none_is_allowed(self):
        # Endpoints where scope is optional must not raise on None.
        assert_not_personal_scope(None) is None

    def test_space_scope_allowed(self):
        assert_not_personal_scope("space") is None

    def test_crew_scope_allowed(self):
        assert_not_personal_scope("crew") is None

    def test_org_scope_allowed(self):
        assert_not_personal_scope("org") is None

    def test_personal_lowercase_blocked(self):
        with pytest.raises(ForbiddenError) as exc:
            assert_not_personal_scope("personal")
        assert "Personal" in str(exc.value)

    def test_personal_uppercase_blocked(self):
        with pytest.raises(ForbiddenError):
            assert_not_personal_scope("PERSONAL")

    def test_arbitrary_string_allowed(self):
        # Guard is a denylist for "personal" — unknown strings flow
        # through to whatever validation the endpoint performs next.
        assert_not_personal_scope("garbage") is None


class TestAssertNotPersonalFlag:
    def test_false_allowed(self):
        assert_not_personal_flag(False) is None

    def test_none_allowed(self):
        assert_not_personal_flag(None) is None

    def test_true_blocked(self):
        with pytest.raises(ForbiddenError):
            assert_not_personal_flag(True)

    def test_truthy_value_blocked(self):
        with pytest.raises(ForbiddenError):
            assert_not_personal_flag(1)  # type: ignore[arg-type]
