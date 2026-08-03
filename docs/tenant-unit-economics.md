# Tenant Unit Economics — design

**Status:** backend implemented (2026-08) · frontend pending · **Owner:** Console / Cost
**Goal:** per-tenant *fully-loaded* cost + margin, and a platform view that shows margin improving with scale — the quantified "value of the architecture" story.

> **2026-08 revision.** The original proposal assumed each tenant owned dedicated
> AWS resources billable through a `tenant` cost-allocation tag. It does not.
> §3 has been rewritten with what onboarding actually provisions and why the
> tag plan was dropped. §1 loses the `Dedicated` term accordingly.

---

## 1. The model

For each active tenant, over a window (default 30d, normalised to a month):

```
Cost(tenant)   = SharedAlloc(tenant) + LLM(tenant)
Margin(tenant) = MRR_usd(tenant) − Cost(tenant)
```

- **SharedAlloc(tenant)** — the tenant's slice of the shared platform (one BE, one AI service, EKS control plane, RDS, Redis, NAT, monitoring). Computed **two ways** (decision: show both):
  - **Equal** — `SharedTotal / N_active` → the "architecture cost": drops as N grows.
  - **Weighted** — `SharedTotal × activityShare(tenant)`, where `activityShare = tenantActivity / Σ tenantActivity`. The "real consumption cost".
- **LLM(tenant)** — token cost per tenant. **Authoritative** for LLM spend.

There is no `Dedicated(tenant)` term — see §3.

### Avoiding double-counting (Bedrock)
LLM cost is attributed per tenant from the Langfuse snapshots. If Bedrock also appears in the AWS CE `bedrock_usd` bucket, counting both double-charges. **Rule:** the shared pool **excludes** the Bedrock bucket.

```
SharedTotal = platform_cost.total_usd − platform_cost.bedrock_usd
```

Clamped at 0: credits and refunds can push a bucket negative, and a negative shared pool would hand every tenant a fictitious profit.

### Activity weight
`activity` is the tenant's LLM **request count** over the same window, read from `tenant_llm_daily_snapshots`. Chosen over query counters because it is already per-tenant, already persisted daily, and aligned to whole days like the AWS figures — `tenant_plan_limits.current_queries_this_month` is month-to-date and would reintroduce the window mismatch of §7. When total activity is zero the weighted split degrades to the equal split and the response sets `weighted_fell_back_to_equal`, so the UI can label it instead of presenting two identical columns as if they were independent.

## 2. The scale insight (why SaaS gets cheaper per tenant)

- **Marginal cost of tenant N+1** ≈ `LLM` (small; no new shared infra).
- It adds a **full MRR** → very high incremental contribution margin.
- **Blended margin** `= (Σ MRR_usd − Σ Cost) / Σ MRR_usd` rises as `SharedTotal / N` shrinks.

The Console shows a **"margin vs N tenants"** curve: hold current SharedTotal + avg LLM/MRR, sweep N → the curve that proves the architecture pays off with scale. Also surface **break-even N** and **marginal margin per new tenant**.

Break-even solves `N × avg_mrr ≥ SharedTotal + N × avg_llm`, i.e. `N ≥ SharedTotal / (avg_mrr − avg_llm)`, rounded up. When an average tenant's LLM spend already exceeds its MRR the margin never crosses zero no matter how many tenants are added, and `break_even_n` is `null` — scale is not a fix for negative unit economics.

## 3. Why there are no per-tenant AWS costs to tag

**What onboarding actually provisions.** `onboard-client.yml` is explicit: *"Option A — shared Postgres, schema-per-tenant"*, and *"Option B (per-tenant RDS instance) is deferred"*. For a new tenant `abc`:

| Resource | Dedicated? |
|---|---|
| Database | ✅ but **inside the shared RDS instance** |
| Secrets Manager entry (`sky/<env>/tenant-abc/db`) | ✅ |
| k8s namespace + Ingress/Services | ✅ |
| Route53 record | ✅ |
| ArgoCD Application | ✅ |
| RDS instance | ❌ shared |
| Redis | ❌ shared |
| Backend pods | ❌ **shared** — *"every tenant is served by the SHARED platform BE pod"*; the tenant is resolved from the `Host` header |

**Consequence.** The only AWS resource that is both per-tenant and independently billable is the Secrets Manager entry — roughly **0.40 USD/month**. A `tenant` cost-allocation tag would therefore report a rounding error as the tenant's infrastructure cost.

Note also that onboarding stamps `sky-tenant=<slug>` as a **Kubernetes label**, not an AWS resource tag, so it never reaches Cost Explorer at all.

