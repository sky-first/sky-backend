"""``UserResponse`` must surface ``is_sky_operator`` so the platform
profile dropdown can show the "Console" link only to Sky engineers.

The flag must default to False — every customer user is non-operator
unless explicitly flipped by the SSO auto-promote (Sky-team domain)
or by an explicit grant.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.models.user import User
from src.schemas.user import UserResponse


def _make_user(**overrides) -> User:
    base = dict(
        id=uuid.uuid4(),
        email="someone@example.com",
        password_hash="x",
        name="Some One",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=False,
        onboarding_version=0,
        preferences={},
        status="offline",
        is_demo=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    u = User(**base)
    # ``needs_onboarding`` is a computed attribute on the schema, not a
    # column on the model — pin it on the instance so ``from_attributes``
    # finds it during validation.
    u.needs_onboarding = False  # type: ignore[attr-defined]
    return u


class TestUserResponseExposesSkyOperator:
    def test_default_false_for_external_user(self) -> None:
        user = _make_user(
            email="customer@gbtsolutions.pt",
            is_sky_operator=False,
        )
        body = UserResponse.model_validate(user).model_dump()
        assert body["is_sky_operator"] is False

    def test_true_for_sky_operator(self) -> None:
        user = _make_user(
            email="lucas.ventura@skyfirstlabs.com",
            is_sky_operator=True,
        )
        body = UserResponse.model_validate(user).model_dump()
        assert body["is_sky_operator"] is True

    def test_field_is_explicit_not_inferred(self) -> None:
        """If the field is missing from the source, default should keep
        the surface false — never leak operator on accidental missing
        data."""
        body = UserResponse(
            id=uuid.uuid4(),
            email="x@x.com",
            name="x",
            role="user",
            email_verified=True,
            has_completed_onboarding=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ).model_dump()
        assert body["is_sky_operator"] is False
