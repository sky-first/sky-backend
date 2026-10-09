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
    # ── Falhas da conversa ──────────────────────────────────────────
    #
    # Sete ramos do `ai_service` classificavam a excepção e só UM pedia a
    # frase a este catálogo. Os outros seis estavam cravados em inglês, e
    # apareciam numa plataforma em português a dizer «The AI service
    # rejected the request. Please retry or open a ticket.»
    #
    # Essa frase tinha um segundo problema: mandava abrir um pedido de
    # apoio e não havia botão nenhum para o abrir. Agora não promete o
    # que o ecrã não dá.
    # O agente correu e nao devolveu nada. Era «Run produced no output
    # (nome)», em ingles, e aparecia na lista de descobertas.
    "agent_run_no_output": {
        "pt": "a corrida não devolveu nada",
        "en": "the run produced no output",
        "es": "la ejecución no ha devuelto nada",
    },
    # ── O que o agente diz quando não tem nada a dizer ──────────────
    #
    # Estavam cravadas em português no `agent_worker`, como constantes.
    # Um agente corre sozinho e não sabe quem o vai ler — e o mesmo
    # agente é lido pelo Lucas em português e por um cliente de Badajoz
    # em castelhano. O worker continua a escrever o texto no `content`
    # (é o que se vê sem mais nada), mas guarda a chave ao lado para o
    # cliente poder trocar a língua na altura de mostrar.
    "agent_nothing_to_report": {
        "pt": (
            "Olhei agora e não há nada a assinalar. Volto a olhar na próxima "
            "corrida e só falo se encontrar alguma coisa que valha a pena."
        ),
        "en": (
            "I've just looked and there's nothing to flag. I'll look again on "
            "the next run and will only speak up if I find something worth it."
        ),
        "es": (
            "Acabo de mirar y no hay nada que señalar. Volveré a mirar en la "
            "próxima ejecución y solo hablaré si encuentro algo que merezca la pena."
        ),
    },
    "agent_could_not_run": {
        "pt": (
            "Não consegui responder desta vez — foi um problema nosso, não dos "
            "seus dados. Vou tentar outra vez na próxima corrida."
        ),
        "en": (
            "I couldn't answer this time — that was a problem on our side, not "
            "with your data. I'll try again on the next run."
        ),
        "es": (
            "No he podido responder esta vez — ha sido un problema nuestro, no "
            "de sus datos. Lo intentaré de nuevo en la próxima ejecución."
        ),
    },
    # A última leitura boa, quando a de agora falhou.
    #
    # > «devemos ser inteligentes e talvez mostrar o primeiro resultado»
    # > — Lucas, 09/10/2026
    #
    # O `{data}` não é decoração: é o que impede isto de ser outra
    # mentira tranquilizadora. Repetir um número antigo sem dizer que é
    # antigo é pior do que não o mostrar — quem lê decide com ele como
    # se fosse de hoje.
    #
    # Fica a seguir à frase da avaria, não no lugar dela: primeiro
    # dizer que falhou, depois o que ainda se sabe.
    "agent_last_known_reading": {
        "pt": "A última leitura que consegui foi a de {data}:",
        "en": "The last reading I managed was from {data}:",
        "es": "La última lectura que conseguí fue la de {data}:",
    },
    # O corpo do achado de uma corrida vazia. O título já vinha do
    # catálogo (`agent_run_no_output`) e a descrição ao lado estava
    # cravada em inglês — a mesma falha, na linha seguinte à correcção.
    "agent_run_no_output_body": {
        "pt": (
            "O motor não devolveu conteúdo nesta corrida. Reveja o foco do "
            "agente e as fontes de dados, ou repita."
        ),
        "en": (
            "The AI service returned no content for this run. Check the agent's "
            "focus prompt, data sources, or retry."
        ),
        "es": (
            "El motor no ha devuelto contenido en esta ejecución. Revise el foco "
            "del agente y las fuentes de datos, o reinténtelo."
        ),
    },
    "chat_error_generic": {
        "pt": "A Sky não conseguiu responder agora. Tente outra vez.",
        "en": "Sky couldn't answer right now. Please try again.",
        "es": "Sky no ha podido responder ahora. Inténtelo de nuevo.",
    },
    "chat_error_timeout": {
        "pt": "A pergunta demorou demasiado. Experimente uma mais simples, ou repita.",
        "en": "The question took too long. Try a simpler one, or retry.",
        "es": "La pregunta ha tardado demasiado. Pruebe con una más sencilla, o reinténtelo.",
    },
    "chat_error_rate_limited": {
        "pt": "Perguntas a mais em pouco tempo. Espere uns segundos e repita.",
        "en": "Too many questions in a short window. Wait a few seconds and retry.",
        "es": "Demasiadas preguntas en poco tiempo. Espere unos segundos y reinténtelo.",
    },
    "chat_error_unavailable": {
        "pt": "A Sky está indisponível neste momento. Repita daqui a pouco.",
        "en": "Sky is unavailable right now. Please retry in a moment.",
        "es": "Sky no está disponible en este momento. Reinténtelo en un momento.",
    },
    "chat_error_network": {
        "pt": "Não foi possível contactar a Sky. Verifique a ligação e repita.",
        "en": "Couldn't reach Sky. Check your connection and retry.",
        "es": "No se ha podido contactar con Sky. Compruebe la conexión y reinténtelo.",
    },
    # O 404 do `/connections/<id>/query` quer dizer uma coisa muito
    # concreta: a ligação não tem metadados. A frase antiga — «the AI
    # service rejected the request» — mandava procurar um defeito no
    # serviço de IA, que está bom, em vez de no sítio onde se resolve.
    "chat_error_no_metadata": {
        "pt": "Esta ligação ainda não foi analisada, por isso a Sky não "
        "sabe que tabelas existem. Sincronize-a em Definições › Ligações.",
        "en": "This connection hasn't been analysed yet, so Sky doesn't know "
        "which tables exist. Sync it in Settings › Connections.",
        "es": "Esta conexión aún no se ha analizado, así que Sky no sabe qué "
        "tablas existen. Sincronícela en Ajustes › Conexiones.",
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


NOTIFICATION_KEYS: frozenset[str] = frozenset(
    {
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
    }
)

# DB migration that adds the columns consumed by these keys: notif_i18n_keys_20260612


def get_message(key: str, locale: str | None = None) -> str:
    """Return a user-facing string for the given locale.

    Falls back to DEFAULT_LOCALE if the key or locale is not found.
    """
    resolved = normalize_locale(locale)
    bucket = _MESSAGES.get(key, {})
    return bucket.get(resolved) or bucket.get(DEFAULT_LOCALE) or key


def lingua_da_resposta(preferences: dict | None) -> str:
    """A língua em que a IA responde.

    ── Duas definições, não uma ────────────────────────────────────

    > «tem pessoas que falam mais idiomas, querem a plataforma de uma
    >  forma, e querem a resposta de outra, por causa dos dados»
    > — Lucas, 05/10/2026

    O caso concreto: uma empresa espanhola cujos dados — tabelas, nomes
    de colunas — estão em inglês. É preciso ler o dado em inglês e
    responder em castelhano. A língua do dado é o que é; a de quem lê é
    uma escolha.

    Até aqui havia uma só preferência, `language`, a servir as duas
    coisas. Agora `answer_language` sobrepõe-se quando existe.

    ⚠️ Vazio **não** é «inglês»: é «como a interface». Um `or` simples
    sobre a string vazia dá exactamente o comportamento certo, e é por
    isso que o valor por omissão é `""` e não `None` — uma preferência
    gravada como `""` lê-se igual a uma que nunca foi gravada, que é o
    que queremos.
    """
    prefs = preferences or {}
    escolhida = (prefs.get("answer_language") or "").strip()
    if escolhida:
        return normalize_locale(escolhida)
    return normalize_locale(prefs.get("language", DEFAULT_LOCALE))
