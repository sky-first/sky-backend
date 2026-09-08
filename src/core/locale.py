"""Central locale contract for the Sky platform.

Single source of truth for:
- DEFAULT_LOCALE  — the platform default ('pt')
- normalize_locale — canonicalise user-supplied locale strings
- resolve_locale   — pick locale from request → user prefs → default
"""

from __future__ import annotations

DEFAULT_LOCALE = "pt"

# ⚠️ O espanhol faltava aqui, e o que acontecia era pior do que ficar em
# inglês: `normalize_locale("es")` caía no DEFAULT_LOCALE, que é `pt`. Um
# cliente espanhol recebia **português**.
#
# A app e a web já falam espanhol há muito; este ficheiro é que não sabia.
# Duas listas de línguas em serviços diferentes divergem em silêncio — e a
# que mente é sempre a que alguém se esqueceu de actualizar.
_ALLOWED: frozenset[str] = frozenset({"en", "pt", "es"})

_NORMALIZE_MAP: dict[str, str] = {
    "pt-br": "pt",
    "pt-pt": "pt",
    "en-us": "en",
    "en-gb": "en",
    "es-es": "es",
    "es-mx": "es",
    "es-ar": "es",
    "es-419": "es",
}


def normalize_locale(value: str | None) -> str:
    """Canonicalise a locale string to 'en', 'pt' or 'es'.

    Handles BCP-47 variants (pt-BR → pt, en-US → en, es-MX → es).
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
    # ⚠️ **Isto estava em português do Brasil.**
    #
    # «Pensando…», «Mencionaram você», «na aba Editar», «uma conexão». A web
    # e a app já tinham sido corrigidas; este catálogo é a cópia do servidor
    # e ficou para trás. E não é decorativo: quando o cliente não conhece a
    # chave, é ESTE texto que aparece no ecrã (ver NOTIFICATION_KEYS).
    "thinking": {
        "pt": "A pensar…",
        "en": "Thinking...",
        "es": "Pensando…",
    },
    # Sem dados no projeto — a frase depende de **quem** pergunta.
    #
    # Havia uma só, em inglês, dentro do `ai_service`: "Connect a data source
    # from the toolbar". Dita a um member, manda-o fazer uma coisa que a
    # plataforma lhe recusa (cunhar ligações é decisão do cliente), e a pessoa
    # fica num beco: a única instrução no ecrã é o que não pode fazer.
    #
    # O mesmo defeito estava no frontend e foi corrigido a 19/08; o backend
    # tinha a sua própria cópia.
    "space_has_no_data_can_connect": {
        "pt": "Este projeto ainda não tem dados. Ligue uma fonte na barra de "
        "ferramentas (Fontes → Ligar) e eu respondo com base nela.",
        "en": "This project has no data yet. Connect a source from the "
        "toolbar (Sources → Connect) and I'll answer from it.",
        "es": "Este proyecto aún no tiene datos. Conecte una fuente en la "
        "barra de herramientas (Fuentes › Conectar) y le respondo con ella.",
    },
    "space_has_no_data_ask_access": {
        "pt": "Este projeto ainda não tem dados. Peça acesso em "
        "Definições › Pedir dados e um administrador trata do resto.",
        "en": "This project has no data yet. Ask for access in "
        "Settings › Request data and an admin takes it from there.",
        "es": "Este proyecto aún no tiene datos. Pida acceso en "
        "Ajustes › Solicitar datos y un administrador se encarga del resto.",
    },
    "no_data_source": {
        "pt": "Nenhuma fonte de dados disponível para esta conversa.",
        "en": "No data source available for this chat.",
        "es": "No hay ninguna fuente de datos disponible para esta conversación.",
    },
    "no_data_source_agent": {
        "pt": "Nenhuma fonte de dados disponível. Acrescente uma ligação no separador Editar, ou mude para o modo Contexto completo.",
        "en": "No data source available. Add a connection in the Edit tab, or switch to Full context mode.",
        "es": "No hay ninguna fuente de datos disponible. Añada una conexión en la pestaña Editar, o cambie al modo Contexto completo.",
    },
    "unable_to_start_stream": {
        "pt": "Não foi possível iniciar a conversa.",
        "en": "Unable to start chat stream.",
        "es": "No se ha podido iniciar la conversación.",
    },
    "couldnt_understand": {
        "pt": "Não percebi essa pergunta. Tente reformulá-la.",
        "en": "I couldn't understand that question. Try rephrasing it.",
        "es": "No he entendido esa pregunta. Pruebe a reformularla.",
    },
    "how_can_i_help": {
        "pt": "Em que posso ajudar hoje?",
        "en": "How can I help you today?",
        "es": "¿En qué puedo ayudarle hoy?",
    },
    "how_can_i_help_data": {
        "pt": "Em que posso ajudar com os seus dados?",
        "en": "How can I help you with your data?",
        "es": "¿En qué puedo ayudarle con sus datos?",
    },
    "empty_message": {
        "pt": "Mensagem vazia.",
        "en": "Empty message.",
        "es": "Mensaje vacío.",
    },
    # ── Notifications — localized at creation time by the recipient's
    # locale. Strings carry {placeholders} resolved via str.format() at
    # the callsite (get_message itself does not interpolate).
    "notif_comment_mention_title": {
        "pt": "Foi mencionado num comentário",
        "en": "You were mentioned in a comment",
        "es": "Le han mencionado en un comentario",
    },
    "notif_comment_mention_desc": {
        "pt": "Mencionaram-no: {snippet}…",
        "en": "Someone mentioned you: {snippet}...",
        "es": "Alguien le ha mencionado: {snippet}…",
    },
    # Alguem escreveu numa conversa em que participo.
    #
    # Nao e a mesma coisa que uma mencao: a mencao e dirigida a mim, isto e "a
    # conversa mexeu-se". O texto tem de dizer QUEM escreveu, porque numa
    # conversa de tres pessoas saber o autor decide se vale a pena abrir agora.
    "notif_conversation_reply_title": {
        "pt": "{autor} escreveu em «{conversa}»",
        "en": "{autor} wrote in “{conversa}”",
        "es": "{autor} ha escrito en «{conversa}»",
    },
    "notif_conversation_reply_desc": {
        "pt": "{snippet}",
        "en": "{snippet}",
        "es": "{snippet}",
    },
    # «espaço» era o nome antigo. Hoje chama-se **projeto** em toda a
    # aplicação — menos aqui, que era o que a app mostrava no ecrã.
    "notif_space_added_title": {
        "pt": "Foi adicionado ao projeto «{space}»",
        "en": "You were added to the project “{space}”",
        "es": "Le han añadido al proyecto «{space}»",
    },
    "notif_space_added_desc": {
        "pt": "{actor} acrescentou-o a este projeto",
        "en": "{actor} added you to this project",
        "es": "{actor} le ha añadido a este proyecto",
    },
    # ── Equipas e páginas ────────────────────────────────────────────────
    #
    # Estas duas eram montadas com um f-string em inglês dentro do
    # `crew_service` e do `page_service` — «You were added to crew 'X'» —
    # e sem chave nenhuma. Num produto em português.
    "notif_crew_added_title": {
        "pt": "Foi adicionado à equipa «{crew}»",
        "en": "You were added to the team “{crew}”",
        "es": "Le han añadido al equipo «{crew}»",
    },
    "notif_crew_added_desc": {
        "pt": "{actor} acrescentou-o como {role}",
        "en": "{actor} added you as {role}",
        "es": "{actor} le ha añadido como {role}",
    },
    "notif_page_added_title": {
        "pt": "Foi adicionado a «{page}»",
        "en": "You were added to “{page}”",
        "es": "Le han añadido a «{page}»",
    },
    "notif_page_added_desc": {
        "pt": "{actor} acrescentou-o como {role}",
        "en": "{actor} added you as {role}",
        "es": "{actor} le ha añadido como {role}",
    },

}


NOTIFICATION_KEYS: frozenset[str] = frozenset({
    "notif_comment_mention_title",
    "notif_comment_mention_desc",
    "notif_conversation_reply_title",
    "notif_conversation_reply_desc",
    "notif_space_added_title",
    "notif_space_added_desc",
    "notif_crew_added_title",
    "notif_crew_added_desc",
    "notif_page_added_title",
    "notif_page_added_desc",
})

# DB migration that adds the columns consumed by these keys: notif_i18n_keys_20260612


def get_message(key: str, locale: str | None = None) -> str:
    """Return a user-facing string for the given locale.

    Falls back to DEFAULT_LOCALE if the key or locale is not found.
    """
    resolved = normalize_locale(locale)
    bucket = _MESSAGES.get(key, {})
    return bucket.get(resolved) or bucket.get(DEFAULT_LOCALE) or key
