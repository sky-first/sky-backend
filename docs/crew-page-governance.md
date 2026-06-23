# Crew Page Governance — Design, Gaps & Test Plan

> Status: **DRAFT for Lucas's approval — no feature code written yet.**
> Method (per Lucas): validate → document gaps + tests → adversarially stress → only then code.
> Date: 2026-06-16. Scope: how pages are created, owned, shared, and deleted inside a Crew, and how every member converges on a shared canvas.

---

## A. The reported bug (what triggered this)

Paulinho is a **member of a crew**. He enters the crew expecting to land on the **same shared page** as Felipe (collaboration). Instead he is **prompted to create a new page** — convergence onto the crew's canonical page failed for the second member.

This exposed a broader question Lucas raised: a crew (like a space) must have **one default/canonical page for everyone**, and page creation/editing/deletion must follow **collaboration rules** (a viewer shouldn't create; a creator's page still belongs to the crew, so deletion/ownership must be governed). This doc maps the current state, the gaps, a proposed model benchmarked against other tools, and the full test + stress plan.

---

## B. Current state (as-is) — verified against the code

### B.1 Permission rules (`authorization.py::PERMISSION_RULES`)

| Key | Rule (scope, min role) | Effect |
|---|---|---|
| `pages.view` | (space, **viewer**) | any member can view |
| `pages.create` | (space, **editor**) | viewers cannot create |
| `pages.edit` | (space, **editor**) | viewers cannot edit widgets/content |
| `pages.delete` | (space, **owner**) | only space owners (or creator, see B.4) |

Personal variants exist: `pages.create.personal` / `edit.personal` / `delete.personal` = (tenant, any_member).

### B.2 How a role is resolved (the important subtlety)

`Authorization.can()` computes the effective level as `max(space_role, crew_role, best_crew_in_space, acl)` — **but only the contexts it is given**. Crew role elevates a space-scoped permission **only when `crew_id` is passed to the check** (`authorization.py:448-450, 476-483`).

`RBACService.assert_permission()` adds a fallback: when a space-scoped key is checked **with no `space_id`/`crew_id`**, it uses **`_best_role_for_user_anywhere(user)`** — the user's highest role across *any* space/crew (`rbac_service.py:1095-1130`). Platform `super_admin`/`admin` bypass everything non-data-plane.

### B.3 Page model & ownership

- `Page.owner_id` = creator. `Page.crew_id` set ⇒ crew-level (all crew members see). `Page.space_id` set ⇒ space-level. Crew default page is created with `crew_id=X, space_id=NULL`.
- On create, the creator is also inserted as `PageMember(role="owner")`. PageMember roles: `owner/admin/member/viewer` (per-page, distinct from crew roles).
- **Canonical crew page** = the **oldest** non-deleted page with that `crew_id` (`page.py:get_default_crew_page`, `order_by created_at asc limit 1`). `ensure_default_crew_page` returns it (Postgres advisory lock prevents two members forking on first entry). **Multiple crew pages can exist; "default" is implicit (oldest), not a flag.**

### B.4 Deletion (`page_service.delete_page`, lines 458-491)

```
if page.space_id is None:        # ← treats CREW pages as personal!
    only page.owner_id may delete
else (space page):
    page.owner_id OR pages.delete (space owner) may delete
```

### B.5 Already fixed this session

