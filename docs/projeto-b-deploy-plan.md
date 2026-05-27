# Projeto B — Deploy plan (staging → production)

**Date:** 2026-05-27
**Owner:** Lucas (approval) · Claude (preparation)
**Status:** Ready for staging deploy after approval

> What follows is the exact sequence to ship Projetos A + B to
> staging + production. Tested every step locally; staging is the
> first time it touches managed infrastructure. Read end-to-end
> before kicking anything off.

---

## 1. What's shipping

### Backend (`sky-first/sky-backend`) — 9 commits
* Projeto A (Model B multi-tenant resolver, tenant registry, conn manager, dual-pool)
* Projeto B core (Console API, telemetry providers, CSM, RBAC, compliance, support, polish)
* 7 alembic migrations: tenant_registry → internal_console → csm_notes → role_grants → compliance → support
* New `version_table="alembic_version_be"` in env.py (sky-be no longer shares the legacy `alembic_version` table with sky-ai)

### AI service (`sky-first/sky-ai`) — 1 commit
* Tenant context propagation
* Per-tenant Bedrock Application Inference Profile lookup

### Frontend (`sky-first/sky-frontend`) — 4 commits
* Projeto A (subdomain-aware client + tenant-scoped Zustand state)
* Projeto B (Console `/console/*`, sidebar collapsible, ⌘K palette, charts, RBAC gating)

---

## 2. Pre-flight checks (run before pushing)

| Check | How | Last run |
|---|---|---|
| Local alembic chain valid | `alembic upgrade head` against local docker postgres | OK |
| Local alembic version table separated | `migrate_alembic_version_table.py` moved head OK | OK |
| Backend tests | 25/25 (auth + models + tenant_*) | OK |
| Frontend tests | 28/28 (tenant + console) | OK |
| E2E smoke (Projeto A) | `scripts/smoke_multi_tenant.py` | OK |
| Console endpoints respond | 23+ endpoints under `/api/console/v1/*` | OK |
| CORS includes staging origins | `CORS_ORIGINS` env contains `workspace-*.skyfirstlabs.com` | **needs check at deploy** |

---

## 3. Critical: alembic version table separation

**Why it matters.** Sky-be + sky-ai share one Postgres database in
staging + prd; they each have their own migration script tree but
historically both used the default `alembic_version` table — the
known cause of every "Can't locate revision identified by 'XYZ'"
error during deploys (see `skyfirst-alembic-version-conflict`
memory).

**What we did.** `migrations/env.py` now passes
`version_table="alembic_version_be"`. From this commit forward,
sky-be reads/writes only its own table; sky-ai keeps `alembic_version`.

**Bootstrap step required ONCE per environment (staging, then prod):**

```bash
# Reach the DB via the sky-be pod (we have psql in the image)
kubectl --context stg exec -it deploy/sky-be-stg-aws-common-app -- /bin/bash

# Inside the pod, run the migration script.
# DATABASE_URL is already in the pod env.
cd /app
python scripts/migrate_alembic_version_table.py --expected-head console_support_20260527
```

The script:
1. Reads sky-be revisions from the deployed script tree
2. Finds the sky-be row inside legacy `alembic_version`
3. Creates `alembic_version_be` (if missing) and inserts that row
4. Removes the sky-be row from the legacy table — leaves sky-ai's rows alone

Repeat the exact same command on production once staging is green.

**Verify after the script** (still inside the pod):

```bash
psql $DATABASE_URL -c "SELECT * FROM alembic_version_be; SELECT * FROM alembic_version;"
# alembic_version_be should contain 'console_support_20260527'
# alembic_version should contain only sky-ai's revisions
```

---

## 4. Env vars audit (what staging + prod need)

### Backend (sky-be Helm chart)

