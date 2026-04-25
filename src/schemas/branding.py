"""Pydantic schemas for tenant-wide branding."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# The FE picker offers exactly these fonts. Keep in sync with
# ``sky-poc-frontend/src/store/ui-config-store.ts`` — a wider set
# would silently render Geist on the user's machine since we don't
# bundle every weight.
FontFamily = Literal["geist", "inter", "dm-sans", "plus-jakarta", "outfit"]


class BrandingConfig(BaseModel):
    """Public response shape — what every authenticated user sees."""

    primary_color: str = Field(default="#1e3a5f", description="3- or 6-digit hex (with or without leading #)")
    radius: int = Field(default=10, ge=0, le=32)
    font_family: FontFamily = "geist"
    logo_url: Optional[str] = None
    company_name: str = Field(default="SkyFirstLabs", min_length=1, max_length=255)

    # Read-only metadata — included so the FE can show "last edited by X
    # at Y" in the Branding panel.
    updated_at: Optional[datetime] = None


class BrandingUpdate(BaseModel):
    """Owner-only write shape. All fields optional so the FE can patch."""

    primary_color: Optional[str] = None
    radius: Optional[int] = Field(default=None, ge=0, le=32)
    font_family: Optional[FontFamily] = None
    # ``logo_url`` accepts both ``data:image/...;base64,...`` URLs (small
    # uploaded files) and absolute https URLs. We cap length at 1 MB worth
    # of base64 to prevent multi-MB blobs from saturating the JSON column.
    logo_url: Optional[str] = Field(default=None, max_length=1_400_000)
    company_name: Optional[str] = Field(default=None, min_length=1, max_length=255)

    @field_validator("primary_color")
    @classmethod
    def _validate_hex(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = v.strip()
        if not s.startswith("#"):
            s = f"#{s}"
        # Accept #abc and #aabbcc.
        body = s[1:]
        if len(body) not in (3, 6) or any(c not in "0123456789abcdefABCDEF" for c in body):
            raise ValueError("primary_color must be a 3- or 6-digit hex string")
        return s
