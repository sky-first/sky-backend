# Internal Console — Roles, Use Cases, Gap Analysis & Plan

**Audience:** SkyFirst engineering + leadership
**Purpose:** Identify every person who should open the Console and what they want to do there. Map that to features we have, features we lack, and a prioritised implementation plan so the tool becomes the company's single source of truth.

> The Console is not a DevOps dashboard. It is a **company cockpit** — every Sky-team member should land here daily and find the answer to their job.

---

## 1. Roles inventory

A SkyFirst startup at year 2 spans roughly nine roles. Some are filled today by one person wearing multiple hats (Lucas), some are future hires. The Console must accommodate all of them with proper RBAC from day one.

| # | Role | Filled today by | Mature org | Sensitivity |
|---|---|---|---|---|
| 1 | **CEO / Founder** | Lucas | Lucas | sees everything |
| 2 | **CTO / VP Engineering** | (Lucas wears) | future hire 2027 | sees everything |
| 3 | **Engineering Manager / Tech Lead** | Gustavo, Paulo | Gustavo | infra + revenue + costs |
| 4 | **Platform / DevOps / SRE** | Gustavo, Paulo | dedicated 2027 | infra + costs, no revenue |
| 5 | **Backend Engineer** | Gustavo, Paulo + hires | 4-6 engineers | infra read, no costs/revenue |
| 6 | **AI / ML Engineer** | (Paulo wears) | dedicated 2027 | LLM + per-tenant Bedrock costs |
| 7 | **Customer Success Manager (CSM)** | (Lucas wears) | dedicated 2027 | customer health + usage, no infra detail |
| 8 | **Sales / BD** | (Lucas wears) | dedicated 2027 | pipeline + customer revenue, no costs |
| 9 | **Finance / CFO** | (Lucas wears + Elive externally) | hire 2028 | revenue + costs + margins, no logs/infra |
| 10 | **Customer Support** | (Lucas wears) | hire 2026 | single-tenant view + ability to impersonate |
| 11 | **Compliance / Privacy / DPO** | (Lucas wears + advogado) | hire 2028 | audit log + DPA status + data residency |

---

## 2. Role profiles — jobs, questions, use cases

For each role: **who** they are, **what jobs** they're hired to do, **what questions** they bring to the Console, **what actions** they need to take, and **what data** the Console must surface.

---

### 2.1 CEO / Founder (Lucas today)

**Profile.** Open the Console once a day, ideally in the morning. Needs the 60-second pulse of the company — is the business healthy, are customers happy, are we burning the right amount.

**Top jobs-to-be-done:**
- Know if revenue is on track to plan
- Know if any customer is at risk
- Know if engineering is shipping or stuck
- Know if cash burn vs revenue is sustainable
- Approve / block escalations (suspend a tenant, refund, etc.)

**Daily questions:**
1. What's our MRR this week vs last? Is the trend up?
2. Which customers are happy / at risk / churning?
3. How much did we spend on AWS + Bedrock this month? Is the gross margin healthy?
4. Are any tenants in trouble (suspended, payment overdue, capacity > 80%)?
5. What did my team ship this week? Any incidents?
6. Are there any compliance flags I need to know about?

**Use cases (concrete actions):**
- See *single CEO Overview page* with: MRR, ARR run-rate, customer count + change, AWS+Bedrock spend MTD, gross margin %, list of customers at risk, alerts requiring decisions.
- *Approve* a tier change for a customer (workflow: CSM requests → CEO approves).
- *Send* a renewal email manually triggered from a tenant card.
- *Compare* tenants side-by-side: who's growing in usage, who's stalled.

**Data needed (write access to most of it):**
- All commercial metrics: MRR, ARR, churn, NRR, gross margin
- All cost metrics: AWS, Bedrock, infra fixed costs
- All customer health metrics: capacity utilisation, login frequency, NPS, support tickets
- All audit log (read)
- All settings (write)

**RBAC:** ★★★★★ — full read + write everywhere, including destructive actions.

---

### 2.2 CTO / VP Engineering (future)

**Profile.** Engineering leader. Cares about velocity, reliability, technical debt, AWS efficiency.

**Top jobs:**
- Keep the platform up
- Keep engineering velocity high
- Keep AWS+Bedrock spend predictable
- Decide architecture direction
- Manage engineering hiring + capacity

