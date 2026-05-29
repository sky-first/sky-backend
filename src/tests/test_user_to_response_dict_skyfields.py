"""``user_to_response_dict`` must surface the Sky-platform fields.

The dict is what the SSO callback and password-login responses run
through ``UserResponse.model_validate(...)`` on the way back to the
browser. Without these two fields the FE user-store hydrates with
``is_sky_operator`` undefined and the platform profile dropdown
silently hides the Console shortcut from engineers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.models.user import User
from src.services.auth_service import user_to_response_dict


def _user(**overrides) -> User:
    base = dict(
        id=uuid.uuid4(),
        email="x@x.com",
        password_hash="x",
        name="X",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=False,
        sky_role=None,
        onboarding_version=0,
        preferences={},
        status="offline",
        is_demo=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return User(**base)


class TestUserToResponseDictSkyFields:
    def test_customer_user_carries_false_and_null(self) -> None:
        u = _user(email="customer@gbtsolutions.pt")
        d = user_to_response_dict(u)
        assert d["is_sky_operator"] is False
        assert d["sky_role"] is None

    def test_sky_operator_owner_carries_through(self) -> None:
        u = _user(
            email="lucas.ventura@skyfirstlabs.com",
            is_sky_operator=True,
            sky_role="owner",
        )
        d = user_to_response_dict(u)
        assert d["is_sky_operator"] is True
        assert d["sky_role"] == "owner"

    def test_missing_attrs_default_safely(self) -> None:
        """Defensive: if the source object somehow lacks the attribute
        we coerce to the safe defaults (False / None) so a corrupt or
        legacy User row never leaks operator on accident."""

        class _BareUser:
            id = uuid.uuid4()
            email = "x@x.com"
            name = "x"
            avatar = None
            role = "user"
            is_demo = False
            demo_expires_at = None
            email_verified = True
            email_verified_at = None
            onboarding_step = 0
            onboarding_version = 0
            has_completed_onboarding = True
            selected_domain = None
            preferences = {}
            last_login_at = None
            last_active_at = None
            status = "offline"
            created_at = datetime.now(timezone.utc)
            updated_at = datetime.now(timezone.utc)

        bare = _BareUser()
        d = user_to_response_dict(bare)  # type: ignore[arg-type]
        assert d["is_sky_operator"] is False
        assert d["sky_role"] is None
