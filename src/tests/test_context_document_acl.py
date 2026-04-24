"""W1 — context_documents ACL + content_hash + crew_ids tests.

QA perspectives covered:
  - Dedup by content_hash (same content different source → same hash)
  - crew_ids multi-crew ACL (matches plan §2.3)
  - Hash recomputation on body/title/meta/kind update
  - Hash stability on unrelated column update
  - Visibility enum enforced
  - Backward-compat with legacy crew_id single column
  - Role-scoped visibility helper (is_visible_to_context)
  - Cross-space / cross-crew / cross-user isolation
  - Personal mode isolation (owner_user_id)
  - Tag-smuggled content doesn't bypass hashing
  - Ingest from untrusted body preserves literal (no code-exec)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

import pytest

from src.models.context_document import ContextDocument, ContextDocumentVisibility
from src.services.context_acl import (
    VisibilityContext,
    is_visible_to_context,
    sanitize_body_for_hash,
)

# ---------------------------------------------------------------------------
#  content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    """Content-hash semantics — the dedup key across source rows."""

    def test_hash_is_sha256_hex(self):
        h = ContextDocument.compute_content_hash("pillar", "t", "b", {})
        assert len(h) == 64
        int(h, 16)  # hex

    def test_same_content_same_hash(self):
        a = ContextDocument.compute_content_hash("pillar", "Growth", "Body", {"x": 1})
        b = ContextDocument.compute_content_hash("pillar", "Growth", "Body", {"x": 1})
        assert a == b

    def test_different_title_different_hash(self):
        a = ContextDocument.compute_content_hash("pillar", "Growth", "Body", {})
        b = ContextDocument.compute_content_hash("pillar", "Churn", "Body", {})
        assert a != b

    def test_different_body_different_hash(self):
        a = ContextDocument.compute_content_hash("pillar", "t", "alpha", {})
        b = ContextDocument.compute_content_hash("pillar", "t", "beta", {})
        assert a != b

    def test_different_kind_different_hash(self):
        a = ContextDocument.compute_content_hash("pillar", "t", "b", {})
        b = ContextDocument.compute_content_hash("goal", "t", "b", {})
        assert a != b

    def test_meta_key_order_stable(self):
        """meta keys in different insertion order must produce same hash."""
        a = ContextDocument.compute_content_hash("pillar", "t", "b", {"a": 1, "b": 2})
        b = ContextDocument.compute_content_hash("pillar", "t", "b", {"b": 2, "a": 1})
        assert a == b

    def test_meta_none_vs_empty_same_hash(self):
        """NULL meta must normalize to empty dict — mirror legacy rows."""
        a = ContextDocument.compute_content_hash("pillar", "t", "b", None)
        b = ContextDocument.compute_content_hash("pillar", "t", "b", {})
        assert a == b

    def test_huge_body_still_fixed_hash(self):
        big = "x" * 5_000_000  # 5 MiB body
        h = ContextDocument.compute_content_hash("pillar", "t", big, {})
        assert len(h) == 64

    def test_hash_rejects_tag_injection_for_cache_bypass(self):
        """Attacker crafts body that, after a naive strip, equals a cached
        doc — we must hash the RAW body, not post-sanitize, so the attacker
        cannot poison cache with a different-looking-but-same-hash row."""
        raw = "legit content"
        injected = "legit <script>alert(1)</script> content"
        assert (
            ContextDocument.compute_content_hash("pillar", "t", raw, {})
            != ContextDocument.compute_content_hash("pillar", "t", injected, {})
        )

    def test_sanitize_for_hash_does_not_strip(self):
        """sanitize_body_for_hash is explicitly a passthrough — hash is over
        the exact bytes stored. Sanitization happens only at render time."""
        body = "a <b> c <script>x</script>"
        assert sanitize_body_for_hash(body) == body

    def test_hash_deterministic_across_interpreters(self):
        """Manual SHA-256 computed via Python's hashlib must match the helper
        — guard against accidental switch to a non-deterministic hash (e.g.,
        Python's hash() which randomizes per-process)."""
        payload = json.dumps(
            {"kind": "pillar", "title": "t", "body": "b", "meta": {}},
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        assert ContextDocument.compute_content_hash("pillar", "t", "b", {}) == expected


# ---------------------------------------------------------------------------
#  ORM auto-populate on insert/update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestContentHashEvents:
    async def test_insert_populates_hash(self, db_session):
        doc = ContextDocument(
            kind="pillar",
            source_id=uuid.uuid4(),
            source_table="strategic_pillars",
            title="Growth",
            body="Drive growth",
            meta={},
            visibility="space",
        )
        db_session.add(doc)
        await db_session.flush()
        assert doc.content_hash
        assert len(doc.content_hash) == 64

    async def test_update_body_changes_hash(self, db_session):
        doc = ContextDocument(
            kind="pillar",
            source_id=uuid.uuid4(),
            source_table="strategic_pillars",
            title="t",
            body="v1",
            meta={},
            visibility="space",
        )
        db_session.add(doc)
        await db_session.flush()
        h1 = doc.content_hash

        doc.body = "v2"
        await db_session.flush()
        assert doc.content_hash != h1

    async def test_update_unrelated_column_keeps_hash(self, db_session):
        doc = ContextDocument(
            kind="pillar",
            source_id=uuid.uuid4(),
            source_table="strategic_pillars",
            title="t",
            body="b",
            meta={},
            visibility="space",
            pii_flags=[],
        )
        db_session.add(doc)
        await db_session.flush()
        h1 = doc.content_hash

        doc.pii_flags = ["email"]
        await db_session.flush()
        # pii_flags does NOT contribute to hash
        assert doc.content_hash == h1

    async def test_explicit_hash_not_overwritten(self, db_session):
        """If caller explicitly passes content_hash, respect it (used in
        backfill migration)."""
        fixed = "a" * 64
        doc = ContextDocument(
            kind="pillar",
            source_id=uuid.uuid4(),
            source_table="strategic_pillars",
            title="t",
            body="b",
            meta={},
            visibility="space",
            content_hash=fixed,
        )
        db_session.add(doc)
        await db_session.flush()
        assert doc.content_hash == fixed


# ---------------------------------------------------------------------------
#  crew_ids multi-crew ACL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCrewIdsMultiCrew:
    async def test_default_is_empty_list(self, db_session):
        doc = ContextDocument(
            kind="pillar",
            source_id=uuid.uuid4(),
            source_table="strategic_pillars",
            title="t",
            body="b",
            meta={},
            visibility="space",
        )
        db_session.add(doc)
        await db_session.flush()
        assert doc.crew_ids == []

    async def test_multiple_crew_ids_persist(self, db_session):
        crew_a, crew_b = uuid.uuid4(), uuid.uuid4()
        doc = ContextDocument(
            kind="pillar",
            source_id=uuid.uuid4(),
            source_table="strategic_pillars",
            title="t",
            body="b",
            meta={},
            visibility="crew",
            crew_ids=[crew_a, crew_b],
        )
        db_session.add(doc)
        await db_session.flush()
        # sqlite JSON variant may store as strings; normalize
        got = [uuid.UUID(str(c)) if not isinstance(c, uuid.UUID) else c for c in doc.crew_ids]
        assert set(got) == {crew_a, crew_b}

    async def test_legacy_crew_id_backfills_crew_ids_on_save(self, db_session):
        """If caller sets only legacy crew_id, ORM auto-mirrors into crew_ids
        so retrieval can query a single column."""
        legacy = uuid.uuid4()
        doc = ContextDocument(
            kind="pillar",
            source_id=uuid.uuid4(),
            source_table="strategic_pillars",
            title="t",
            body="b",
            meta={},
            visibility="crew",
            crew_id=legacy,
        )
        db_session.add(doc)
        await db_session.flush()
        got = [uuid.UUID(str(c)) if not isinstance(c, uuid.UUID) else c for c in doc.crew_ids]
        assert legacy in got


# ---------------------------------------------------------------------------
#  Visibility helper (pure function — W2 uses this)
# ---------------------------------------------------------------------------


def _make_doc(**overrides) -> ContextDocument:
    d = ContextDocument(
        kind=overrides.get("kind", "pillar"),
        source_id=overrides.get("source_id", uuid.uuid4()),
        source_table="strategic_pillars",
        title="t",
        body="b",
        meta={},
        visibility=overrides.get("visibility", "space"),
        space_id=overrides.get("space_id"),
        crew_id=overrides.get("crew_id"),
        crew_ids=overrides.get("crew_ids", []),
        owner_user_id=overrides.get("owner_user_id"),
    )
    return d


class TestIsVisibleToContext:
    """QA role perspectives — is_visible_to_context used by W2 retrieval chain.

    Roles modeled:
      - Owner (doc creator)
      - Space member (in the doc's space_id)
      - Non-member (different space)
      - Crew member (matches crew_ids)
      - Crew non-member (in space but wrong crew)
      - Personal user asking from own scope (space_id=None)
      - Outsider (wrong tenant — simulated by disjoint memberships)
    """

    def test_public_always_visible(self):
        d = _make_doc(visibility="public")
        ctx = VisibilityContext(user_id=uuid.uuid4(), space_id=None, crew_ids=[], is_personal=True)
        assert is_visible_to_context(d, ctx) is True

    def test_user_scope_only_owner(self):
        owner = uuid.uuid4()
        other = uuid.uuid4()
        d = _make_doc(visibility="user", owner_user_id=owner, space_id=None)
        ctx_owner = VisibilityContext(user_id=owner, space_id=None, crew_ids=[], is_personal=True)
        ctx_other = VisibilityContext(user_id=other, space_id=None, crew_ids=[], is_personal=True)
        assert is_visible_to_context(d, ctx_owner) is True
        assert is_visible_to_context(d, ctx_other) is False

    def test_space_scope_member_sees(self):
        space = uuid.uuid4()
        d = _make_doc(visibility="space", space_id=space)
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=space, crew_ids=[], is_personal=False
        )
        assert is_visible_to_context(d, ctx) is True

    def test_space_scope_non_member_blocked(self):
        d = _make_doc(visibility="space", space_id=uuid.uuid4())
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=uuid.uuid4(), crew_ids=[], is_personal=False
        )
        assert is_visible_to_context(d, ctx) is False

    def test_crew_scope_member_sees(self):
        space = uuid.uuid4()
        crew = uuid.uuid4()
        d = _make_doc(visibility="crew", space_id=space, crew_ids=[crew])
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=space, crew_ids=[crew], is_personal=False
        )
        assert is_visible_to_context(d, ctx) is True

    def test_crew_scope_space_only_blocked(self):
        """In a space but not in the crew — must NOT see crew-scoped doc."""
        space = uuid.uuid4()
        d = _make_doc(visibility="crew", space_id=space, crew_ids=[uuid.uuid4()])
        ctx = VisibilityContext(
            user_id=uuid.uuid4(),
            space_id=space,
            crew_ids=[uuid.uuid4()],  # different crew
            is_personal=False,
        )
        assert is_visible_to_context(d, ctx) is False

    def test_crew_scope_multi_crew_any_match(self):
        """User is member of ANY crew in doc's crew_ids → visible."""
        space = uuid.uuid4()
        crew_a, crew_b, crew_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        d = _make_doc(visibility="crew", space_id=space, crew_ids=[crew_a, crew_b])
        ctx = VisibilityContext(
            user_id=uuid.uuid4(),
            space_id=space,
            crew_ids=[crew_b, crew_c],  # overlap on crew_b
            is_personal=False,
        )
        assert is_visible_to_context(d, ctx) is True

    def test_personal_mode_sees_own_doc(self):
        owner = uuid.uuid4()
        d = _make_doc(visibility="user", owner_user_id=owner, space_id=None)
        ctx = VisibilityContext(user_id=owner, space_id=None, crew_ids=[], is_personal=True)
        assert is_visible_to_context(d, ctx) is True

    def test_personal_mode_blocks_other_space_docs(self):
        """Paul (Personal) must NOT see docs scoped to a space he has no
        membership in. Personal aggregates only spaces the user belongs to."""
        d = _make_doc(visibility="space", space_id=uuid.uuid4())
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=None, crew_ids=[], is_personal=True
        )
        # Personal without explicit access to the space → blocked
        assert is_visible_to_context(d, ctx) is False

    def test_personal_mode_sees_own_space_aggregate(self):
        """Personal mode with allowed_space_ids list includes space-scoped
        docs for spaces the user belongs to."""
        space = uuid.uuid4()
        d = _make_doc(visibility="space", space_id=space)
        ctx = VisibilityContext(
            user_id=uuid.uuid4(),
            space_id=None,
            crew_ids=[],
            is_personal=True,
            allowed_space_ids=[space],
        )
        assert is_visible_to_context(d, ctx) is True

    def test_deleted_doc_never_visible(self):
        """Tombstoned docs (deleted_at set) never surface, even to owner."""
        owner = uuid.uuid4()
        d = _make_doc(visibility="user", owner_user_id=owner, space_id=None)
        d.deleted_at = datetime.utcnow()
        ctx = VisibilityContext(user_id=owner, space_id=None, crew_ids=[], is_personal=True)
        assert is_visible_to_context(d, ctx) is False

    def test_invalid_visibility_fails_closed(self):
        """Unknown visibility string (future migration bug, data corruption)
        must fail CLOSED — never return True."""
        d = _make_doc(visibility="space", space_id=uuid.uuid4())
        d.visibility = "hacker_mode"  # simulate corruption
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=d.space_id, crew_ids=[], is_personal=False
        )
        assert is_visible_to_context(d, ctx) is False

    def test_null_space_on_space_scope_fails_closed(self):
        """visibility=space but space_id IS NULL is a data bug — treat as
        invisible to avoid leaking to everyone."""
        d = _make_doc(visibility="space", space_id=None)
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=uuid.uuid4(), crew_ids=[], is_personal=False
        )
        assert is_visible_to_context(d, ctx) is False

    def test_null_crew_ids_on_crew_scope_fails_closed(self):
        """visibility=crew but crew_ids empty — same fail-closed stance."""
        space = uuid.uuid4()
        d = _make_doc(visibility="crew", space_id=space, crew_ids=[])
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=space, crew_ids=[uuid.uuid4()], is_personal=False
        )
        assert is_visible_to_context(d, ctx) is False