**Decision: the tag plan is dropped.** No Billing activation, no 24h propagation, no `Dedicated` term. Everything shared is allocated per §1 instead. This is both more accurate *and* cheaper to build.

**If Option B ever ships** (per-tenant RDS), reintroduce `Dedicated(tenant)` sourced from a `tenant` cost-allocation tag, and subtract `Σ Dedicated` from `SharedTotal`. `src/services/unit_economics.py` documents this at the top so the next person does not re-derive it.

### What per-tenant cost is actually made of

1. **LLM tokens** — the only genuinely variable, cleanly attributable cost. Already snapshotted daily per tenant.
2. **Activity share** — queries + agent runs, used to weight the shared allocation.
3. **Storage** — `pg_database_size()` on the tenant's database. Comes from Postgres, not AWS. *(Not yet wired; would refine the weighted split.)*
4. **Shared infrastructure** — allocated, never measured per tenant, because it genuinely is shared.

## 4. API

```
GET /api/console/v1/dashboard/unit-economics?days=30      (sky-team only)
→ {
    window_days, n_active,
    platform_total_usd, bedrock_usd, llm_total_usd,
    shared_total_usd, mrr_total_usd,
    blended_margin_equal_pct, blended_margin_weighted_pct,
    break_even_n: int | null,
    marginal_cost_next_usd, marginal_margin_next_usd,
    weighted_fell_back_to_equal: bool,
    tenants: [{
      slug, display_name, tier,
      mrr_usd, llm_usd, activity_share_pct,
      shared_equal_usd, shared_weighted_usd,
      cost_equal_usd, cost_weighted_usd,
      margin_equal_usd, margin_weighted_usd,
      margin_equal_pct, margin_weighted_pct,
      llm_available: bool
    }],
    curve: [{ n, blended_margin_pct }]
  }
```

Implemented in `src/services/unit_economics.py`, split in two layers:

- `compute_unit_economics(...)` — pure arithmetic over plain inputs; no DB, AWS, or Langfuse, so the maths is unit-tested directly (`src/tests/test_unit_economics.py`).
- `build_unit_economics(db, days=...)` — composition: tenant registry, `tenant_llm_daily_snapshots`, `billing_provider()`, `cost_provider()`.

MRR is billed in EUR (Moloni) and costs are in USD (AWS); the service converts with `settings.EUR_USD_RATE` so the subtraction is apples-to-apples.

## 5. Frontend

New Console section **"Unit economics"**: per-tenant table (margin equal/weighted, cost breakdown), a toggle equal↔weighted, and the **margin-vs-N** curve with break-even and marginal-margin callouts. Surface `weighted_fell_back_to_equal` when set.

## 6. Rollout

1. ~~Backend service + endpoint~~ — **done**.
2. ~~AWS tag runbook~~ — **dropped**, see §3.
3. **Frontend view** — pending.

## 7. Edge cases / stress

All covered by tests:

- **N = 0** → report shared infra as pure overhead; no divide-by-zero. **N = 1** → equal share is the whole SharedTotal.
- **Zero total activity** → fall back to equal split *and flag it*.
- **Negative activity** → treated as zero.
- **Tenant with no LLM data** → `llm_usd = 0`, `llm_available = false`.
- **Tenant with no MRR** → margin *percentage* is 0 (absolute margin still reported, and negative).
- **Bedrock double-count** → excluded from shared pool (§1).
- **Negative shared pool** (credits skew) → clamped at 0 + logged.
- **avg LLM ≥ avg MRR** → `break_even_n = null`.
- **Window mismatch** — LLM and AWS use the same `days`; the provider's windowed call is preferred over the fixed 30-day one.

## 8. Baseline (2026-08-02)

Real figures, for sanity-checking the first render. AWS is consolidated in the payer account `755400488974`; the member accounts show almost nothing on their own.

| Month | Gross AWS (USD) |
|---|---|
| May 2026 | 1.741 |
| Jun 2026 | 2.303 |
| Jul 2026 | 1.866 |

Top of July: EKS 627, EC2 compute 508, EC2-Other 164, RDS 152, GuardDuty 138, CloudWatch 97, ElastiCache 59.

**Bedrock: 0.0085 USD in July** (1.84 in June, 0 in August) — LLM is a rounding error against infrastructure today, because production runs `AI_PROVIDER=openai` against the `bedrock-mantle` OpenAI-compatible endpoint with `openai.gpt-oss-120b`, and because the agent scheduler had been stalled since June.

⚠️ **All of the above is currently paid by AWS credits** — each month carries a `Credit` line that exactly offsets `Usage`, so the net bill reads zero. When credits run out this becomes ~1.900 USD/month of real spend, and every margin number in this document starts mattering.