- **Child-resource gate (PR #561, in CI):** comments / conversations / chat-sessions / export now validate page access via `get_page` (crew/space member fallback). Previously a non-member could read/write them.
- **Membership freshness (#599) + member-aware selectors (#600):** merged.

---

## C. Gap inventory (the part Lucas cares about most)

| # | Gap | Evidence | Risk |
|---|---|---|---|
| **G1** | **Convergence fails for 2nd member.** Layout `await ensureCrewPage(...)` but ignores the returned page and never `setCurrentPage`s it (`layout.tsx:515-519`); then `page.tsx:369-388` falls back to **creating a `type:'personal'` page** when no active page id is set → user is "asked to create a new page" instead of joining the canonical one. | layout.tsx / page.tsx | **High** — breaks collaboration (the reported bug) + litters personal pages |
| **G2** | **Create role not enforced against the target crew.** `POST /pages` calls `assert_permission("pages.create")` with **no crew/space context** → resolves via *best role anywhere*. `create_page` then validates only crew **membership**, not role ≥ editor. So a **viewer in crew B who is editor in crew A can create a page in B**; role vs the actual target is never checked. FE hides the button (crew-role aware) → **FE/BE mismatch**. | pages.py:131, page_service create_page, rbac_service:1095 | **High** — viewers can create via API; cross-crew privilege leak |
| **G3** | **Crew page deletion mis-governed.** `delete_page` treats crew pages (`space_id=NULL`) as **personal** → **only the creator** can delete; the **crew owner cannot** moderate/remove it, and a mere **editor who created** it can delete a shared page others depend on. | page_service.py:458-491 | **High** — no crew-owner moderation; accidental loss of shared canvas |
| **G4** | **Canonical page unprotected & implicit.** "Default" = oldest-by-created_at, no flag. Deleting it silently promotes the next-oldest (possibly a random member's page) as the new convergence anchor; nothing guards the anchor. | get_default_crew_page | **Med/High** — collaboration room silently moves; chat/widgets "disappear" |
| **G5** | **Edit not enforced against target crew** (same shape as G2). Widget mutations use `pages.edit` via best-role-anywhere → an editor-elsewhere can edit a crew's content where they're only a viewer. | widgets.py + rbac fallback | **Med** — cross-crew write leak |
| **G6** | **FE personal-page fallback pollution.** `page.tsx` creates `type:'personal'` pages as a generic fallback even inside crew/space context. | page.tsx:369-388 | **Med** — stray personal pages, confuses convergence |
| **G7** | **No "page list" UI surfaced for crew** (to be confirmed). If members can't see/switch to a 2nd crew page, collaboration on non-default pages is impossible even when the data allows it. | FE pickers | **Med** — usability/governance |

---

## D. Benchmark — how comparable tools govern collaborative pages

| Platform | Container | Who **creates** | Who **edits** | Who **deletes** | Default/home | Ownership model |
|---|---|---|---|---|---|---|
| **Confluence** | Space | members with "Add page" (≈ contributor) | edit perm; page-level restrictions can narrow | page creator, space admin, or "delete" perm | **Space homepage — protected** | creator recorded; space admin overrides everything |
| **Notion** | Teamspace | members with edit access | Full / Edit access levels | Full-access users + workspace owner | Teamspace home | per-page access (Full/Edit/Comment/View); inherits from parent |
| **Miro** | Team / Project | members (editor+) | editors | board **owner / co-owner**, team admin | — | board owner; admin can reassign |
| **Power BI** | Workspace | **Contributor+** | Contributor+ | **Admin / Member** | — | workspace-governed; publisher recorded, not a veto |

**Universal pattern:** Viewer = read-only (no create). Editor/Contributor = create + edit. Owner/Admin = delete + manage + reassign. The container's **home/default is protected** from casual deletion. Content is **owned-by-creator but governed by the container role** — the creator does not get a private veto; the space/team owner/admin can always manage it.

➡️ This maps cleanly onto Sky's `crew viewer / editor / owner`. We are **not** doing anything exotic — we're aligning with the industry norm. The current gaps (G2/G3) actually *deviate* from it (creator-veto on delete; role not checked against the target).

---

## E. Proposed model

### E.1 Canonical crew page ("Team Canvas")
- Exactly **one default page per crew**, created on crew creation (mirror `create_space` → default General crew; here: crew → default page), so it always pre-exists and convergence never has to create on entry.
- Mark it explicitly: add `Page.is_default` (or reuse a flag) instead of "oldest wins". Convergence targets the flagged default.
- **Protected:** the default page **cannot be deleted**; only the **crew owner** can rename it. If a crew must change its anchor, owner sets another page as default first.

### E.2 Additional crew pages
- **Create:** crew **editor+** (enforced against *this* crew). Viewer cannot.
- **View:** all crew members (viewer+).
- **Edit (widgets/content):** crew editor+.
- **Delete:** the **creator** OR the **crew owner** (owner can moderate any crew page). Never a non-member; never the protected default.
- **Rename / set-default:** crew owner (and creator for their own non-default page — open decision).
- Ownership: `owner_id` = creator (shown as "created by"), but the **crew owner governs** (delete/reassign), matching Confluence/Power BI.

### E.3 RBAC matrix (target)

| Action | Crew viewer | Crew editor | Crew owner | Platform admin (non-member) |
|---|---|---|---|---|
| View crew page | ✅ | ✅ | ✅ | ❌ (Option B — content) |
| Create crew page | ❌ | ✅ | ✅ | ❌ |
| Edit widgets/content | ❌ | ✅ | ✅ | ❌ |
| Delete own non-default page | ❌ | ✅ (own) | ✅ | ❌ |
| Delete others' non-default page | ❌ | ❌ | ✅ | ❌ |
| Delete default page | ❌ | ❌ | ❌ (must unset first) | ❌ |
| Rename / set default | ❌ | own (open) | ✅ | ❌ |

*Open decision:* should platform admin (non-member) be able to delete a crew page for governance/cleanup? Default proposal: **no** (keep Option B clean; a crew owner moderates). Lucas to confirm.

---

## F. Use-case catalog (to be fully tested)

1. Crew **owner** creates a 2nd page → succeeds, page is crew-scoped, visible to all members.
2. Crew **editor** creates a page → succeeds.
3. Crew **viewer** creates a page (via UI and via **direct API**) → denied (403).
4. Editor-in-crew-A, **viewer-in-crew-B**, creates a page in **B** → denied (closes G2).
5. Member **enters crew** (default exists) → lands on the **default page**, not asked to create (closes G1).
6. **Two members** enter an empty crew simultaneously → exactly one default page, both converge (advisory lock).
7. Member opens a **non-default** crew page another member is on → both collaborate (live cursors), no 404.
8. **Viewer** opens a crew page → can view, cannot edit widgets.
9. **Creator (editor)** deletes their own non-default page → succeeds; members on it are moved to default.
10. **Editor** tries to delete **another member's** crew page → denied; **crew owner** can (closes G3).
11. Anyone tries to delete the **default** page → denied (closes G4).
12. **Non-member** tries view/create/delete/comment/chat on a crew page → denied 404 (incl. #561 child resources).
13. Member **removed from crew** while on a crew page → loses access on next action (masked/redirected).
14. **Crew deleted** while a member is on its page → graceful redirect, no orphan canvas.
15. Set a different page as **default** → convergence anchor moves deterministically; old default becomes a normal page.
16. **Personal** page creation still works and never gets a crew_id (no scope bleed).

## G. Test matrix (automated)

| Layer | Tests |
|---|---|
| **BE unit (RBACService/Authorization)** | viewer-in-target denied create/edit/delete; editor-in-target allowed; cross-crew leak (UC4) denied; crew-owner delete-any allowed; default-page delete denied. |
| **BE API (async_client)** | UC1-3, 8-12, 16 as HTTP 201/403/404; #561 child-resource gates (already added in `test_page_child_access.py`). |
| **BE convergence** | `ensure_default_crew_page` idempotent across 2 members (exists in `test_conversations.py`); add: default created on crew creation; set-default moves anchor (UC15). |
| **FE unit (vitest)** | create button hidden for crew viewer; delete action hidden unless creator/owner; default page shows no delete. |
| **FE store** | entering a crew with an existing default sets `currentPage` = default (UC5); no personal-fallback fired in crew context (closes G6). |
| **E2E (Playwright)** | two browsers, two members, same crew → same page id + visible cursors; viewer cannot create; owner deletes a member's page. |

## H. Adversarial / stress scenarios ("try to destroy")

1. **Bypass FE, hit API directly** as a crew viewer → must 403 on create/edit/delete.
2. **Privilege borrow:** editor-in-A calls create with crew B's id while only viewer in B → must 403 (G2/G5).
3. **Delete the anchor mid-collaboration:** owner/creator deletes the page everyone is on → must be blocked if default; if non-default, all members get redirected to default (no white screen, no orphaned chat/widgets).
4. **Race:** N members enter a brand-new crew within the same 100 ms → exactly ONE default page exists afterwards.
5. **Concurrent delete + edit:** member A deletes a page while member B adds a widget to it → no partial/orphan rows; B gets a clean 404.
6. **Removed-mid-session:** remove a member from the crew while they have the page open, then they add a widget / send a chat → denied (content mask + 404), no stale write.
7. **Cross-tenant:** a user from tenant X with a guessed crew/page UUID from tenant Y → 404 (tenant isolation holds for every page child route).
8. **Default reassignment loop:** set-default A→B→A rapidly → anchor always resolvable, never zero defaults, never two.
9. **Orphan child resources:** delete a page with conversations/chat-sessions/comments → cascade or block cleanly (no dangling rows that later 500).
10. **Demo/guest sandbox** unaffected (single-user convergence path stays).

## I. Decisions (Lucas, 2026-06-16) — LOCKED

1. **Platform admin (non-member) deletion** of a crew page: **NO.** Only creator + crew owner. (Keeps Option B clean.)
2. **Editor deleting their own** non-default crew page: **YES.** Crew owner can delete any; a non-creator editor cannot delete others'.
3. **Set-default**: deferred (no reassignment UI in this lot — see #4).
4. **Explicit `is_default` column:** **deferred** to avoid the shared-alembic migration risk (it caused a prod incident before — see [[skyfirst-alembic-version-conflict]], [[skyfirst-tenant-db-migration-gap-conversations]]). For now "default = oldest crew page" and **that page is protected from deletion** (no schema change). An explicit flag + set-default can follow once we're ready to migrate.
5. **Sequencing:** **all in one tested lot** (not a G1 hotfix first). G1+G2+G3+G4 land together, only after the §G tests + §H stress pass.

## J. Implementation status (this lot)

| Gap | Layer | Change | Status |
|---|---|---|---|
| G2 | BE | `create_page` requires editor+ in the **target** crew/space (`assert_permission` with `crew_id`/`space_id`), not "editor anywhere" | ✅ coded + tests |
| G3 | BE | `delete_page` crew branch: creator **or** crew owner; non-members/viewers/non-creator-editors denied | ✅ coded + tests |
| G4 | BE | crew **default** (oldest) page protected from deletion; bare `pages.delete` endpoint check removed (service is sole authority) | ✅ coded + tests |
| G1 | FE | convergence: use `ensureCrewPage` result as `currentPage`; stop the `page.tsx` personal-page fallback in crew/space context | ⏳ next |

Tests: `src/tests/test_crew_page_governance.py` (8 cases incl. cross-crew leak + default protection) + `test_page_child_access.py` (#561). Run in CI (local async_client blocked by httpx mismatch).
