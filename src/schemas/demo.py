"""Public demo signup schemas (Cenário B).

The /demo/signup endpoint is the only path a non-SSO visitor has into
the platform. Every field below is validated again on the server to
keep the path safe even if the FE form is bypassed by curl.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from src.schemas.user import UserResponse


# Throwaway / one-time-mailbox domains we don't want for demo lead
# capture. Block list — short, deliberately. We're not chasing edge
# providers, just stopping the obvious ones from polluting the pipeline.
_BLOCKED_DOMAINS = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "tempmail.com",
        "10minutemail.com",
        "throwaway.email",
        "trashmail.com",
        "yopmail.com",
        "discard.email",
        "fakeinbox.com",
        "getnada.com",
        "maildrop.cc",
        "sharklasers.com",
    }
)

_NAME_RE = re.compile(r"^[\w\s\-'.]{2,80}$", re.UNICODE)
_COMPANY_RE = re.compile(r"^[\w\s\-&.,'/]{2,120}$", re.UNICODE)


class DemoSignupRequest(BaseModel):
    """Form payload from demo.skyfirstlabs.com landing page."""

    name: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    company: str = Field(..., min_length=2, max_length=120)
    role: Optional[str] = Field(default=None, max_length=80)
    turnstile_token: str = Field(
        ...,
        min_length=1,
        description="Cloudflare Turnstile cf-turnstile-response token from the form.",
    )

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        v = v.strip()
        if not _NAME_RE.match(v):
            raise ValueError(
                "Name must be 2-80 characters, letters/spaces/hyphens/apostrophes only."
            )
        return v

    @field_validator("company")
    @classmethod
    def _company_shape(cls, v: str) -> str:
        v = v.strip()
        if not _COMPANY_RE.match(v):
            raise ValueError("Company must be 2-120 readable characters.")
        return v

    @field_validator("email")
    @classmethod
    def _email_not_throwaway(cls, v: str) -> str:
        domain = v.split("@", 1)[1].lower() if "@" in v else ""
        if domain in _BLOCKED_DOMAINS:
            raise ValueError(
                "Please use your work email address. Throwaway email providers are not accepted for the demo."
            )
        return v


class DemoSignupResponse(BaseModel):
    """Issues a JWT the FE stores like a normal login response."""

    access_token: str
    refresh_token: str
    expires_in: int
    user: UserResponse
    space_id: str
    demo_expires_at: str  # ISO-8601 UTC
    is_returning: bool = False  # true when same email already had a sandbox
