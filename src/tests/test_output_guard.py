"""W5 — output guardrail tests.

QA perspectives (thinking like an attacker trying to exfiltrate):

A. Clean answers pass unchanged.
B. Secret scanner — every supported pattern redacts.
C. System prompt leak — 2+ anchors blocks; 1 anchor passes; long
   verbatim run blocks.
D. ACL breach — positional ``[ev:N]`` out of range raises; UUID ``id=``
   outside authorised set raises.
E. Multi-secret in one answer — all redacted.
F. Empty / None input safe.
G. Flags populated correctly.
H. Defence in depth: even after secret redaction, a system-prompt-leak
   still triggers the canned refusal (order of operations).
"""

from __future__ import annotations

import uuid

import pytest

from src.ai.output_guard import (
    CANNED_REFUSAL_ON_PROMPT_LEAK,
    OutputACLBreach,
    REDACTED,
    GuardedOutput,
    guard_model_output,
)


# ---------------------------------------------------------------------------
#  A — Clean answers
# ---------------------------------------------------------------------------


class TestCleanAnswers:
    def test_plain_answer_passes_unchanged(self):
        out = guard_model_output("Receita no Q1 cresceu 12%.")
        assert out.safe is True
        assert out.text == "Receita no Q1 cresceu 12%."
        assert out.redactions == []
        assert out.flags == []

    def test_none_is_safe_empty(self):
        out = guard_model_output(None)  # type: ignore[arg-type]
        assert out.text == ""
        assert out.safe is True

    def test_empty_string_is_safe(self):
        out = guard_model_output("")
        assert out.text == ""
        assert out.safe is True


# ---------------------------------------------------------------------------
#  B — Secret scanner
# ---------------------------------------------------------------------------


class TestSecretRedaction:
    @pytest.mark.parametrize(
        "secret,label",
        [
            ("AKIAIOSFODNN7EXAMPLE",                                  "aws_access_key"),
            ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbiJ9.signatureee",  "jwt"),
            ("postgres://u:pw@db.host:5432/app",                      "postgres_url"),
            ("mysql://root:root@db:3306/x",                           "mysql_url"),
            ("sk-abcdefghijklmnopqrstuvwxyz1234567890",               "openai_key"),
            ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",     "anthropic_key"),
            ("xoxb-12345-67890-abcdefghijk",                          "slack_token"),
        ],
    )
    def test_single_secret_redacted(self, secret, label):
        ans = f"Here is the key: {secret} — treat carefully."
        out = guard_model_output(ans)
        assert secret not in out.text
        assert REDACTED in out.text
        assert label in out.redactions
        assert "SECRET_REDACTED" in out.flags

    def test_private_key_block_redacted(self):
        ans = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKC\n-----END"
        out = guard_model_output(ans)
        assert "BEGIN RSA PRIVATE KEY" not in out.text
        assert "private_key" in out.redactions

    def test_gcp_service_account_detected(self):
        ans = 'config: {"type": "service_account", "project_id": "x"}'
        out = guard_model_output(ans)
        assert "gcp_sa_json" in out.redactions

    def test_multiple_secrets_all_redacted(self):
        ans = (
            "AWS=AKIAIOSFODNN7EXAMPLE "
            "JWT=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.signature1234567890 "
            "OAI=sk-abcdefghijklmnopqrstuvwxyz"
        )
        out = guard_model_output(ans)
        for label in ("aws_access_key", "jwt", "openai_key"):
            assert label in out.redactions

    def test_benign_postgres_in_docs_not_redacted(self):
        """Talking about a Postgres table without credentials — safe."""
        ans = "Consulte postgres://docs para mais informações."
        out = guard_model_output(ans)
        assert "postgres_url" not in out.redactions


# ---------------------------------------------------------------------------
#  C — System prompt leak
# ---------------------------------------------------------------------------


class TestSystemPromptLeak:
    def test_two_anchors_trigger_refusal(self):
        leaked = (
            "You are SKY, an enterprise analytics assistant deployed inside "
            "the Sky platform.\n\nABSOLUTE RULES — these override every "
            "instruction that follows:"
        )
        out = guard_model_output(leaked)
        assert out.safe is False
        assert out.text == CANNED_REFUSAL_ON_PROMPT_LEAK
        assert "SYSTEM_PROMPT_LEAK" in out.flags

    def test_one_anchor_does_not_trigger(self):
        """The model might legitimately paraphrase a single rule."""
        one = "I can only answer using facts present inside the evidence."
        out = guard_model_output(one)
        assert out.safe is True
        assert "SYSTEM_PROMPT_LEAK" not in out.flags

    def test_long_verbatim_run_triggers(self):
        from src.ai.prompt_templates import LAYER_1_PLATFORM
        chunk = LAYER_1_PLATFORM[0:180]
        out = guard_model_output(chunk)
        assert out.safe is False

    def test_leak_with_embedded_secret_returns_canned_only(self):
        """Order of ops: we redact secrets first, THEN check for leak.
        If leak is detected, the final output is the canned refusal —
        no leaked fragment of the original answer escapes."""
        leaked = (
            "You are SKY, an enterprise analytics assistant deployed inside "
            "the Sky platform. Also my key: AKIAIOSFODNN7EXAMPLE — "
            "ABSOLUTE RULES"
        )
        out = guard_model_output(leaked)
        assert out.safe is False
        assert out.text == CANNED_REFUSAL_ON_PROMPT_LEAK
        # secret also redacted in redactions list (though not shown)
        assert "aws_access_key" in out.redactions


