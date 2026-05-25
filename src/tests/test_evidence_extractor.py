"""Tests for the Runpod evidence extractor.

QA perspectives:
  - Recognises every supported container key (evidence/sources/chunks/
    retrieved/citations) and every alias for chunk fields.
  - Plain-string entries OK (rare but used by some libs).
  - Drops malformed entries silently rather than crashing.
  - Snippet truncated at 400 chars.
  - Score clamped to [0, 1].
  - Returns [] on None / wrong-type / missing keys.
  - Walks one level of nesting (meta/metadata/trace).
"""

from __future__ import annotations

import pytest

from src.ai.evidence_extractor import MAX_SNIPPET_CHARS, extract_evidence
from src.schemas.ai_transparency import EvidenceChunkOut


# ---------------------------------------------------------------------------
#  Empty / null
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_none_returns_empty(self):
        assert extract_evidence(None) == []

    def test_empty_dict_returns_empty(self):
        assert extract_evidence({}) == []

    def test_unrecognised_keys_return_empty(self):
        assert extract_evidence({"foo": "bar", "baz": [1, 2]}) == []

    def test_non_mapping_returns_empty(self):
        # Passing a list directly — should not crash, returns [].
        assert extract_evidence([1, 2, 3]) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
#  Container key recognition
# ---------------------------------------------------------------------------


class TestContainerKeys:
    @pytest.mark.parametrize("key", ["evidence", "sources", "chunks", "retrieved", "citations"])
    def test_top_level_key_recognised(self, key):
        result = extract_evidence({
            key: [{"id": "x", "title": "T", "snippet": "S"}],
        })
        assert len(result) == 1
        assert result[0].id == "x"

    def test_priority_evidence_wins_over_sources(self):
        result = extract_evidence({
            "evidence": [{"title": "from-evidence", "snippet": "x"}],
            "sources": [{"title": "from-sources", "snippet": "y"}],
        })
        assert result[0].source_label == "from-evidence"
        assert len(result) == 1

    def test_case_insensitive_fallback(self):
        result = extract_evidence({"Evidence": [{"title": "T", "snippet": "S"}]})
        assert len(result) == 1


class TestNesting:
    def test_finds_evidence_in_meta(self):
        payload = {"meta": {"evidence": [{"title": "T", "snippet": "S"}]}}
        result = extract_evidence(payload)
        assert len(result) == 1
        assert result[0].source_label == "T"

    def test_finds_evidence_in_metadata(self):
        payload = {"metadata": {"sources": [{"title": "T", "snippet": "S"}]}}
        result = extract_evidence(payload)
        assert len(result) == 1


# ---------------------------------------------------------------------------
#  Field alias coverage
# ---------------------------------------------------------------------------


class TestFieldAliases:
    @pytest.mark.parametrize(
        "id_key", ["id", "embedding_id", "chunk_id", "source_id"],
    )
    def test_id_aliases(self, id_key):
        result = extract_evidence({
            "evidence": [{id_key: "ID-X", "title": "T", "snippet": "S"}],
        })
        assert result[0].id == "ID-X"

    @pytest.mark.parametrize("kind_key", ["kind", "type"])
    def test_kind_aliases(self, kind_key):
        result = extract_evidence({
            "evidence": [{kind_key: "pillar", "title": "T", "snippet": "S"}],
        })
        assert result[0].kind == "pillar"

    @pytest.mark.parametrize("label_key", ["source_label", "label", "title", "name"])
    def test_label_aliases(self, label_key):
        result = extract_evidence({
            "evidence": [{label_key: "Vendas BR", "snippet": "S"}],
        })
        assert result[0].source_label == "Vendas BR"

    @pytest.mark.parametrize("snip_key", ["snippet", "text", "body", "content", "preview"])
    def test_snippet_aliases(self, snip_key):
        result = extract_evidence({
            "evidence": [{"title": "T", snip_key: "this is the body"}],
        })
        assert "this is the body" in result[0].snippet

    @pytest.mark.parametrize("score_key", ["score", "similarity", "relevance"])
    def test_score_aliases(self, score_key):
        result = extract_evidence({
            "evidence": [{"title": "T", "snippet": "S", score_key: 0.83}],
        })
        assert result[0].score == 0.83

    @pytest.mark.parametrize("href_key", ["href", "url", "link"])
    def test_href_aliases(self, href_key):
        result = extract_evidence({
            "evidence": [{"title": "T", "snippet": "S", href_key: "/x/y"}],
        })
        assert result[0].href == "/x/y"

    def test_score_string_coerced(self):
        result = extract_evidence({
            "evidence": [{"title": "T", "snippet": "S", "score": "0.42"}],
        })
        assert result[0].score == 0.42


# ---------------------------------------------------------------------------
#  Plain string entries
# ---------------------------------------------------------------------------


class TestStringEntries:
    def test_string_entry_becomes_unlabelled_snippet(self):
        result = extract_evidence({"evidence": ["Just a snippet"]})
        assert len(result) == 1
        assert result[0].snippet == "Just a snippet"
        assert result[0].source_label == "(unlabelled)"

    def test_empty_string_dropped(self):
        result = extract_evidence({"evidence": ["", "   ", "actual content"]})
        assert len(result) == 1
        assert result[0].snippet == "actual content"


# ---------------------------------------------------------------------------
#  Malformed entries
# ---------------------------------------------------------------------------


class TestMalformed:
    def test_dict_with_no_useful_fields_dropped(self):
        result = extract_evidence({"evidence": [{"random": 1}]})
        assert result == []

    def test_non_dict_non_string_entries_dropped(self):
        result = extract_evidence({"evidence": [42, None, [1, 2], {"title": "T", "snippet": "S"}]})
        assert len(result) == 1
        assert result[0].source_label == "T"

    def test_truncates_long_snippet(self):
        long = "x" * 1000
        result = extract_evidence({
            "evidence": [{"title": "T", "snippet": long}],
        })
        assert len(result[0].snippet) <= MAX_SNIPPET_CHARS

    def test_negative_score_clamped_to_zero(self):
        result = extract_evidence({
            "evidence": [{"title": "T", "snippet": "S", "score": -0.5}],
        })
        assert result[0].score == 0.0


# ---------------------------------------------------------------------------
#  Returns the right type
# ---------------------------------------------------------------------------


class TestReturnType:
    def test_returns_list_of_evidence_chunk_out(self):
        result = extract_evidence({
            "evidence": [{"title": "T", "snippet": "S"}],
        })
        assert isinstance(result, list)
        assert all(isinstance(c, EvidenceChunkOut) for c in result)