# ---------------------------------------------------------------------------
#  Batch visibility (filter helper used by retrieval)
# ---------------------------------------------------------------------------


class TestBatchFilter:
    """filter_visible is the pure helper W2 wires into permission_service.
    Stress-test with mixed scopes + ensure zero cross-leakage."""

    def _docs(self, space_a, space_b, crew_a, crew_b, user_a, user_b):
        return [
            _make_doc(visibility="public", space_id=None),
            _make_doc(visibility="space", space_id=space_a),
            _make_doc(visibility="space", space_id=space_b),
            _make_doc(visibility="crew", space_id=space_a, crew_ids=[crew_a]),
            _make_doc(visibility="crew", space_id=space_a, crew_ids=[crew_b]),
            _make_doc(visibility="user", owner_user_id=user_a),
            _make_doc(visibility="user", owner_user_id=user_b),
        ]

    def test_space_a_member_sees_only_allowed(self):
        space_a, space_b = uuid.uuid4(), uuid.uuid4()
        crew_a, crew_b = uuid.uuid4(), uuid.uuid4()
        user_a, user_b = uuid.uuid4(), uuid.uuid4()

        from src.services.context_acl import filter_visible

        docs = self._docs(space_a, space_b, crew_a, crew_b, user_a, user_b)
        ctx = VisibilityContext(
            user_id=user_a, space_id=space_a, crew_ids=[crew_a], is_personal=False
        )
        visible = filter_visible(docs, ctx)

        # Expected: public (1) + space_a (1) + crew_a in space_a (1) + user_a's
        # own user-scoped doc (1) = 4. space_b, crew_b and user_b's doc must be
        # invisible.
        assert len(visible) == 4
        assert all(
            d.visibility != "space" or d.space_id == space_a for d in visible
        )
        assert all(d.visibility != "user" or d.owner_user_id == user_a for d in visible)
        # Zero leakage from space_b / crew_b / user_b
        assert not any(d.space_id == space_b for d in visible)
        assert not any(
            d.visibility == "crew" and crew_b in (d.crew_ids or []) for d in visible
        )
        assert not any(
            d.visibility == "user" and d.owner_user_id == user_b for d in visible
        )

    def test_empty_context_only_public(self):
        space_a, space_b = uuid.uuid4(), uuid.uuid4()
        crew_a, crew_b = uuid.uuid4(), uuid.uuid4()
        user_a, user_b = uuid.uuid4(), uuid.uuid4()

        from src.services.context_acl import filter_visible

        docs = self._docs(space_a, space_b, crew_a, crew_b, user_a, user_b)
        # New user with no memberships at all
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=None, crew_ids=[], is_personal=True
        )
        visible = filter_visible(docs, ctx)
        assert len(visible) == 1
        assert visible[0].visibility == "public"

    def test_personal_aggregate_cross_space_is_bounded(self):
        space_a, space_b = uuid.uuid4(), uuid.uuid4()
        crew_a, crew_b = uuid.uuid4(), uuid.uuid4()
        user_a, user_b = uuid.uuid4(), uuid.uuid4()

        from src.services.context_acl import filter_visible

        docs = self._docs(space_a, space_b, crew_a, crew_b, user_a, user_b)
        # Personal mode — member of space_a only
        ctx = VisibilityContext(
            user_id=user_a,
            space_id=None,
            crew_ids=[crew_a],
            is_personal=True,
            allowed_space_ids=[space_a],
        )
        visible = filter_visible(docs, ctx)
        # public + space_a + crew_a(space_a) + user_a doc = 4
        assert len(visible) == 4
        # zero leakage from space_b
        assert not any(d.space_id == space_b for d in visible)


