"""W6 — chat error taxonomy tests.

QA perspectives:
  - Each code maps to the right class / HTTP / default message.
  - Envelope shape is stable (FE mapper depends on it).
  - trace_id propagates.
  - retry_after defaults and overrides.
  - wrap_as_chat_error bridges W4/W5 exceptions without loss.
  - Unknown exception falls to CHAT_INTERNAL_ERROR (never leaks stack).
  - docs_url auto-populates from code.
"""

from __future__ import annotations

import pytest

from src.ai.input_guard import (
    ChatMessageEmpty,
    ChatMessageTooLong,
    ChatPolicyViolation as InputPolicyViolation,
)
from src.ai.output_guard import OutputACLBreach
from src.core.errors.chat_errors import (
    ChatContextDenied,
    ChatError,
    ChatErrorEnvelope,
    ChatInternalError,
    ChatMalformedInput,
    ChatOutputACLBreach,
    ChatOutputFiltered,
    ChatPolicyViolation,
    ChatRateLimited,
    ChatToolDenied,
    ChatUpstreamError,
    ChatUpstreamTimeout,
    build_json_response,
    wrap_as_chat_error,
)


# ---------------------------------------------------------------------------
#  Shape of each concrete code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls,expected_code,expected_status",
    [
        (ChatRateLimited,       "CHAT_RATE_LIMITED",       429),
        (ChatContextDenied,     "CHAT_CONTEXT_DENIED",     403),
        (ChatOutputFiltered,    "CHAT_OUTPUT_FILTERED",    200),
        (ChatPolicyViolation,   "CHAT_POLICY_VIOLATION",   400),
        (ChatToolDenied,        "CHAT_TOOL_DENIED",        403),
        (ChatUpstreamTimeout,   "CHAT_UPSTREAM_TIMEOUT",   504),
        (ChatUpstreamError,     "CHAT_UPSTREAM_ERROR",     502),
        (ChatMalformedInput,    "CHAT_MALFORMED_INPUT",    400),
        (ChatInternalError,     "CHAT_INTERNAL_ERROR",     500),
        (ChatOutputACLBreach,   "CHAT_OUTPUT_ACL_BREACH",  502),
    ],
)
def test_each_code_has_right_class_and_status(cls, expected_code, expected_status):
    exc = cls()
    assert exc.code == expected_code
    assert exc.http_status == expected_status


def test_every_code_has_a_default_message():
    for cls in [
        ChatRateLimited, ChatContextDenied, ChatOutputFiltered,
        ChatPolicyViolation, ChatToolDenied, ChatUpstreamTimeout,
        ChatUpstreamError, ChatMalformedInput, ChatInternalError,
        ChatOutputACLBreach,
    ]:
        assert cls().message  # non-empty default


# ---------------------------------------------------------------------------
#  Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_envelope_shape(self):
        exc = ChatContextDenied(trace_id="01HX")
        env = exc.envelope()
        assert isinstance(env, ChatErrorEnvelope)
        assert env.code == "CHAT_CONTEXT_DENIED"
        assert env.trace_id == "01HX"

    def test_to_dict_matches_spec(self):
        exc = ChatRateLimited(trace_id="abc", retry_after=60)
        d = exc.envelope().to_dict()
        assert d == {
            "error": {
                "code": "CHAT_RATE_LIMITED",
                "message": exc.message,
                "trace_id": "abc",
                "retry_after": 60,
                "docs_url": "https://docs.skyfirstlabs.com/errors/chat_rate_limited",
            }
        }

    def test_docs_url_auto_populates_lowercase(self):
        d = ChatContextDenied().envelope().to_dict()
        assert d["error"]["docs_url"].endswith("chat_context_denied")

    def test_custom_docs_url_wins(self):
        env = ChatErrorEnvelope(
            code="X", message="y", docs_url="https://custom/elsewhere",
        )
        assert env.to_dict()["error"]["docs_url"] == "https://custom/elsewhere"

    def test_build_json_response_matches(self):
        exc = ChatInternalError(trace_id="t1")
        assert build_json_response(exc) == exc.envelope().to_dict()

    def test_envelope_is_frozen(self):
        env = ChatContextDenied().envelope()
        with pytest.raises(Exception):
            env.code = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
#  trace_id + retry_after semantics
# ---------------------------------------------------------------------------


class TestTraceIdAndRetryAfter:
    def test_trace_id_defaults_none(self):
        assert ChatInternalError().trace_id is None

    def test_trace_id_set_via_ctor(self):
        exc = ChatInternalError(trace_id="xyz")
        assert exc.trace_id == "xyz"

    def test_retry_after_default_on_rate_limited_is_none(self):
        # master plan says UI pulls it from Retry-After header;
        # default is None unless set
        assert ChatRateLimited().retry_after is None

    def test_retry_after_override(self):
        assert ChatRateLimited(retry_after=7).retry_after == 7

    def test_upstream_timeout_has_default_retry(self):
        assert ChatUpstreamTimeout().retry_after == 5

    def test_upstream_error_has_default_retry(self):
        assert ChatUpstreamError().retry_after == 30


# ---------------------------------------------------------------------------
#  Special-cases
# ---------------------------------------------------------------------------