**Daily questions:**
1. What's our SLO compliance this week?
2. Are any clusters / pods unhealthy?
3. What's the deploy frequency + lead time vs goals?
4. Did Bedrock cost spike? Which tenant drove it?
5. What's the error budget burn rate?
6. Any incidents this week? Post-mortems written?

**Use cases:**
- See *Engineering Overview*: deploys this week, p95 latencies, error rates, SLO burn, on-call status.
- *Drill into* a specific deploy: which SHA, which tenant, success/rollback.
- *Configure* SLO targets per tenant tier.
- *Approve* config changes that affect cluster shape (autoscaler limits).
- *Trigger* manual rollback of last deploy on a tenant.

**Data needed:**
- Pod health across both clusters
- Deploy history + rollback capability
- SLO compliance + error budget
- Per-component Bedrock cost
- Incident timeline

**RBAC:** ★★★★☆ — read everything technical + revenue. No write on customer commercial data (that's CEO).

---

### 2.3 Engineering Manager / Tech Lead (Gustavo today)

**Profile.** Day-to-day technical leader. Bridges engineering and customer concerns.

**Top jobs:**
- Resolve production issues
- Coordinate cross-tenant deploys
- Coach the engineering team
- Make architecture trade-offs
- Communicate engineering health to the CEO

**Daily questions:**
1. What's broken right now and who's working on it?
2. Did the deploy succeed? Any rollback needed?
3. Are any tenants on an old version? Need upgrade?
4. Did my team's PRs land? CI green?
5. Which tenant is using the new feature first?
6. Any pages overnight? On-call rotation healthy?

**Use cases:**
- See *Engineering "today" page*: ongoing deploys, pages, error spikes, CI status, open PRs.
- *Trigger* a deploy or rollback for a tenant.
- *Pause* a tenant deploy stream if a regression suspected.
- *Filter* logs by component / severity / tenant in real time.
- *Compare* tenant configs (feature flags, env vars).

**Data:** all infra + audit + a "team activity" feed (deploys, commits, PRs merged).

**RBAC:** ★★★★☆ — same as CTO at this scale.

---

### 2.4 Platform / DevOps / SRE (Gustavo, Paulo today)

**Profile.** Infrastructure owner. Lives in the Console + terminal + Grafana.

**Top jobs:**
- Keep clusters up and healthy
- Keep deploys reliable
- Keep AWS spend in control
- Provision new tenants
- Run upgrades (alembic, k8s, base images)

**Daily questions:**
1. Are all pods running? Any crashloops?
2. What's the cluster utilisation? Are we close to autoscaling?
3. How's the deploy pipeline behaving? Any flaky tests?
4. What's the AWS spend trajectory? Any anomaly?
5. Any tenants stuck in a bad state?
6. What's queued in the alembic migration sequence?

**Use cases:**
- See *Infrastructure page* — already have skeleton.
- *Provision* a tenant: fill form, watch progress live, get a working tenant at the end.
- *Suspend / Resume / Destroy* a tenant.
- *Stream logs* live from any pod across any tenant.
- *Open shell* into a pod (with audit + read-only-by-default).
- *Trigger* a manual `kubectl rollout restart` per tenant component.
- *Compare* AWS Cost Allocation Tags per tenant.
- *Run* a quick psql query (read-only) on a tenant DB.
- *View* ArgoCD sync state directly inline (linked from Console).
- *Take a snapshot* of a tenant DB before a risky upgrade.

**Data:**
- Per-cluster, per-namespace, per-pod view
- Per-tenant DB connection + last backup
- Per-tenant deploy SHA + ArgoCD link
- Cost Allocation Tag breakdown
- Velero / backup state per tenant

**RBAC:** ★★★★☆ — read everything technical, write on infra (deploys, scaling, suspend). No write on customer commercial / pricing data.

---

### 2.5 Backend Engineer (future hires)

**Profile.** Builds features. Uses the Console occasionally for debugging.

**Top jobs:**
- Build features
- Debug bugs reported by support / CSM
- Validate own deploys hit the right tenants

**Daily questions:**
1. Did my deploy land in alpha-stg? What SHA?
2. Why is tenant X seeing this error?
3. What's the schema of `users` table on tenant Y?
4. Can I see the audit log for the action that broke?
5. Is my new feature flag turned on for the test tenant?

**Use cases:**
- *Search* logs by trace id / correlation id across all tenants.
- *View* feature flag state per tenant.
- *Open* tenant detail and read the activity / audit tabs to reproduce.
- *Trigger* a manual sync of a connection on a stg tenant.

**Data:** read-only access to logs (filterable), audit, feature flags, deploy SHAs. No cost, no revenue.

**RBAC:** ★★★☆☆ — read-only on infra + audit + logs. No tenant lifecycle writes. No commercial data.

---

### 2.6 AI / ML Engineer (future)

**Profile.** Owns LLM stack: model selection, Bedrock spend, RAG quality, response latency.

**Top jobs:**
- Keep AI response quality high
- Keep Bedrock spend predictable
- Tune per-tenant model selection
- A/B test prompts and model versions

**Daily questions:**
1. What's the average response time across tenants?
2. Which tenant is consuming the most Bedrock tokens? Why?
3. Are any responses being rejected by guardrails? Pattern?
4. How does Haiku vs Sonnet split look this week?
5. Are any tenants flagged for hallucination feedback?

**Use cases:**
- See *AI Operations* page: tokens consumed by tier / by tenant / by model
- *Switch* a tenant's Bedrock model (haiku ↔ sonnet) with audit
- *Pin* an inference profile per tenant for cost segregation
- *View* response latency p50/p95/p99 per tenant
- *Inspect* a specific query end-to-end (RAG context + SQL + answer)

**Data:**
- Per-tenant Bedrock cost + token counts
- Per-tenant model assignment
- Latency distributions per node (orchestrator/specialist/formatter)
- Guardrail rejection rate
- Sample queries for inspection

**RBAC:** ★★★★☆ — write access on per-tenant model config + inference profile. Read on all AI metrics. No write on tenant lifecycle, no commercial data.

---

### 2.7 Customer Success Manager (future, dedicated 2027)

**Profile.** Customer-facing. Owns the relationship after onboarding. Renewals + upsells + retention.

**Top jobs:**
- Keep every customer healthy (usage > activity threshold)
- Spot expansion opportunities (customer hitting limits = upsell)
- Spot churn risks (customer not using = at risk)
- Run QBRs with data
- Coordinate support escalations

**Daily questions:**
1. Who's near a capacity limit? (upsell opportunity)
2. Who hasn't logged in in 14 days? (churn risk)
3. Whose subscription renews in 60 days?
4. What support tickets are open by tenant?
5. What's the trend in agent runs / queries for tenant X?
6. Did the customer adopt the new feature we shipped?

**Use cases:**
- See *Customer Success Overview*: health-by-tenant matrix (green/yellow/red), renewals upcoming, open tickets.
- *Open* tenant CSM tab: notes, last meeting, last contact, NPS, custom flags.
- *Write* CSM notes (visible to CEO + CSM, not engineering).
- *Trigger* a renewal proposal email.
- *Tag* a tenant as "at risk" / "expansion candidate" / "reference".
- *Compare* tenant adoption: which features are used, which ignored.
- *Send* a survey from a tenant card.

**Data:**
- Customer health metrics: logins last 30d, queries last 30d, agents active, sources connected
- Subscription terms + renewal calendar
- NPS / CSAT scores (when we collect)
- Support ticket count + status
- Custom CSM notes
- Per-tenant adoption: feature usage matrix

**RBAC:** ★★★☆☆ — read all customer-facing data + write notes/tags. No infra detail. No costs. Revenue (their tenant) yes, totals no.

---

### 2.8 Sales / BD (future, dedicated 2027)

**Profile.** Manages the pipeline from prospect → trial → paid. Hands off to CSM after first invoice.

**Top jobs:**
- Convert prospects to paid customers
- Run trials and discovery calls
- Quote prices and contracts
- Hit quarterly revenue targets

**Daily questions:**
1. What's my pipeline coverage vs quota?
2. Which prospects are in trial? Day N of M?
3. Who in trial is showing strong product signals?
4. What did sales close this month? What's at risk?
5. Are any prospects upgrading tiers?

**Use cases:**
- See *Sales pipeline*: prospects, trials, paid, churned (Kanban-style or table).
- *Convert* a prospect to a trial tenant (creates the tenant with trial limits).
- *Convert* trial → paid (changes tier + starts billing).
- *Inspect* trial activity (lite version of Activity tab) to qualify.
- *Generate* a pricing proposal (PDF) from a tenant card.
- *Forecast* revenue for next quarter.

**Data:**
- Pipeline stage per prospect
- Trial activity (logins, queries, agents created)
- Subscription terms (current + proposed)
- Quarterly revenue numbers

**RBAC:** ★★★☆☆ — write on prospects + trial lifecycle. Read on revenue (own deals + team totals). No infra detail. No engineering pages.

---

### 2.9 Finance / CFO (future, hire 2028; outsourced via Elive today)

**Profile.** Owns financial accuracy. Cares about revenue recognition, AR, costs, margins, AWS billing reconciliation.

**Top jobs:**
- Close the books monthly
- Track AR / payments
- Forecast cash
- Justify spend
- Prep board reports

**Daily questions:**
1. What invoiced this month? What collected?
2. Who's overdue?
3. What's my AWS spend by tenant? Reconcile to revenue?
4. What's the gross margin trend?
5. What's the burn rate? Runway?

**Use cases:**
- See *Finance dashboard*: MRR, ARR, churn, NRR, gross margin, cash runway, AR aging.
- *Export* invoice list to CSV.
- *Mark* an invoice paid manually.
- *View* AWS cost allocation per tenant + period.
- *Generate* a board pack from a button.

**Data:**
- Full revenue ledger (Moloni sync)
- Full cost ledger (AWS Cost Explorer + Bedrock + infra fixed)
- AR aging
- Cash position (banking sync)
- Subscription terms per tenant

**RBAC:** ★★★★☆ — read everything financial + write on invoice status / payment reconciliation. No infra writes. No customer engineering view.

---

### 2.10 Customer Support (future, hire 2026)

**Profile.** Handles tickets. Often needs to *be* a customer to reproduce. Reports up to CSM.

**Top jobs:**
- Resolve tickets fast
- Reproduce bugs
- Escalate to engineering when blocked

**Daily questions:**
1. What tickets are open? Mine?
2. How do I reproduce this customer's issue?
3. Can I see the audit trail of what they did?
4. Did engineering acknowledge my escalation?

**Use cases:**
- See *Support inbox* (per-tenant tickets).
- *Open* tenant in "support mode" — read-only access scoped to one tenant.
- *Impersonate* a customer user (heavily audited; requires their consent flag).
- *Attach* an audit log entry to a ticket.
- *Escalate* a ticket to engineering (creates a Jira / Linear issue with attached audit + logs).

**Data:**
- Ticket queue per tenant
- Per-tenant audit + logs (read)
- Impersonation tokens (gated)

**RBAC:** ★★☆☆☆ — read on a *single* tenant at a time (the one the ticket is for). No cross-tenant visibility. No commercial. No infra config.

---

### 2.11 Compliance / Privacy / DPO (future, hire 2028; lawyer ad-hoc today)

**Profile.** Owns GDPR + DPA + data residency + audit retention. Often called only when a customer asks.

**Top jobs:**
- Respond to data subject requests (DSARs)
- Verify data residency claims hold
- Audit access patterns
- Approve new sub-processors
- Run annual SOC2 review

**Daily questions (mostly periodic, not daily):**
1. Where does tenant X's data live? Which region?
2. Who accessed tenant X's data in the last 30 days?
3. Are DPAs signed for all customers? Expiring?
4. Have any Sky-team members exported customer data?

**Use cases:**
- See *Compliance dashboard*: DPA status per customer (signed/pending/expired), data residency per tenant, access stats.
- *Export* an audit trail for a customer on demand (DSAR).
- *Approve* a new sub-processor (records in audit).
- *Generate* SOC2 evidence pack.

**Data:**
- Full audit log (read, can't modify)
- DPA / contract status per tenant
- Data residency per tenant
- Access stats per Sky-team member

**RBAC:** ★★★☆☆ — read everything legal/audit. Cannot modify customer data. Can mark DPAs as signed.

---

## 3. Permissions matrix

The role → resource → action grid the Console must enforce.

Legend: ● write · ○ read · — no access

| Resource ↓ \ Role → | CEO | CTO/Tech Lead | DevOps | Backend Eng | AI Eng | CSM | Sales | Finance | Support | DPO |
|---|---|---|---|---|---|---|---|---|---|---|
| Tenant lifecycle (create/suspend/destroy) | ● | ● | ● | — | — | — | ● (trial only) | — | — | — |
| Tenant settings (tier, limits, flags) | ● | ● | ● | — | ● (AI only) | — | — | — | — | — |
| Tenant config view | ● | ○ | ○ | ○ | ○ | ○ | ○ (own) | ○ | ○ (one) | ○ |
| Customer notes (CSM) | ● | ○ | — | — | — | ● | ○ | — | ○ | — |
| Bedrock model config per tenant | ● | ○ | — | — | ● | — | — | — | — | — |
| Pods + deploys (read) | ○ | ○ | ○ | ○ | ○ | — | — | — | — | — |
| Pods + deploys (write — rollback, restart) | ● | ● | ● | — | — | — | — | — | — | — |
| Live logs streaming | ○ | ○ | ○ | ○ | ○ | — | — | — | ○ (one tenant) | — |
| psql query box (read-only) | ● | ● | ● | ○ | — | — | — | — | — | ○ |
| kubectl exec / shell | ● | ● | ● | — | — | — | — | — | — | — |
| AWS cost (platform total) | ○ | ○ | ○ | — | ○ | — | — | ○ | — | — |
| AWS cost (per tenant) | ○ | ○ | ○ | — | ○ | ○ | ○ (own) | ○ | — | — |
| Bedrock cost (per tenant) | ○ | ○ | — | — | ○ | ○ | — | ○ | — | — |
| Revenue (MRR/ARR/totals) | ○ | ○ | — | — | — | ○ | ○ | ○ | — | — |
| Gross margin | ○ | ○ | — | — | — | — | — | ○ | — | — |
| Invoices + payments | ● | ○ | — | — | — | ○ | ○ | ● | — | — |
| Audit log (read) | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Audit log (export for DSAR) | ● | ● | — | — | — | — | — | — | — | ● |
| DPA / compliance flags | ● | ○ | — | — | — | ○ | ○ | — | — | ● |
| Impersonation | ● | — | — | — | — | — | — | — | ● (gated) | — |
| Settings (role grants) | ● | ● | — | — | — | — | — | — | — | — |
| Incident / alert ack | ● | ● | ● | — | ● | ● | — | — | — | — |

Concrete read of the matrix: **only CEO + CTO see literally everything**. Every other role is bounded.

---

## 4. Cross-role workflows

Some flows span multiple roles. The Console should make these handoffs visible.

### 4.1 Tenant provisioning (Sales → DevOps → CSM)
1. Sales converts a prospect → creates a trial tenant (Pilot tier).
2. DevOps gets a notification: *"new tenant `acme` queued, run bootstrap"*.
3. DevOps clicks one button → bootstrap runs → tenant is ready → email sent to customer admin.
4. CSM is auto-assigned, sees the new tenant in their queue.

### 4.2 Suspension for non-payment (Finance → CSM → CEO)
1. Finance flags invoice as overdue >30 days.
2. CSM sees the flag, attempts customer outreach.
3. After 14 more days, CEO sees the escalation, decides to suspend.
4. Suspend action records: invoice id, attempts, decision actor.
5. On payment, Finance marks paid → auto-resume.

### 4.3 Bedrock cost spike (AI Eng → CTO → CEO)
1. AI Eng dashboard flags: tenant X consuming 5x baseline.
2. AI Eng inspects: identifies bad prompt loop.
3. AI Eng applies rate limit temporarily.
4. CTO is notified of the action via audit.
5. CSM sees the customer-side note: "throttled, root-cause: X".

### 4.4 Incident response (DevOps → CSM → CEO)
1. DevOps sees a pod crashloop alert.
2. Triggers incident response runbook from the alert card.
3. CSM gets affected-tenants list automatically.
4. Once resolved, post-mortem is attached to the incident entry.
5. CEO sees a weekly digest of incidents.

The Console v2 should make at least **flows 4.1 and 4.4** explicit. Flows 4.2 and 4.3 can wait for v3.

---

## 5. Gap analysis — Console today vs the role mapping

A walk through what each role would actually find vs what they need.

### What Console v1.5 already does well
- ✅ Tenant CRUD (create / suspend / resume / destroy) — DevOps ✓ + CEO ✓ for the action
- ✅ Audit log + filters — DPO ✓ partially, Engineering ✓
- ✅ Provisioning jobs list — DevOps ✓
- ✅ Tenant detail with 9 tabs (Overview, Activity, Health, Logs, Cost, Billing, Capacity, Audit, Jobs)
- ✅ Cross-cluster Infra view — DevOps ✓
- ✅ Cross-tenant Cost & Revenue page — Finance partial ✓, CEO partial ✓
- ✅ Live logs stream + log explorer — DevOps ✓, Eng ✓
- ✅ Incidents + alerts page
- ✅ Command palette
- ✅ Collapsible sidebar

### What's missing — by importance

**P0 (CEO + day-1 hygiene)**

| Missing | Why it matters | Effort |
|---|---|---|
| **Tier limits editable from Console** | Today you set them via the form on create — but CEO/CSM should be able to change `capacity_limits.agents` etc. inline without an engineer | M |
| **Tier presets table** (pilot/foundation/.../strategic) sourced from the pricing doc, applied when tier changes | When CSM upgrades tenant from Pilot→Foundation, agents/sources/indexed_gb auto-bump to tier defaults | M |
| **RBAC enforcement (real roles, not just admin/operator/read_only)** | All 9 roles defined above need to actually be enforced; today everyone is admin via dev-bypass | L |
| **CEO Overview page** — explicit / different from /console | A 1-screen company pulse: MRR, ARR run-rate, customer count, gross margin, spend, alerts, this week's deploys | M |
| **Activate dashboard auto-refresh + last-loaded marker** | CEO opens once an hour, must trust freshness | S |

**P1 (CSM + Sales + retention)**

| Missing | Why | Effort |
|---|---|---|
| **CSM tab on tenant detail** — notes, last contact, NPS, custom tags | CSM today has no place to record judgements | M |
| **Per-tenant feature-flag editor** | Toggle features on/off from Console without code change | M |
| **Renewal calendar** — global view of subscriptions ending next 90 days | Sales + CEO need to see renewals coming up | S |
| **Customer health score** per tenant | Composite of: login frequency, queries last 30d, agents running, capacity utilisation, days since last contact | M |
| **Trial → Paid conversion flow** | Sales needs a button "convert to paid", which: changes tier, starts billing, notifies CSM | M |
| **Activity adoption matrix** — which features each tenant uses | CSM uses to identify expansion opps | L |

**P2 (Finance + compliance)**

| Missing | Why | Effort |
|---|---|---|
| **Real Moloni / invoice sync** | Finance currently has mock billing data | L |
| **AR aging view** — invoiced not paid, overdue buckets | Cash management | M |
| **DPA / contract status per tenant** | Compliance needs this for SOC2 + GDPR | M |
| **Data residency per tenant** | Compliance evidence | S |
| **Cost reconciliation** — invoiced minus AWS allocated | Margin per tenant | M |
| **Quarterly board pack export** | One-click export of CEO Overview as PDF | M |

**P3 (Engineering depth)**

| Missing | Why | Effort |
|---|---|---|
| **Real kubernetes integration** — replace mock InfraProvider | DevOps needs real pods data | L |
| **Real AWS Cost Explorer integration** — replace mock CostProvider | Finance + DevOps both need real | L |
| **kubectl exec (gated)** | DevOps needs shell into pods sometimes | M |
| **Read-only psql box per tenant** | Backend Eng + DevOps need to inspect data without leaving Console | M |
| **Deploy timeline + rollback button** | Tech Lead needs in-Console deploy ops | M |
| **Embedded Grafana panels** — iframe with auto-login | Don't reinvent Grafana | S |
| **Embedded ArgoCD app cards** — sync state + history | Don't reinvent ArgoCD | S |
| **Feature flag definitions** — central registry not just per-tenant | Engineering owns the flag taxonomy | M |

**P4 (Support + impersonation)**

| Missing | Why | Effort |
|---|---|---|
| **Support ticket integration** — link from Console to tickets | Customer Support inbox | M |
| **Customer impersonation (gated)** | Support reproduces customer issues | L (heavy audit) |
| **Per-tenant single-page view for Support** | Support is bounded to one tenant at a time | S |

**P5 (Polish / completeness)**

| Missing | Why | Effort |
|---|---|---|
| **Notifications system** — bell with unread alerts targeted at user's role | Alerts come to the right person | M |
| **Cmd+K extended actions** — "Suspend X", "Renew X" inline | Power-user speed | S |
| **Tenant comparison tool** — pick 2-3 tenants, side-by-side | CSM + Sales benchmark | M |
| **Activity audit export** (CSV) for DSARs | DPO compliance | S |
| **In-Console runbook execution** — e.g. "rotate Bedrock key for tenant" | Reduce tribal knowledge | L |

---

## 6. Prioritised implementation plan

Given everything above, the next implementation iterations should be **shaped by role coverage**, not by feature isolation. Each iteration *adds a complete role-experience* rather than one feature here and one there.

### Iteration 3 — CEO + CSM essentials (highest leverage today)
Lucas opens the Console daily; CSM hires need a usable tool. This iteration covers both.

* **CEO Overview** standalone page (`/console`) becomes the dashboard for that role specifically; current `/console` becomes `/console/operations`
* **Tier presets** loaded from a config (`backend/src/services/pricing_tiers.py`) reflecting the pricing doc
* **Inline tier change** on tenant detail Settings tab → applies tier preset to capacity_limits, records audit
* **Capacity limits editor** in Settings tab (override per tenant, audit recorded)
* **CSM tab** on tenant detail — free-form notes (markdown), tags (at_risk / expansion / reference), last contact date, NPS field
* **Health score** per tenant — composite of capacity %, days since last login (mocked until real), open tickets count
* **Renewal calendar** under `/console/cost` → "Renewals next 90 days" table

Effort: ~1.5 days of focused work.

### Iteration 4 — Real RBAC + Sales conversion flow
* Replace dev-bypass with role grants stored in DB
* `console_role_grants` table: (user_email, role, granted_at, granted_by)
* `RoleRequirement` decorator on every route; permissions matrix encoded
* UI shows / hides sections per role
* Sales flow: "Convert to paid" button on a trial tenant card

Effort: ~2 days.

### Iteration 5 — Real integrations (k8s + AWS + Moloni)
Replace the three mock providers with real ones, behind feature flags so we can A/B locally.

* `RealInfraProvider` using `kubernetes-client` against both clusters via SSM tunnel
* `RealCostProvider` using AWS Cost Explorer API + Bedrock Application Inference Profile tags
* `RealBillingProvider` using Moloni API (auth via API key in Secrets Manager)
* WS log streaming wires to `kubectl logs --follow`
* Grafana panel embed (iframe with service-account auth)

Effort: ~3-4 days, mostly AWS plumbing.

### Iteration 6 — Compliance + DPO
* DPA status per tenant (signed/pending/expired)
* Data residency per tenant
* DSAR export button (audit log scoped to a tenant + their users)
* Compliance dashboard for DPO role

Effort: ~1.5 days.

### Iteration 7 — Support tooling
* Ticket integration (whichever ticket tool we pick — probably Plain.com or Zendesk lite)
* Support-mode tenant view (single-tenant scope)
* Customer impersonation, gated by customer consent flag + heavy audit
* Escalation to engineering — creates a Linear / Jira issue with attached logs

Effort: ~3 days.

### Iteration 8 — Polish
* Notifications system (bell + targeted by role)
* Tenant comparison tool
* Board pack PDF export
* Quick-action `Cmd+K` extensions

Effort: ~2 days.

---

## 7. What I'd build next if I had to pick one thing

If today is one slot of work, do **Iteration 3** (CEO + CSM essentials, ~1.5 days).

Reason: it makes the tool *usable as the CEO cockpit* immediately. Every other iteration is enabler / cleanup. Iteration 3 alone gets Lucas opening the Console daily and finding answers.

After that, **Iteration 4 (real RBAC)** because we cannot bring on a CSM hire or Sales hire without the tool already restricting them. Today everyone is admin — that's a hiring blocker, not a polish item.

The integrations (Iteration 5) are heavier but defer well — the mocks let everyone start using the Console productively while we wire the real data sources.

---

## 8. Concrete next-session checklist

**Owner:** Claude executing under Lucas's autonomous-mode authorization.

**Deliverables:**
- [ ] `src/services/pricing_tiers.py` — tier preset registry
- [ ] `/api/console/v1/tiers` — list available tiers + their defaults
- [ ] `POST /api/console/v1/tenants/{slug}/tier` — set tier + apply preset (audited)
- [ ] `PATCH /api/console/v1/tenants/{slug}/capacity_limits` — manual override (audited)
- [ ] Settings tab on tenant detail with the two above forms
- [ ] CSM tab on tenant detail (notes / tags / last-contact)
- [ ] `console_tenant_csm_notes` table + endpoints
- [ ] `/console` redesigned as CEO Overview; old dashboard moves to `/console/operations`
- [ ] Health score component (computed in backend service)
- [ ] Renewals next-90-days section on `/console/cost`
- [ ] Tests + e2e smoke
- [ ] Commit per repo, local-only as per Projeto A/B convention

When Lucas reviews this doc, the decision is: do we start Iteration 3 next, or do we sequence differently based on his read?
