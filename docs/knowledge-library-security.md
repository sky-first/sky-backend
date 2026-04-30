# Knowledge Library — Security & Auditability Model

> Last reviewed: 2026-04-30 (Lucas's drop-zone audit)

The Knowledge Library accepts user uploads (PDF, TXT, MD, CSV, DOCX, XLSX)
and turns them into chunked embeddings the AI can cite. Because the AI
will quote those chunks back as "facts", every file that lands in the
context store must be traceable to a human who chose to put it there.
This document captures the model.

---

## 1. RBAC matrix (per scope)

| Role | View | Upload | Approve | Reprocess | Delete |
|------|:----:|:------:|:-------:|:---------:|:------:|
| **Platform Owner / Admin** | ✅ | ✅ direct | ✅ | ✅ | ✅ |
| **Commander** (Space / Crew) | ✅ | ✅ direct → `processing` | ✅ | ✅ | ✅ |
| **Navigator** (Space / Crew) | ✅ | ✅ → **`pending_approval`** | ❌ | ❌ | ❌ |
| **Explorer** (Space / Crew) | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Guest** | view-only | ❌ | ❌ | ❌ | ❌ |

Source of truth:
- `src/services/knowledge_service.py::_assert_scope_access`
- `src/services/rbac_service.py::DEFAULT_ROLE_PERMISSIONS` (`files.*` keys)

## 2. Status state machine

```
            ┌─────────┐
upload-url  │ pending │   confirm endpoint not reached yet
─────────►  └────┬────┘
                 │
       confirm() resolved
                 │
   ┌─────────────┴─────────────┐
   │                           │
   ▼                           ▼
┌───────────────┐     ┌────────────────────┐
│  processing   │     │  pending_approval  │  ← navigator upload, awaits commander
│  (worker)     │     └─────────┬──────────┘
└──────┬────────┘               │ approve()
       │                        │
       │  ┌─────────────────────┘
       ▼  ▼
   ┌────────┐    ┌────────┐
   │ ready  │    │ error  │
   └────┬───┘    └────────┘
        │
        ▼
   visible in Universe Intelligence (Knowledge → Library)
   citable by AI chat / agents
```

A file is **only chunked + embedded after status flips to `processing`**.
Files in `pending` or `pending_approval` never enter the context store —
they cannot poison answers.

## 3. Upload guards (defense in depth)

| Layer | Guard | Where |
|-------|-------|-------|
| Client | File picker accepts whitelisted extensions only (cosmetic — never trust client) | FE Knowledge Library UI |
| API gate | RBAC `files.upload` per scope/role; quota check + lock | `request_upload_url` |
| API gate | MIME whitelist (`ALLOWED_MIMES`) | `request_upload_url:142` |
| API gate | Size limit `FILE_MAX_BYTES = 15 MB` | `request_upload_url:144` |
| Storage | Time-limited SAS URL (10 min TTL, write-only, exact mime + size) | `generate_upload_sas_url` |
| Approval | Navigator uploads block on `pending_approval` until commander approves | `confirm_upload:202` |
| **Audit** | `audit_events` row on every upload-requested / confirmed / approved / deleted / reprocessed | `knowledge_service._audit` |

## 4. What's intentionally NOT in code yet

These are deferred and require Lucas's call before shipping:

### 4.1 Virus scan
**Recommended:** Microsoft Defender for Storage — toggle in the Azure
Storage account, runs antimalware on every blob upload, tags each blob
with `Malware Scanning result`. We listen via Event Grid and either
quarantine the blob or auto-delete the row if `Malicious`. No code in
our service required, ~$0.30/GB/month.

Alternative: ClamAV daemon as a sidecar — more infra, more cost,
similar functionality.

**Decision needed:** confirm Defender for Storage spend → I add the
Terraform toggle + Event Grid handler.

### 4.2 SHA256 verification mandatory
Today the `sha256_hash` field is optional. The FE should:
1. Hash the file in the browser (Web Crypto, ~50 ms for 15 MB).
2. Send hash with the `confirm` request.
3. BE re-hashes the blob on confirm and rejects on mismatch.

This catches transit corruption AND gives us a fingerprint for
deduplication ("this file is the same as one you already approved").

### 4.3 Citation provenance
When the AI cites a chunk, today we show only the file name. To close
the audit loop the citation should include:

```
Source: report.pdf
  uploaded by Lucas Ventura, 2026-04-30 14:22 UTC
  approved by Lais Bispo, 2026-04-30 14:25 UTC
```

This is FE work in `ai-search-bar.tsx` citation rendering — pull
extra fields from the `KnowledgeFile` joined response.

### 4.4 "Untrusted" badge / quarantine flow
Even after approval, mark every file with a confidence tag:

- **Verified** = uploaded by owner/admin OR approved by commander after
  manual review.
- **Provisional** = approved but the commander didn't open the preview
  before approving (track via `approved_after_preview: bool`).
- **Quarantined** = Defender for Storage flagged it; chunks
  immediately removed from context, owner notified.

The AI prompt should weight Verified > Provisional and refuse to cite
Quarantined sources.

## 5. Audit query examples

```sql
-- All file-related actions in the last 7 days
SELECT occurred_at, actor_email, action, decision, metadata
FROM audit_events
WHERE resource_kind = 'knowledge_file'
  AND occurred_at >= now() - interval '7 days'
ORDER BY occurred_at DESC;

-- Trace a specific file's lifecycle
SELECT occurred_at, actor_email, action, decision_reason, metadata
FROM audit_events
WHERE resource_id = '<file_id>'
ORDER BY occurred_at ASC;

-- Files approved by a given commander
SELECT actor_email, COUNT(*) as approvals
FROM audit_events
WHERE action = 'knowledge.upload.approved'
GROUP BY actor_email
ORDER BY approvals DESC;
```

## 6. Open items

- [ ] Decide on Defender for Storage (Lucas, billing call).
- [ ] Make SHA256 mandatory client + server.
- [ ] Citation provenance UI in chat.
- [ ] Verified / Provisional / Quarantined badge on file rows.
- [ ] Add a "Files" entry in the left toolbar (separate from "Knowledge")
      so the affordance is one click closer for commanders.