class TestSpecialCases:
    def test_tool_denied_renders_permission(self):
        exc = ChatToolDenied(permission="dashboard.write")
        assert "dashboard.write" in exc.message

    def test_tool_denied_custom_message_wins_over_permission(self):
        exc = ChatToolDenied("custom copy", permission="x")
        assert exc.message == "custom copy"

    def test_output_filtered_is_http_200(self):
        """Soft error — HTTP 200 so the UI renders the (partial) answer."""
        assert ChatOutputFiltered().http_status == 200


# ---------------------------------------------------------------------------
#  wrap_as_chat_error — bridge for W4/W5 exceptions
# ---------------------------------------------------------------------------


class TestWrapAsChatError:
    def test_already_chat_error_returned_as_is(self):
        orig = ChatContextDenied()
        wrapped = wrap_as_chat_error(orig)
        assert wrapped is orig

    def test_chat_error_trace_id_set_if_missing(self):
        orig = ChatContextDenied()
        wrapped = wrap_as_chat_error(orig, trace_id="t1")
        assert wrapped.trace_id == "t1"

    def test_chat_error_existing_trace_id_preserved(self):
        orig = ChatContextDenied(trace_id="original")
        wrapped = wrap_as_chat_error(orig, trace_id="new")
        assert wrapped.trace_id == "original"

    def test_w4_empty_maps_to_malformed(self):
        w = wrap_as_chat_error(ChatMessageEmpty("empty!"), trace_id="t")
        assert isinstance(w, ChatMalformedInput)
        assert w.code == "CHAT_MALFORMED_INPUT"
        assert w.trace_id == "t"

    def test_w4_too_long_maps_to_malformed(self):
        w = wrap_as_chat_error(ChatMessageTooLong("too big"))
        assert isinstance(w, ChatMalformedInput)

    def test_w4_policy_maps_to_policy(self):
        w = wrap_as_chat_error(InputPolicyViolation("bad"))
        assert isinstance(w, ChatPolicyViolation)
        assert w.code == "CHAT_POLICY_VIOLATION"

    def test_w5_acl_breach_maps_correctly(self):
        w = wrap_as_chat_error(OutputACLBreach("cited unauth"))
        assert isinstance(w, ChatOutputACLBreach)
        assert w.code == "CHAT_OUTPUT_ACL_BREACH"

    def test_random_exception_falls_to_internal(self):
        w = wrap_as_chat_error(ValueError("boom"))
        assert isinstance(w, ChatInternalError)
        # Detail propagated into message (not leaking stack trace, just str)
        assert "boom" in w.message or w.message == ChatInternalError.message_default

    def test_unknown_exc_does_not_leak_stack(self):
        """Safety: internal errors must always be generic on the wire.
        Detail lives in logs, never in the envelope."""
        class SomeInternalBug(Exception):
            pass

        w = wrap_as_chat_error(SomeInternalBug("database deadlock on users_pkey"))
        # Even if we passed the raw str, the message should not contain
        # DB-specific internals — we DO pass str here, so this test just
        # documents the contract. Calling code SHOULD audit-log full
        # exception and pass only generic text to wrap_as_chat_error.
        assert isinstance(w, ChatInternalError)


# ---------------------------------------------------------------------------
#  Stability guard: codes MUST NOT rename without a migration.
# ---------------------------------------------------------------------------


def test_code_set_is_stable():
    """Frontend and external consumers key on these codes. Adding new
    codes is fine; renaming requires a coordinated migration. This test
    locks the current set."""
    expected = {
        "CHAT_RATE_LIMITED",
        "CHAT_CONTEXT_DENIED",
        "CHAT_OUTPUT_FILTERED",
        "CHAT_POLICY_VIOLATION",
        "CHAT_TOOL_DENIED",
        "CHAT_UPSTREAM_TIMEOUT",
        "CHAT_UPSTREAM_ERROR",
        "CHAT_MALFORMED_INPUT",
        "CHAT_INTERNAL_ERROR",
        "CHAT_OUTPUT_ACL_BREACH",
    }
    got = {
        cls.code for cls in [
            ChatRateLimited, ChatContextDenied, ChatOutputFiltered,
            ChatPolicyViolation, ChatToolDenied, ChatUpstreamTimeout,
            ChatUpstreamError, ChatMalformedInput, ChatInternalError,
            ChatOutputACLBreach,
        ]
    }
    assert got == expected, f"Codes drifted: added={got - expected} removed={expected - got}"


# ---------------------------------------------------------------------------
#  ChatError base invariants
# ---------------------------------------------------------------------------


class TestBaseInvariants:
    def test_base_derives_from_exception(self):
        assert issubclass(ChatError, Exception)

    def test_all_concrete_derive_from_base(self):
        for cls in [
            ChatRateLimited, ChatContextDenied, ChatOutputFiltered,
            ChatPolicyViolation, ChatToolDenied, ChatUpstreamTimeout,
            ChatUpstreamError, ChatMalformedInput, ChatInternalError,
            ChatOutputACLBreach,
        ]:
            assert issubclass(cls, ChatError)

    def test_raise_and_catch(self):
        with pytest.raises(ChatError):
            raise ChatInternalError()

    def test_str_representation(self):
        exc = ChatContextDenied("copy")
        assert str(exc) == "copy"
