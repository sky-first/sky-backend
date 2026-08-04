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

# Personal email providers — blocked so the lead-gen pipeline only
# captures *work* addresses. Same-domain grouping (item D) keys off
# the email domain to bind colleagues to one demo Space, which only
# makes sense if the domain reflects the company. Allowing gmail.com
# would silently merge unrelated visitors into a single Space.
#
# Not exhaustive — the goal is to filter ~95% of casual personal
# signups, not to be bulletproof. Strong-validation should use a
# vendor (Clearbit / ZeroBounce); out of scope for the public demo.
_PERSONAL_EMAIL_DOMAINS = frozenset(
    {
        # Big four
        "gmail.com",
        "outlook.com",
        "hotmail.com",
        "yahoo.com",
        # Apple
        "icloud.com",
        "me.com",
        "mac.com",
        # Microsoft variants
        "live.com",
        "msn.com",
        "outlook.com.br",
        "hotmail.com.br",
        # Yahoo variants
        "yahoo.com.br",
        "ymail.com",
        "rocketmail.com",
        # Other big providers
        "aol.com",
        "gmx.com",
        "gmx.net",
        "mail.com",
        "zoho.com",
        # Privacy-focused
        "protonmail.com",
        "proton.me",
        "tutanota.com",
        "tuta.io",
        "fastmail.com",
        # PT-BR popular
        "uol.com.br",
        "bol.com.br",
        "ig.com.br",
        "globo.com",
        "terra.com.br",
        # Education / generic free
        "edu.com",
        "qq.com",
        "163.com",
        "126.com",
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
                "Please use your work email address. Throwaway email "
                "providers are not accepted for the demo."
            )
        if domain in _PERSONAL_EMAIL_DOMAINS:
            raise ValueError(
                "Please use your work email address. The public demo "
                "is for evaluating SKY at your company; personal email "
                "providers (gmail/outlook/etc) are not accepted. If "
                "your company uses a personal-email-style domain, "
                "contact us at lucas@skyfirstlabs.com to whitelist it."
            )
        # @skyfirstlabs.com is the engineering Workspace. The demo path
        # creates a *local* user with no Google verification — accepting
        # this domain would let anyone seed a fake "lucas@skyfirstlabs.com"
        # in our DB and contaminate audit logs, even though the real
        # Console guard (``is_sky_team_member``) still requires
        # ``is_sky_operator=true`` to grant access. Defence in depth:
        # refuse the demo signup outright so the impersonation never
        # gets a row.
        if domain == "skyfirstlabs.com":
            raise ValueError(
                "This domain is reserved for SkyFirst engineering accounts; "
                "demo sign-ups must use a different work email. Sky team "
                "members should sign in via the engineering SSO instead."
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