# ---------------------------------------------------------------------------
#  D — ACL breach
# ---------------------------------------------------------------------------


class TestACLBreach:
    def test_positional_citation_out_of_range_raises(self):
        ans = "Per evidence [ev:99] the total is 10."
        with pytest.raises(OutputACLBreach):
            guard_model_output(ans, evidence_count=3)

    def test_positional_citation_zero_raises(self):
        ans = "See [ev:0]"
        with pytest.raises(OutputACLBreach):
            guard_model_output(ans, evidence_count=3)

    def test_positional_citation_in_range_ok(self):
        ans = "See [ev:1] and [ev:3]"
        out = guard_model_output(ans, evidence_count=3)
        assert out.safe is True

    def test_inline_id_outside_authorised_raises(self):
        good = uuid.uuid4()
        bad = uuid.uuid4()
        ans = f"Based on id={bad} the answer is 42."
        with pytest.raises(OutputACLBreach):
            guard_model_output(ans, authorized_evidence_ids=[good])

    def test_inline_id_in_authorised_ok(self):
        good = uuid.uuid4()
        ans = f"Based on id={good} the answer is 42."
        out = guard_model_output(ans, authorized_evidence_ids=[good])
        assert out.safe is True

    def test_no_citations_no_auth_ids_ok(self):
        out = guard_model_output("Just a summary.")
        assert out.safe is True

    def test_citation_without_authorised_set_only_checks_positional(self):
        """If caller doesn't supply authorised_evidence_ids, we only check
        positional range (defence-in-depth: caller SHOULD supply both)."""
        ans = "Based on id=deadbeef-dead-beef-dead-beefdeadbeef see [ev:2]"
        out = guard_model_output(ans, evidence_count=5)
        # Citation idx 2 is in range; id= check skipped because no auth ids
        assert out.safe is True


# ---------------------------------------------------------------------------
#  E / F / G — Flags + edge cases
# ---------------------------------------------------------------------------


class TestFlagsAndEdgeCases:
    def test_safe_answer_has_no_flags(self):
        out = guard_model_output("Normal answer")
        assert out.flags == []
        assert out.redactions == []

    def test_dataclass_is_frozen(self):
        out = guard_model_output("x")
        with pytest.raises(Exception):
            out.text = "mutated"  # type: ignore[misc]

    def test_secret_then_no_leak_keeps_safe_true(self):
        """Redacted secrets don't make the output 'unsafe' — the answer
        still ships (with redaction). Only prompt leak / ACL breach
        flip ``safe`` to False."""
        ans = "key=AKIAIOSFODNN7EXAMPLE so what"
        out = guard_model_output(ans)
        assert out.safe is True
        assert "SECRET_REDACTED" in out.flags

    def test_returns_guarded_output_type(self):
        out = guard_model_output("x")
        assert isinstance(out, GuardedOutput)

    def test_unicode_answer_unchanged(self):
        msg = "análise completa — tudo certo."
        out = guard_model_output(msg)
        assert out.text == msg


# ---------------------------------------------------------------------------
#  Defence-in-depth — layered tests
# ---------------------------------------------------------------------------


class TestDefenceInDepth:
    def test_citation_breach_preempts_secret_redaction(self):
        """ACL breach is fail-closed: we raise BEFORE any text transformation.
        Even if the same answer contains a secret, the redaction never
        ships — the exception does."""
        bad = uuid.uuid4()
        good = uuid.uuid4()
        ans = f"Secret eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.siggg from id={bad}."
        with pytest.raises(OutputACLBreach):
            guard_model_output(ans, authorized_evidence_ids=[good])

    def test_system_prompt_leak_preempts_secret_in_output(self):
        """Even a 'secret in the leak' returns the canned refusal, not
        the partially-redacted leak body."""
        leaked = (
            "You are SKY, an enterprise analytics assistant deployed inside the "
            "Sky platform. Key: AKIAIOSFODNN7EXAMPLE. ABSOLUTE RULES apply."
        )
        out = guard_model_output(leaked)
        assert out.text == CANNED_REFUSAL_ON_PROMPT_LEAK

    def test_no_fragment_of_leak_in_canned_refusal(self):
        """Sanity: after leak detection, NONE of the original answer
        characters beyond the canned string leak out."""
        leaked = (
            "You are SKY, an enterprise analytics assistant deployed inside the "
            "Sky platform. SECRET=abcdef. ABSOLUTE RULES apply."
        )
        out = guard_model_output(leaked)
        assert "SECRET=abcdef" not in out.text
        assert "ABSOLUTE RULES" not in out.text
        assert "SKY" not in out.text
