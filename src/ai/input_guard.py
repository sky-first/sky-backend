"""W4 — Chat input guardrails.

Master plan §5.

Pipeline (strict order):
  1. Hard limits (total chars, lines, single-line chars)
  2. Normalise (strip C0 control chars, neutralise zero-width unicode)
  3. Category classifier (regex-based MVP — TODO W4.1: swap for
     Llama Guard-2 once we have the pod capacity)
  4. Injection signature detection (regex + substring — marks, does NOT
     block; the anti-injection platform prompt in W3 handles the rest)
  5. Emit a ``GuardedInput`` record that downstream (prompt render +
     audit log) consume.

Security stance: **fail-closed**. Ambiguous matches count as suspected
injection. Category misses fall to "ok" because we only hard-block the
three strictly-forbidden classes (abuse, self-harm, csam).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from uuid import UUID

from src.core.locale import get_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Limits
# ---------------------------------------------------------------------------

MAX_MESSAGE_CHARS = 8_000
MAX_MESSAGE_LINES = 500
MAX_SINGLE_LINE_CHARS = 4_000


# ---------------------------------------------------------------------------
#  Exceptions
# ---------------------------------------------------------------------------


class ChatInputError(Exception):
    """Base class. ``code`` maps to the ``CHAT_*`` taxonomy in W6."""

    code: str = "CHAT_MALFORMED_INPUT"
    http_status: int = 400

    def __init__(self, message: str, *, code: Optional[str] = None):
        super().__init__(message)
        if code:
            self.code = code


class ChatMessageEmpty(ChatInputError):
    code = "CHAT_MALFORMED_INPUT"


class ChatMessageTooLong(ChatInputError):
    code = "CHAT_MALFORMED_INPUT"


class ChatPolicyViolation(ChatInputError):
    code = "CHAT_POLICY_VIOLATION"


# ---------------------------------------------------------------------------
#  Patterns
# ---------------------------------------------------------------------------

# C0 control chars (excluding \t \n \r) + DEL.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# Zero-width and other "invisible" unicode often used to smuggle markers
# past naive regex — strip on ingest.
_INVISIBLE_RE = re.compile(
    r"[​-‏‪-‮⁠-⁯﻿]"
)

INJECTION_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("ignore_previous",       re.compile(r"(?i)ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions|prompts|rules)")),
    ("disregard_system",      re.compile(r"(?i)disregard\s+(all\s+|the\s+)?(system|previous|above)")),
    ("persona_switch",        re.compile(r"(?i)you\s+are\s+(now\s+)?(in\s+)?(dan|admin|developer|jailbreak|root|sudo)\s*(mode)?")),
    ("print_system_prompt",   re.compile(r"(?i)(print|show|repeat|reveal|display|give\s+me)\s+(your|the)\s+(system|initial|original)\s+(prompt|instructions|rules)")),
    ("repeat_above",          re.compile(r"(?i)repeat\s+(the\s+)?(words|text|everything)\s+above")),
    ("tag_smuggle",           re.compile(r"</?(evidence|user_input|system|tool_result|assistant|user)\b")),
    ("role_spoof",            re.compile(r"(?m)^\s*(system|assistant|user)\s*:\s*\S")),
    ("json_role_spoof",       re.compile(r'(?i)["\']?role["\']?\s*:\s*["\']?(system|assistant)["\']?')),
    ("override_separator",    re.compile(r"(?m)^\s*-{3,}\s*$.*(new\s+(system|rule)|override)", re.DOTALL)),
)

# Category classifier — crude regex MVP. Upgrade to a proper moderation
# model in a follow-up PR. Words chosen to be unambiguous (no false
# positives on "hate speech" in analytical content).
_ABUSE_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"(?i)\b(kill|murder)\s+(yourself|themselves|him|her)\b"),
    re.compile(r"(?i)\b(hate\s+speech|slur)\s+generator\b"),
)
_SELF_HARM_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"(?i)\bhow\s+to\s+(kill|hurt|harm)\s+my(self)?\b"),
    re.compile(r"(?i)\b(suicide|self[- ]?harm)\s+(methods|instructions|how to)\b"),
)
_CSAM_PATTERNS: Tuple[re.Pattern, ...] = (
    # Intentionally narrow — false positives here are awful but
    # false negatives are worse. Content-level moderation must run
    # as a second layer regardless.
    re.compile(r"(?i)\b(child|minor|underage|kid)\b[^.]{0,40}\b(sexual|nude|explicit)\b"),
)


# ---------------------------------------------------------------------------
#  Output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardedInput:
    text: str
    category: str                                 # "ok" | "abuse" | "self_harm" | "csam"
    injection_suspected: bool
    injection_reasons: List[str] = field(default_factory=list)
    stripped_chars: int = 0
    original_length: int = 0


# ---------------------------------------------------------------------------
#  API
# ---------------------------------------------------------------------------


def guard_user_input(
    message: str,
    *,
    user_id: Optional[UUID] = None,
    locale: Optional[str] = None,
    max_chars: int = MAX_MESSAGE_CHARS,
    max_lines: int = MAX_MESSAGE_LINES,
    max_line_chars: int = MAX_SINGLE_LINE_CHARS,
) -> GuardedInput:
    """Validate + normalise a user chat message.

    Returns ``GuardedInput`` on success.

    Raises:
      - ``ChatMessageEmpty`` when empty after normalisation.
      - ``ChatMessageTooLong`` when limits exceeded.
      - ``ChatPolicyViolation`` when a forbidden category matches.
    """
    if message is None:
        raise ChatMessageEmpty(get_message("empty_message", locale))

    original_length = len(message)

    # [1] Hard limits (raw bytes).
    if original_length == 0:
        raise ChatMessageEmpty(get_message("empty_message", locale))
    if original_length > max_chars:
        raise ChatMessageTooLong(
            f"Message too long ({original_length} chars, max {max_chars})."
        )

    # [2] Normalise. Unicode NFC first (so combining marks compose),
    # then strip C0 controls + invisibles.
    normalised = unicodedata.normalize("NFC", message)
    stripped_controls = _CONTROL_CHARS_RE.sub("", normalised)
    stripped = _INVISIBLE_RE.sub("", stripped_controls)
    stripped_chars = len(normalised) - len(stripped)

    if len(stripped) == 0:
        raise ChatMessageEmpty("Message is empty after normalisation.")

    lines = stripped.splitlines()
    if len(lines) > max_lines:
        raise ChatMessageTooLong(
            f"Too many lines ({len(lines)}, max {max_lines})."
        )
    for line in lines:
        if len(line) > max_line_chars:
            raise ChatMessageTooLong(
                f"Single line too long ({len(line)} chars, max {max_line_chars})."
            )

    # [3] Category classifier — hard block on any match.
    if _any_match(stripped, _ABUSE_PATTERNS):
        _log_refusal(user_id, "abuse")
        raise ChatPolicyViolation("Input blocked by abuse policy.")
    if _any_match(stripped, _SELF_HARM_PATTERNS):
        _log_refusal(user_id, "self_harm")
        raise ChatPolicyViolation("Input blocked by self-harm policy.")
    if _any_match(stripped, _CSAM_PATTERNS):
        _log_refusal(user_id, "csam")
        raise ChatPolicyViolation("Input blocked by CSAM policy.")

    # [4] Injection signature scan — mark, don't block. The platform
    # prompt in W3 + output guard in W5 handle the actual defence.
    injection_reasons: List[str] = []
    for label, pattern in INJECTION_PATTERNS:
        if pattern.search(stripped):
            injection_reasons.append(label)

    return GuardedInput(
        text=stripped,
        category="ok",
        injection_suspected=bool(injection_reasons),
        injection_reasons=injection_reasons,
        stripped_chars=stripped_chars,
        original_length=original_length,
    )


# ---------------------------------------------------------------------------
#  Internals
# ---------------------------------------------------------------------------


def _any_match(text: str, patterns: Tuple[re.Pattern, ...]) -> bool:
    return any(p.search(text) for p in patterns)


def _log_refusal(user_id: Optional[UUID], category: str) -> None:
    logger.warning(
        "Chat input blocked by %s policy (user=%s)",
        category,
        user_id,
    )
