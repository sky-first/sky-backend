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


# ---------------------------------------------------------------------------
# User-facing backend strings
# ---------------------------------------------------------------------------

_MESSAGES: dict[str, dict[str, str]] = {
    "thinking": {
        "pt": "Pensando...",
        "en": "Thinking...",
    },
    "no_data_source": {
        "pt": "Nenhuma fonte de dados disponível para este chat.",
        "en": "No data source available for this chat.",
    },
    "no_data_source_agent": {
        "pt": "Nenhuma fonte de dados disponível. Adicione uma conexão na aba Editar, ou mude para o modo Contexto completo.",
        "en": "No data source available. Add a connection in the Edit tab, or switch to Full context mode.",
    },
    "unable_to_start_stream": {
        "pt": "Não foi possível iniciar o stream do chat.",
        "en": "Unable to start chat stream.",
    },
    "couldnt_understand": {
        "pt": "Não consegui entender essa pergunta. Tente reformulá-la.",
        "en": "I couldn't understand that question. Try rephrasing it.",
    },
    "how_can_i_help": {
        "pt": "Como posso ajudá-lo hoje?",
        "en": "How can I help you today?",
    },
    "how_can_i_help_data": {
        "pt": "Como posso ajudá-lo com seus dados?",
        "en": "How can I help you with your data?",
    },
    "empty_message": {
        "pt": "Mensagem vazia.",
        "en": "Empty message.",
    },
}


def get_message(key: str, locale: str | None = None) -> str:
    """Return a user-facing string for the given locale.

    Falls back to DEFAULT_LOCALE if the key or locale is not found.
    """
    resolved = normalize_locale(locale)
    bucket = _MESSAGES.get(key, {})
    return bucket.get(resolved) or bucket.get(DEFAULT_LOCALE) or key
