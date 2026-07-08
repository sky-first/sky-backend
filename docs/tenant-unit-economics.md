# Tenant Unit Economics — design

**Status:** proposal (2026-07) · **Owner:** Console / Cost
**Goal:** per-tenant *fully-loaded* cost + margin, and a platform view that shows margin improving with scale — the quantified "value of the architecture" story.

---

## 1. The model

For each active tenant, over a window (default 30d, normalised to a month):

```
Cost(tenant) = Dedicated(tenant) + SharedAlloc(tenant) + LLM(tenant)
Margin(tenant) = MRR_usd(tenant) − Cost(tenant)
```

- **Dedicated(tenant)** — AWS resources that belong to *one* tenant: its dedicated RDS DB, Redis, and Secrets Manager entries. Sourced from Cost Explorer filtered by the `tenant=<slug>` cost-allocation tag (§3).
- **SharedAlloc(tenant)** — the tenant's slice of the shared platform (one BE, one AI service, EKS control plane, NAT, monitoring). Computed **two ways** (decision: show both):
  - **Equal** — `SharedTotal / N_active` → the "architecture cost": drops as N grows.
  - **Weighted** — `SharedTotal × activityShare(tenant)`, where `activityShare = tenantActivity / Σ tenantActivity` (queries + agent-runs). The "real consumption cost".
- **LLM(tenant)** — token cost from Langfuse via `get_tenant_llm_metrics(slug)`. **Authoritative** for LLM spend.

### Avoiding double-counting (Bedrock)
LLM cost comes from Langfuse. If Bedrock also appears in the AWS CE `bedrock_usd` bucket, counting both double-charges. **Rule:** the shared pool **excludes** the Bedrock bucket; LLM is taken solely from Langfuse.

```
SharedTotal = platform_cost.total_usd − platform_cost.bedrock_usd − Σ Dedicated(tenant)
```

## 2. The scale insight (why SaaS gets cheaper per tenant)

- **Marginal cost of tenant N+1** ≈ `Dedicated + LLM` (small; no new shared infra).
- It adds a **full MRR** → very high incremental contribution margin.
- **Blended margin** `= (Σ MRR_usd − Σ Cost) / Σ MRR_usd` rises as `SharedTotal / N` shrinks.

The Console shows a **"margin vs N tenants"** curve: hold current SharedTotal + avg dedicated/LLM/MRR, sweep N → the curve that proves the architecture pays off with scale. Also surface **break-even N** (where blended margin crosses 0) and **marginal margin per new tenant**.

## 3. Cost-allocation tag plan (AWS) — the part needing account access

**Problem today:** onboarding stamps `sky-tenant=<slug>` (`onboard-client.yml`), the provider filters `tenant` (`aws_cost_provider.TENANT_TAG_KEY`), and the per-tenant RDS/Redis/secret are not tagged at all → `tenant_cost(slug)` returns ~0.

**Decision:** standardise on tag key **`tenant`** (matches the provider; cleaner than `sky-tenant`).

**Steps (per env; needs access to 741375879811 stg / 032080729567 prd):**
1. **Onboarding** — add `tenant=<slug>` alongside the existing `sky-tenant` tag when creating tenant resources (keep `sky-tenant` for backward compat during transition).
2. **Tag existing resources** — RDS instance/DB, ElastiCache, and `sky/<env>/tenant-<slug>/db` secret for every live tenant:
   ```
   aws rds add-tags-to-resource --resource-name <rds-arn> --tags Key=tenant,Value=<slug>
   aws elasticache add-tags-to-resource --resource-name <redis-arn> --tags Key=tenant,Value=<slug>
   aws secretsmanager tag-resource --secret-id sky/<env>/tenant-<slug>/db --tags Key=tenant,Value=<slug>
   ```
3. **Activate** `tenant` as a cost-allocation tag: Billing → Cost allocation tags → User-defined → activate `tenant`. **~24h** to propagate before CE can group by it.
4. Verify: `aws ce get-cost-and-usage --group-by Type=TAG,Key=tenant ... --region us-east-1`.

Until step 3 lands, `Dedicated` reads 0 and the UI labels the tenant "tag onboarding pending" (not an error).

## 4. API

New endpoint (Console, sky-team only):

```
GET /console/dashboard/unit-economics?days=30
→ {
    n_active: int,
    shared_total_usd: float,
    blended_margin_equal_pct: float,
    blended_margin_weighted_pct: float,
    break_even_n: int | null,
    marginal_cost_next_usd: float,
    tenants: [{
      slug, display_name, tier,
      mrr_usd,
      dedicated_usd, llm_usd,
      shared_equal_usd, shared_weighted_usd,
      cost_equal_usd, cost_weighted_usd,
      margin_equal_usd, margin_weighted_usd,
      dedicated_tag_pending: bool
    }]
  }
```

Composes existing providers: `cost_provider().platform_cost()` / `tenant_cost(slug)`, `llm_cost_metrics_provider().get_tenant_llm_metrics()`, `billing_provider().tenant_billing()`, `activity_provider()` for weights.

## 5. Frontend

New Console section **"Unit economics"**: per-tenant table (margin equal/weighted, cost breakdown), a toggle equal↔weighted, and the **margin-vs-N** curve with break-even and marginal-margin callouts.

## 6. Rollout (phased, low-risk)

1. **Backend service + endpoint** — works immediately; `Dedicated` = 0 until tags live (graceful).
2. **AWS tag runbook (§3)** — needs Lucas / prod access; 24h propagation.
3. **Frontend view**.

## 7. Edge cases / stress

- **N = 0/1** → guard divide-by-zero; equal share = SharedTotal for N=1.
- **Zero total activity** (weighted) → fall back to equal split.
- **Tenant with no Langfuse data** → `llm_usd = 0`.
- **Untagged tenant** → `dedicated_usd = 0`, `dedicated_tag_pending = true`.
- **Bedrock double-count** → excluded from shared pool (§1).
- **Negative shared** (dedicated > platform total, e.g. credits skew) → clamp at 0 + log.
- **Window mismatch** — LLM (Langfuse) and AWS (CE) must use the same `days`.
