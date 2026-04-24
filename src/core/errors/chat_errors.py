"""W6 — Claude-level chat error taxonomy.

Master plan §9.

Single source of truth for every error the chat/agent stack produces.
Each subclass pairs a stable ``code`` (``CHAT_*``) with a user-facing
message (pt-BR), an HTTP status and optional ``retry_after`` / ``docs_url``
hints. The FastAPI exception handler turns them into::

    {
      "error": {
        "code": "CHAT_CONTEXT_DENIED",
        "message": "Não tenho acesso a essa informação neste espaço.",
        "trace_id": "01HX3K...",
        "retry_after": null,
        "docs_url": "https://docs.skyfirstlabs.com/errors/chat_context_denied"
      }
    }

Downstream (frontend ``src/lib/errors/mapper.ts``) switches on ``code``.
Never switch on ``message`` — copy is localisable / tunable.

Importing from earlier waves:

  - W4 ``ChatInputError`` family already carries compatible ``code``s;
    the handler in ``handlers.py`` routes both through this envelope.
  - W5 ``OutputACLBreach`` maps to ``CHAT_OUTPUT_ACL_BREACH``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


DOCS_BASE = "https://docs.skyfirstlabs.com/errors"


# ---------------------------------------------------------------------------
#  Envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatErrorEnvelope:
    code: str
    message: str
    trace_id: Optional[str] = None
    retry_after: Optional[int] = None
    docs_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "trace_id": self.trace_id,
                "retry_after": self.retry_after,
                "docs_url": self.docs_url or f"{DOCS_BASE}/{self.code.lower()}",
            }
        }


# ---------------------------------------------------------------------------
#  Base
# ---------------------------------------------------------------------------


class ChatError(Exception):
    """Every error in the chat/agent stack derives from this. Holds
    ``code`` (stable identifier, don't change post-ship), ``message`` (UI
    copy, translatable), ``http_status`` and optional ``retry_after``."""

    code: str = "CHAT_INTERNAL_ERROR"
    http_status: int = 500
    message_default: str = "Algo deu errado. Se o problema persistir, compartilhe o trace id com o suporte."
    retry_after: Optional[int] = None

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        trace_id: Optional[str] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        self.message = message or self.message_default
        self.trace_id = trace_id
        if retry_after is not None:
            self.retry_after = retry_after
        super().__init__(self.message)

    def envelope(self) -> ChatErrorEnvelope:
        return ChatErrorEnvelope(
            code=self.code,
            message=self.message,
            trace_id=self.trace_id,
            retry_after=self.retry_after,
        )


# ---------------------------------------------------------------------------
#  Concrete codes (master plan §9)
# ---------------------------------------------------------------------------


class ChatRateLimited(ChatError):
    code = "CHAT_RATE_LIMITED"
    http_status = 429
    message_default = "Você atingiu o limite de mensagens. Tente novamente em instantes."


class ChatContextDenied(ChatError):
    code = "CHAT_CONTEXT_DENIED"
    http_status = 403
    message_default = "Não tenho acesso a essa informação neste contexto."


class ChatOutputFiltered(ChatError):
    """Soft error — returned with HTTP 200 but ``error.code`` set so the
    UI can show a subtle "filtered" banner. Use when part of the answer
    was redacted but the call still succeeded."""

    code = "CHAT_OUTPUT_FILTERED"
    http_status = 200
    message_default = "Parte da resposta foi filtrada por conter dados sensíveis."


class ChatPolicyViolation(ChatError):
    code = "CHAT_POLICY_VIOLATION"
    http_status = 400
    message_default = "Não posso ajudar com esse tipo de solicitação."


class ChatToolDenied(ChatError):
    code = "CHAT_TOOL_DENIED"
    http_status = 403
    message_default = "Essa ação requer uma permissão que você não tem."

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        permission: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        if permission and message is None:
            message = f"Essa ação requer a permissão `{permission}`, que você não tem."
        super().__init__(message, trace_id=trace_id)


class ChatUpstreamTimeout(ChatError):
    code = "CHAT_UPSTREAM_TIMEOUT"
    http_status = 504
    message_default = "A IA demorou demais para responder. Tentando de novo?"
    retry_after = 5


class ChatUpstreamError(ChatError):
    code = "CHAT_UPSTREAM_ERROR"
    http_status = 502
    message_default = "A IA está temporariamente indisponível. Já fomos notificados."
    retry_after = 30


class ChatMalformedInput(ChatError):
    code = "CHAT_MALFORMED_INPUT"
    http_status = 400
    message_default = "Mensagem inválida ou muito grande. Simplifique e tente de novo."


class ChatInternalError(ChatError):
    code = "CHAT_INTERNAL_ERROR"
    http_status = 500
    message_default = "Algo deu errado. Compartilhe o trace id com o suporte."


class ChatOutputACLBreach(ChatError):
    """From W5 — evidence the LLM cited wasn't in the authorised set.
    Block the response. Frontend shows generic message; audit log keeps
    the full detail."""

    code = "CHAT_OUTPUT_ACL_BREACH"
    http_status = 502  # upstream-ish from the client's POV
    message_default = "Não consegui gerar uma resposta segura para essa pergunta."


# ---------------------------------------------------------------------------
#  Legacy bridge — wrap W4/W5 exceptions as ChatError subclasses
# ---------------------------------------------------------------------------


def wrap_as_chat_error(exc: Exception, *, trace_id: Optional[str] = None) -> ChatError:
    """Convert any known-family exception into the right ``ChatError``
    subclass. Used by the FastAPI handler so we only need one handler
    registered for the whole family.

    Unknown exception → ``ChatInternalError``.
    """
    # Already one of ours.
    if isinstance(exc, ChatError):
        if trace_id and exc.trace_id is None:
            exc.trace_id = trace_id
        return exc

    # W4 family (input guard)
    try:
        from src.ai.input_guard import (
            ChatMessageEmpty,
            ChatMessageTooLong,
            ChatPolicyViolation as InputPolicyViolation,
        )
    except ImportError:  # pragma: no cover - should always import
        ChatMessageEmpty = ChatMessageTooLong = InputPolicyViolation = ()  # type: ignore

    if isinstance(exc, (ChatMessageEmpty, ChatMessageTooLong)):
        return ChatMalformedInput(str(exc), trace_id=trace_id)
    if isinstance(exc, InputPolicyViolation):
        return ChatPolicyViolation(str(exc), trace_id=trace_id)

    # W5 family (output guard)
    try:
        from src.ai.output_guard import OutputACLBreach
    except ImportError:  # pragma: no cover
        OutputACLBreach = ()  # type: ignore

    if isinstance(exc, OutputACLBreach):
        return ChatOutputACLBreach(str(exc), trace_id=trace_id)

    # Anything else
    return ChatInternalError(str(exc) or None, trace_id=trace_id)


# ---------------------------------------------------------------------------
#  FastAPI handler helper (registered from main.py in a follow-up PR)
# ---------------------------------------------------------------------------


def build_json_response(exc: ChatError) -> Dict[str, Any]:
    """Flat dict representation of ``exc.envelope().to_dict()``. Use to
    build a ``fastapi.responses.JSONResponse(content=..., status_code=...)``
    in the exception handler without importing fastapi here."""
    return exc.envelope().to_dict()