# ---------------------------------------------------------------------------
#  Attacker-style input (negative QA)
# ---------------------------------------------------------------------------


class TestAttackerInputs:
    """Payloads a user-insider might try to smuggle through the hash/ACL
    helpers. These must NOT crash, and must NOT produce spurious True."""

    def test_unicode_normalization_attack(self):
        """Two visually-identical strings with different codepoints must
        NOT collide — hash is over raw bytes."""
        visible = "café"           # U+00E9
        lookalike = "café"   # e + combining acute
        h1 = ContextDocument.compute_content_hash("pillar", visible, "b", {})
        h2 = ContextDocument.compute_content_hash("pillar", lookalike, "b", {})
        assert h1 != h2

    def test_empty_fields_hash_stable(self):
        h = ContextDocument.compute_content_hash("pillar", "", "", {})
        assert len(h) == 64

    def test_nested_meta_hash_stable(self):
        meta = {"nested": {"a": {"b": {"c": [1, 2, 3]}}}}
        h1 = ContextDocument.compute_content_hash("pillar", "t", "b", meta)
        h2 = ContextDocument.compute_content_hash("pillar", "t", "b", meta)
        assert h1 == h2

    def test_visibility_case_sensitivity(self):
        """Migration check enforces lowercase; attacker can't sneak 'PUBLIC'."""
        d = _make_doc(visibility="PUBLIC")
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=None, crew_ids=[], is_personal=True
        )
        assert is_visible_to_context(d, ctx) is False  # strict lowercase match

    def test_crew_ids_string_vs_uuid_coerced(self):
        """crew_ids may round-trip as strings on SQLite — helper must accept
        both forms without failing."""
        space = uuid.uuid4()
        crew = uuid.uuid4()
        d = _make_doc(visibility="crew", space_id=space, crew_ids=[str(crew)])
        ctx = VisibilityContext(
            user_id=uuid.uuid4(), space_id=space, crew_ids=[crew], is_personal=False
        )
        assert is_visible_to_context(d, ctx) is True