| Var | Staging value | Production value | Purpose |
|---|---|---|---|
| `MULTI_TENANT_ENABLED` | `false` (default OFF) | `false` initially | Projeto A flag. Stays OFF until per-tenant DBs ready |
| `TENANT_DB_URL_TEMPLATE` | empty | empty | Filled when Model B clusters provisioned |
| `CONSOLE_DEV_BYPASS` | `false` (REQUIRED) | `false` (REQUIRED — refused if production) | Refuses to grant auth without real JWT |
| `CONSOLE_DEV_BYPASS_EMAIL` | — | — | Only relevant when dev_bypass on (never in prod) |
| `CONSOLE_ADMIN_EMAILS` | `lucas.ventura@skyfirstlabs.com` | same | CEO bootstrap auto-grant |
| `CONSOLE_OPERATOR_EMAILS` | optional CSV | same | Convenience role pre-seeding (rare) |
| `CONSOLE_MOCK_INFRA` | `true` initially | `true` initially | Mocks until kubectl + Cost Explorer wired |
| `KUBECONFIG_STAGING` | (when CONSOLE_MOCK_INFRA=false) | n/a | Path to kubeconfig for stg cluster |
| `KUBECONFIG_PROD` | (when CONSOLE_MOCK_INFRA=false) | (when off) | Path to kubeconfig for prd cluster |
| `AWS_REGION` | `eu-west-1` | same | Cost Explorer + Bedrock |
| `MOLONI_API_KEY` | (deferred — set when wiring) | same | Real billing |
| `MOLONI_BASE_URL` | optional override | optional | Defaults to api.moloni.pt/v1 |
| `MOLONI_COMPANY_ID` | required when wiring | same | SkyFirst's Moloni company id |
| `ARGOCD_BASE_URL` | `https://argocd.skyfirstlabs.com` | same | Used in tenant_health "open in ArgoCD" |
| `GRAFANA_BASE_URL` | `https://grafana.skyfirstlabs.com` | same | Used in tenant_health "open in Grafana" |
| `CORS_ORIGINS` | extend with `https://workspace-*.skyfirstlabs.com,https://api-*.skyfirstlabs.com,https://console.skyfirstlabs.com` | same | Console + tenant subdomain support |

### Frontend (sky-fe Helm chart)

| Var | Staging | Production |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api-stg.skyfirstlabs.com/api` (or rewrite) | `https://api.skyfirstlabs.com/api` |
| `NEXT_PUBLIC_CONSOLE_API_URL` | `https://api-stg.skyfirstlabs.com` | `https://api.skyfirstlabs.com` |

The Next.js `next.config.ts` has a rewrite for `/api/console/v1/*` →
`CONSOLE_API_TARGET` so same-origin requests also work; pick whichever
suits the Helm value file.

### AI service (sky-ai)
No new env vars beyond Projeto A's `MULTI_TENANT_ENABLED`.

---

## 5. Staging deploy sequence

1. **PRs merged into staging branches** (sky-backend, sky-ai, sky-frontend):
   ```bash
   gh pr merge <#PR_be> --squash --admin -R sky-first/sky-backend
   gh pr merge <#PR_ai> --squash --admin -R sky-first/sky-ai
   gh pr merge <#PR_fe> --squash --admin -R sky-first/sky-frontend
   ```
2. **GitHub Actions in each repo:** CI builds images, ArgoCD Image
   Updater bumps `:staging` tag → `gitops/charts/common-app/values-*-stg-aws.yaml`
   gets a SHA via the auto-bump workflow.
3. **Update Helm values for new env vars** (manually edit those files
   in `sky-poc-infra`/staging branch — `CONSOLE_ADMIN_EMAILS`,
   `CORS_ORIGINS` extension, `CONSOLE_MOCK_INFRA=true`,
   `CONSOLE_DEV_BYPASS=false`).
4. **Apply DB version table bootstrap** (see §3) — open shell into
   sky-be-stg pod, run `migrate_alembic_version_table.py`. **MUST
   happen BEFORE sky-be migrate Job runs again.**
5. **ArgoCD reconciles**, sky-be pods restart with new image. The
   migrate Job runs `alembic upgrade head` against
   `alembic_version_be` (now populated) — applies the 5 new
   migrations:
   - `internal_console_20260527`
   - `console_csm_notes_20260527`
   - `console_role_grants_20260527`
   - `console_compliance_20260527`
   - `console_support_20260527`
6. **Smoke test staging Console:**
   ```bash
   curl https://api-stg.skyfirstlabs.com/api/console/v1/me \
        -H "Authorization: Bearer <JWT>"
   # → 200 with email + role + is_sky_team

   curl https://api-stg.skyfirstlabs.com/api/console/v1/dashboard \
        -H "Authorization: Bearer <JWT>"
   # → 200 with total_tenants + active + by_tier
   ```
7. **Browser smoke:** `https://app-stg.skyfirstlabs.com/console`
   (or whichever staging URL) — confirm Overview loads, ⌘K opens,
   /console/tenants lists existing tenants.

---

## 6. Production promote

After staging green for at least 1h (per the
`skyfirst-promote-to-prod-flow` memory):

