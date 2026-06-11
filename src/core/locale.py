"""Central locale contract for the Sky platform.

Single source of truth for:
- DEFAULT_LOCALE  — the platform default ('pt')
- normalize_locale — canonicalise user-supplied locale strings
- resolve_locale   — pick locale from request → user prefs → default
"""

from __future__ import annotations

DEFAULT_LOCALE = "pt"

_ALLOWED: frozenset[str] = frozenset({"en", "pt"})

_NORMALIZE_MAP: dict[str, str] = {
    "pt-br": "pt",
    "pt-pt": "pt",
    "en-us": "en",
    "en-gb": "en",
}


def normalize_locale(value: str | None) -> str:
    """Canonicalise a locale string to 'en' or 'pt'.

    Handles BCP-47 variants (pt-BR → pt, en-US → en).
    Unknown or empty values fall back to DEFAULT_LOCALE.
    """
    if not value:
        return DEFAULT_LOCALE
    low = value.lower()
    if low in _NORMALIZE_MAP:
        return _NORMALIZE_MAP[low]
    base = low.split("-")[0]
    return base if base in _ALLOWED else DEFAULT_LOCALE


def resolve_locale(request_locale: str | None, user: object | None) -> str:
    """Resolve the effective locale for a request.

    Priority: explicit request_locale > user.preferences["language"] > DEFAULT_LOCALE.
    """
    if request_locale:
        return normalize_locale(request_locale)
    if user is not None:
        prefs = getattr(user, "preferences", None) or {}
        if isinstance(prefs, dict):
            lang = prefs.get("language")
            if lang:
                return normalize_locale(lang)
    return DEFAULT_LOCALE
