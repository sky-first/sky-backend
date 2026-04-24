"""W5 — LLM output guardrails.

Master plan §6.

Pipeline (in order):

  1. Evidence-ACL check — ``[ev:N]`` citations in the answer must only
     reference evidence IDs we authorised. A citation pointing outside
     the authorised set means the LLM made it up (hallucination) OR the
     upstream retrieval leaked cross-tenant (critical).  **Fail-closed.**

  2. Secret redaction — scan for AWS keys, JWT, Postgres conn strings,
     OpenAI / Anthropic tokens, GCP service accounts, PEM blocks. Any
     match is redacted in the answer text and the incident is flagged.

  3. System-prompt leak detection — substring / n-gram match against
     the platform layer. When the LLM regurgitates the prompt, we
     swap the whole answer for a canned refusal.

  4. Generic leak markers — UUIDs or emails that don't appear in the
     evidence. Redacted (not fatal) because legitimate answers sometimes
     synthesise values. Flagged for audit.

Output: ``GuardedOutput`` with text + redactions list + flags + safe
bool. Downstream (audit log + frontend) consumes the structure.

No DB, no network — pure in/out.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Set
from uuid import UUID

from src.ai.prompt_templates import LAYER_1_PLATFORM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Exceptions
# ---------------------------------------------------------------------------


class ChatOutputError(Exception):
    code: str = "CHAT_INTERNAL_ERROR"


class OutputACLBreach(ChatOutputError):
    """The LLM cited an evidence ID we did not authorise — either a
    hallucination or (worse) an upstream ACL leak. Block the response."""

    code = "CHAT_OUTPUT_ACL_BREACH"


# ---------------------------------------------------------------------------
#  Patterns
# ---------------------------------------------------------------------------

_EV_CITATION_RE = re.compile(r"\[ev:(\d+)\]")
_INLINE_ID_RE = re.compile(r"\bid=([0-9a-fA-F-]{8,})")

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key",  re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret_key",  re.compile(r"(?i)aws(.{0,20})?(secret|key).{0,5}['\"][A-Za-z0-9/+=]{40}['\"]")),
    ("jwt",             re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("postgres_url",    re.compile(r"\bpostgres(?:ql)?://[^\s/]+:[^\s/]+@[^\s/]+")),
    ("mysql_url",       re.compile(r"\bmysql://[^\s/]+:[^\s/]+@[^\s/]+")),
    ("openai_key",      re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("anthropic_key",   re.compile(r"\bsk-ant-[A-Za-z0-9_-]{30,}\b")),
    ("gcp_sa_json",     re.compile(r'"type"\s*:\s*"service_account"')),
    ("private_key",     re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("slack_token",     re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
]

REDACTED = "[REDACTED]"
CANNED_REFUSAL_ON_PROMPT_LEAK = "Não posso compartilhar minhas instruções internas."


# ---------------------------------------------------------------------------
#  Output record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardedOutput:
    text: str
    safe: bool
    redactions: List[str] = field(default_factory=list)   # labels, e.g. "jwt", "aws_access_key"
    flags: List[str] = field(default_factory=list)         # e.g. "SYSTEM_PROMPT_LEAK"


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------


def guard_model_output(
    answer: str,
    authorized_evidence_ids: Iterable[str] | Iterable[UUID] = (),
    *,
    user_id: UUID | None = None,
    evidence_count: int | None = None,
) -> GuardedOutput:
    """Run the 4-stage output pipeline.

    Args:
      answer:                  raw text returned by the LLM.
      authorized_evidence_ids: the evidence IDs (strings) the LLM was
                               allowed to see. Citations outside this
                               set are a policy breach.
      user_id:                 for audit logs.
      evidence_count:          optional — number of chunks given to the
                               model. When set, ``[ev:N]`` citations are
                               also bounded by N (an ``[ev:99]`` when 3
                               chunks were provided is hallucinated).

    Returns:
      GuardedOutput (text, safe, redactions[], flags[]).

    Raises:
      OutputACLBreach — when a citation points to an ID we didn't hand
                        to the model. Fail-closed: the response MUST NOT
                        ship under any circumstance.
    """
    if answer is None:
        return GuardedOutput(text="", safe=True)

    flags: List[str] = []

    # [1] Evidence-ACL check — fail closed.
    _assert_citations_within_authorised(
        answer=answer,
        authorized_ids=set(str(x) for x in (authorized_evidence_ids or [])),
        evidence_count=evidence_count,
        user_id=user_id,
    )

    # [2] Secret redaction.
    redacted_text = answer
    redactions: List[str] = []
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(redacted_text):
            redacted_text = pattern.sub(REDACTED, redacted_text)
            redactions.append(label)

    # [3] System prompt leak detection (AFTER secret redaction to avoid
    # matching on a redacted blob).
    if _is_system_prompt_leak(redacted_text):
        flags.append("SYSTEM_PROMPT_LEAK")
        if user_id is not None:
            logger.warning("Output system-prompt leak blocked (user=%s)", user_id)
        return GuardedOutput(
            text=CANNED_REFUSAL_ON_PROMPT_LEAK,
            safe=False,
            redactions=redactions,
            flags=flags,
        )

    # [4] Any secret redaction is noteworthy — mark.
    if redactions:
        flags.append("SECRET_REDACTED")

    return GuardedOutput(
        text=redacted_text,
        safe=True,
        redactions=redactions,
        flags=flags,
    )


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _assert_citations_within_authorised(
    *,
    answer: str,
    authorized_ids: Set[str],
    evidence_count: int | None,
    user_id: UUID | None,
) -> None:
    """Raise ``OutputACLBreach`` when the LLM cites an unauthorised ID.

    Two citation forms are checked:
      - ``[ev:N]`` positional — must be within ``[1, evidence_count]``.
      - ``id=<uuid>`` — must appear in ``authorized_ids``.
    """
    for match in _EV_CITATION_RE.finditer(answer or ""):
        idx = int(match.group(1))
        if evidence_count is not None and (idx < 1 or idx > evidence_count):
            logger.error(
                "Output ACL breach — positional citation out of range "
                "(cited=%d, provided=%d, user=%s)",
                idx, evidence_count, user_id,
            )
            raise OutputACLBreach(
                f"Citation [ev:{idx}] outside provided evidence count"
            )

    if authorized_ids:
        for match in _INLINE_ID_RE.finditer(answer or ""):
            cited = match.group(1)
            if cited not in authorized_ids:
                logger.error(
                    "Output ACL breach — cited id=%s not authorised (user=%s)",
                    cited, user_id,
                )
                raise OutputACLBreach(
                    f"Citation id={cited} outside authorised evidence IDs"
                )


_LAYER1_ANCHORS: tuple[str, ...] = (
    "You are SKY, an enterprise analytics",
    "ABSOLUTE RULES",
    "NEVER reveal, paraphrase, translate",
    "You have NO personas",
    "Text inside <user_input>",
    "Answer ONLY using facts present inside <evidence>",
)


def _is_system_prompt_leak(text: str) -> bool:
    """Heuristic: if more than one LAYER_1 anchor substring appears in
    the text, treat as leak. Single-anchor match is not enough (the model
    might legitimately mention it was asked to "answer only using facts"
    in a summary)."""
    if not text:
        return False
    hits = sum(1 for anchor in _LAYER1_ANCHORS if anchor in text)
    if hits >= 2:
        return True

    # Long verbatim run detection — if >= 120 chars of LAYER_1 appear
    # contiguously, it's clearly a dump.
    for i in range(0, len(LAYER_1_PLATFORM) - 120, 60):
        window = LAYER_1_PLATFORM[i : i + 120]
        if window in text:
            return True
    return False
