# Internal Console — Security Posture (2026-05-30, pre-GBT deploy)

Snapshot of `/api/console/v1/*` and the FE `/console` routes ahead of
the GBT customer deploy. Scope is the Internal Console only — customer
data planes and the public `/api/v1/*` surfaces are out of scope.

## Surface × Defence matrix

| Surface | Defence | Status | Notes |
|---|---|---|---|
| `/api/console/v1/*` route group | `Depends(require_sky_team)` on every handler | OK | `src/api/console_auth.py::require_sky_team`. Falls back to 401 when no JWT, 403 when authenticated but not Sky-team. Distinct status codes let the FE route correctly (re-login vs access-denied page). |
| JWT validation | `get_current_user` reuses the standard auth flow | OK | Console uses the same JWT verification as the rest of the API; no separate token issuer. |
| Sky-team membership signal | Three-way check: `users.is_sky_operator` + `CONSOLE_ALLOWED_EMAILS` env CSV + `CONSOLE_DEV_BYPASS` env | OK | Canonical signal is the DB column. Env CSV is the onboarding override. Dev-bypass refuses to take effect when `ENVIRONMENT == "production"` — defence in depth. |
| Console RBAC (read/write/destroy split) | `console_rbac.assert_permission` on sensitive endpoints | OK | Role catalogue in `src/services/console_rbac.py`. Action keys (`rbac.write`, `audit.export_dsar`, `support.write`, `compliance.write`, `impersonate`, `revenue.read`) gate the write paths. |
| Audit log | `audit_action` on every state-changing call | OK | `internal_console_audit` row written with actor email, IP, action, target tenant, redacted payload, result. Failure path writes too (`AuditResult.FAILURE`). |
| Audit log on tier-change FAILURES | dedicated failure entry with `reason: downgrade_exceeds_new_caps` | OK | Added in this PR — every 422 from `change_tenant_tier` writes a discoverable audit row. |
| Payload redaction in audit | `_REDACT_KEYS = {password, secret, token, authorization}` | OK | `_redact` helper in `console.py` + `_safe_extract_payload` in `console_auth.py`. |
| Tier-change escalation | 422 when `capacity_used` exceeds new tier caps + `apply_preset=true` | OK | This PR. Override path (`apply_preset=false`) is logged and intentional. |
| Idempotency on tier-change | No-op when picked tier equals current; no spurious audit row | OK | This PR (`tier_actually_changed` guard). |
| DI safety on `require_sky_team` | `db` resolved explicitly, not via `Depends` inside the function body | OK | `console_auth.py` lines 91-97 documents the historical bug fixed by PR #492-ish; integration regression in `src/tests/test_console_auth_di_fix.py`. |
| FE access guard | `useAccess` hook + middleware redirect on 401/403 | OK | `src/middleware.ts` + `src/hooks/useAccess.ts` route 401 → `/login`, 403 → `/console/no-access` per the unauth-vs-non-sky-team distinction. |
| Demo-signup hardening (`@skyfirstlabs.com` block) | PR #464 — refuses to create demo accounts with Sky emails | OK | `src/services/demo_service.py` rejects with 403 + audit. Test in `src/tests/test_demo_signup.py`. |
| Demo signup email gate | PR #522 — verification email required before demo provisioning | OK | `src/services/demo_email_service.py`. Token TTL'd, single-use, audit-logged. |
| Suspend / destroy actions | Phrase confirmation + slug match | OK | `DestroyTenantRequest` requires both `confirmation_slug` and the literal phrase `"I understand this is irreversible"`. Audited even on confirmation failure. |
| Impersonation | Explicit `customer_consent=true` + reason ≥ 10 chars + ticket id | OK | `start_impersonation` enforces all three at request time. Session row + audit row + impersonation log. |
| WebSocket log streamer | Tenant-existence check before stream starts | OK | `/tenants/{slug}/logs/stream` rejects unknown slugs with `tenant_not_found` and closes. Does NOT yet enforce `require_sky_team` for the WS handshake — see Gap 1. |
| Rate limiting on `/api/console/v1/*` | None today | ⚠ | Console traffic shares the global rate-limit bucket. Distinct path prefix was chosen to support a separate bucket later (`console.py` line 4 docstring); the bucket itself is not configured. |
| CORS | Same origin policy via FastAPI CORS middleware | OK | Configured in `src/main.py` — limited to known frontend origins. |
| TLS / HTTP→HTTPS | Terminated at the LB | OK | Out-of-band; not enforced at the Python layer. |

## Gaps recommended for pre-GBT-deploy attention

1. **Console WebSocket lacks Sky-team gate.** The HTTP routes go through `require_sky_team`, but `stream_tenant_logs` only validates that the tenant exists. A non-Sky-team but authenticated user could open the WS and tail mock log lines. With real `kubectl logs --follow` wiring this becomes a data-exfiltration vector. Fix: read the JWT from the WS `subprotocol` (the FE already supports it) and call `is_sky_team_member` before `await websocket.accept()`.

2. **No dedicated rate-limit bucket for `/api/console/v1/*`.** Console traffic shares the platform bucket; a chatty operator UI can starve the customer-facing rate limit. Pre-deploy this is low risk (≤5 simultaneous Sky operators), but worth doing before broadening Console access beyond the engineering team.

3. **Audit log is best-effort.** `audit_action` swallows write errors. Deliberate (per the docstring — losing a log row is better than refusing a destroy that already ran) but means we can't legally use the audit feed as compliance evidence without an out-of-band durable sink. Recommend dual-write to S3 with bucket lock for the actions that matter most: `DESTROY_TENANT`, `GRANT_ROLE`, `REVOKE_ROLE`, `IMPERSONATE_*`, `CHANGE_TIER`.

4. **Tier change does not check `tenant_plan_limits`.** Today the downgrade-safety check reads `tenant_registry.capacity_used`. Once Pricing Fase 1 ships, the live counters live in `tenant_plan_limits` (`current_*` columns). Tier change should consult both tables so the operator isn't blindsided when a downgrade looks safe by `capacity_used` but blows past the live AI-query counter.

5. **`CONSOLE_DEV_BYPASS` should refuse staging too.** Today it disables in `production` only; staging is a public-facing environment used by sales demos and a leaked env var there would expose the Console. Tighten the check to `("production", "staging")`.

6. **Impersonation has no TTL.** `ConsoleImpersonationSession.ended_at` is set on explicit end-call, but a forgotten session stays open indefinitely. Recommend hard cap (e.g. 30 minutes) enforced by a scheduled Celery beat that auto-ends old sessions.

## Conclusion

The Console is acceptable for the GBT customer deploy provided the WebSocket Sky-team gate (Gap 1) is closed before any non-mock log stream lands. Everything else is pre-existing posture that can be hardened post-deploy without blocking GBT — the customer never sees `/console` directly.