1. Capture staging SHAs:
   ```bash
   grep "tag:" sky-poc-infra/gitops/charts/common-app/values-sky-be-stg-aws.yaml
   grep "tag:" sky-poc-infra/gitops/charts/common-app/values-sky-fe-stg-aws.yaml
   grep "tag:" sky-poc-infra/gitops/charts/common-app/values-sky-ai-stg-aws.yaml
   ```
2. Trigger promote workflow:
   ```bash
   gh workflow run promote-to-production.yml -R sky-first/sky-infra \
     -f apps=sky-frontend,sky-backend,sky-ai \
     -f fe_sha=<...> -f be_sha=<...> -f ai_sha=<...>
   ```
3. Approve the `production` env gate in GitHub Actions.
4. Workflow re-tags ECR images, bumps prd values files, opens PR
   staging→main on sky-infra.
5. Merge the PR with `gh pr merge --admin` (Lucas is in bypass list
   for main).
6. **Run `migrate_alembic_version_table.py` against prod RDS** (see §3
   — **MUST happen before prd pods restart with new alembic env**).
7. ArgoCD reconciles prd, sky-be migrate Job applies the 5 new
   migrations to prod RDS.
8. Production smoke test (same as staging step 6, against prod URLs).

---

## 7. Rollback

### Application rollback
Standard ArgoCD rollback — point image SHA back to previous in the
values file and reconcile:
```bash
git revert <bump_commit> -m1 && git push
# ArgoCD reconciles, pods recreated with previous SHA
```

### Migration rollback
The 5 new migrations are **idempotent** (every one has
`inspector.has_table` / `IF NOT EXISTS` guards). To roll back:
```bash
kubectl --context stg exec -it deploy/sky-be-stg-aws-common-app -- \
  alembic downgrade -1
# Repeat 5 times to undo all five migrations
```
Note: rollback drops tables — recovery requires restoring from
backup. Confirm we have an RDS snapshot before kicking off.

### Console-only rollback
If only the Console layer needs to come down (multi-tenant resolver
already in prod):
* Set `CONSOLE_MOCK_INFRA=true` (just disables real telemetry)
* Set `CONSOLE_DEV_BYPASS=false` and remove CONSOLE_ADMIN_EMAILS
  (denies all access; routes 403)
* Or revert the sky-fe image SHA back — `/console` 404s while the
  rest of the platform keeps working

### Tenant resolver rollback
If Model B multi-tenancy misbehaves:
* Set `MULTI_TENANT_ENABLED=false` (single-tenant fallback, validated
  by 90+ unit tests)

---

## 8. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Alembic version conflict | **medium** | breaks migrate Job | `migrate_alembic_version_table.py` (this PR) |
| New CORS rules break existing frontend | low | login broken | Tests against staging in step 6 |
| RBAC bootstrap fails (no admin granted) | low | nobody can open Console | `CONSOLE_ADMIN_EMAILS=lucas.ventura@skyfirstlabs.com` |
| Mock infra exposed in prod | low | confusing data | `CONSOLE_MOCK_INFRA=true` defaulted; flip to false only after kubectl/AWS wired |
| Real-provider AWS calls cost $$ | low | unexpected Cost Explorer charges | Cost Explorer ≤ $0.01/request; bounded |
| Frontend `/console` accessible to customers | **medium** | data leak | Backend `require_sky_team` enforces; UI hide is UX-only — confirm before opening to customer tenants |
| sky-ai migrate Job sees `alembic_version_be` | low | confused stamp | sky-ai's env.py still uses default `alembic_version` — separate trees |

---

## 9. Open follow-ups (post-deploy)

* Wire real `KubernetesInfraProvider` (requires kubeconfig secrets in
  k8s) — switch `CONSOLE_MOCK_INFRA=false` once tested
* Wire real `AwsCostProvider` (requires IRSA role with `ce:Get*` on
  Cost Explorer + Bedrock Application Inference Profile per-tenant
  setup)
* Wire `MoloniBillingProvider` (requires API key + customer-by-slug
  lookup field implementation)
* Grant Gustavo + Paulo their non-CEO roles via `/console/settings`
  once they have JWTs

---

## 10. Sign-off checklist (Lucas)

- [ ] Read this document
- [ ] Approve push of 3 branches to GitHub
- [ ] Approve PR merges to staging branches
- [ ] Run `migrate_alembic_version_table.py` against staging RDS
- [ ] Validate `/console` works in staging
- [ ] Trigger `promote-to-production.yml`
- [ ] Run `migrate_alembic_version_table.py` against production RDS
- [ ] Validate `/console` works in production
