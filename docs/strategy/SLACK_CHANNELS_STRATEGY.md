# Slack channels strategy — public demo + post-launch

This doc captures the channel architecture proposed for the SKY public demo
launch. Driven by Lucas's overnight notes (2026-04-28) about how Slack
notifications should be structured as the lead funnel matures.

## Why a strategy doc

Today we have **one** Slack Incoming Webhook configured (tickets) and a
**second** about to ship (demo signups, see PR #335). Without a deliberate
channel layout we'll either:

- dump everything into one noisy channel that nobody reads, OR
- create channels ad-hoc per event type and end up with 12 dead ones

The strategy below is the smallest channel set that covers the launch +
1-2 quarters of growth, and the explicit rule for adding more.

## Audience map

| Audience | Cares about | Volume | Latency |
|---|---|---|---|
| Lucas (founder) | Everything | Low at launch, growing | Real-time on signups, async on tickets |
| Support / on-call | Bugs + escalations | Spiky | Real-time, paging via webhook |
| Marketing / sales | Lead-gen pipeline | Steady once launched | Real-time on signups |
| Product / eng | Feedback content + repro steps | Steady | Async (review next-day) |
| Compliance / security | Audit-relevant events (admin actions, exports, breaches) | Rare | Async |

Not all audiences need a separate channel — some can share + filter.

## Proposed channel set (launch state)

| Channel | Purpose | Webhook | Membership |
|---|---|---|---|
| **#sky-demo-signups** | Lead-gen funnel: every demo provisioning event (cold, returning, same-domain join) | `SLACK_DEMO_SIGNUPS_WEBHOOK_URL` (PR #335) | Lucas + Marketing |
| **#sky-tickets** | Customer + demo guest tickets created via the in-app feedback widget | `SLACK_TICKETS_WEBHOOK_URL` (PR #328) | Lucas + Support + Eng on-call |
| **#sky-tickets-escalated** | Subset of tickets that hit "Escalate to Sky" — paging-grade | `TICKET_ESCALATION_WEBHOOK_URL` (already exists) | Eng on-call only |
| **#sky-launch-announce** | Public marketing announcements (handled by humans, no webhooks today) | — | All |
| (later) **#sky-billing-events** | Subscription / dunning events from Stripe | future webhook | Lucas + Finance |

The first three are the must-haves before public launch. The last two are
post-launch.

## Why three demo-related channels (not one)

Different retention + reaction times:

- **#sky-demo-signups** — high-volume eventually; nobody reads each event
  individually after week 1, but the rate becomes a vanity metric / health
  signal. Threading off it for VIP signups (e.g. company size > X, role =
  CTO/VP) becomes useful later — that's when we add a `#sky-demo-leads-qualified`
  child.
- **#sky-tickets** — every ticket is something to look at. Searchable by
  reporter email, severity, category. Triage happens in-thread.
- **#sky-tickets-escalated** — paging-grade, on-call rotation lives here.
  Quiet by design.

If we tried to fit all three into one channel:

- Marketing would mute it the day after launch (too noisy from signups)
- On-call would lose the paging signal under signup spam
- Triage threads on a feedback ticket would interleave with unrelated
  signup pings

## Channel naming convention

`#sky-<area>-<event-class>`

- `<area>`: `demo` / `tickets` / `billing` / `audit`
- `<event-class>`: `signups` / `escalated` / `qualified` / nothing for
  generic streams

Avoid product-feature names in channel names — they go stale fast (e.g.
`#sky-pulse-alerts` would have to be renamed when Pulse gets folded into
the unified intelligence surface).

## Adding a new channel

Trigger: when one of the existing channels exceeds **100 messages/day** for
a sustained week, OR when an audience has a clear sub-need that justifies
its own retention/notification policy.

Process:
1. Create the channel in Slack (manual)
2. Generate a new Incoming Webhook for it (api.slack.com/apps/A0B03HEQECB)
3. Add the URL as a new secret in Azure KV (`akv-sky-staging-...`)
4. Reference it in `gitops/.../backend.yaml` ExternalSecret + values yaml
5. Add a corresponding env var in `src/config/settings.py`
6. Add the helper + invocation in the BE service that emits the event
7. PR the whole thing

Don't generate the webhook URL inline in chat or commit it to the repo —
the URL itself is the secret (the path embeds the auth token).

## Open questions for follow-up

- **Bidirectional flow** (commenting on tickets from Slack itself, not just
  receiving notifications) — this needs a Slack App with `chat:write` +
  Slash command + an event-receiver endpoint. Out of scope for now; the
  current setup is one-way (webhook → channel).
- **Ticket → Slack thread linking**: each ticket Slack message could carry
  a thread_ts and subsequent ticket comments could thread into it. Needs
  storing the thread_ts on the Ticket row. Defer until volume justifies it.
- **Public channels for community**: separate question. The ones above are
  internal-only. Customer-facing community Slack would be its own workspace
  (different brand, different ToS), not a channel here.

## What I am NOT proposing

- Per-customer channels (doesn't scale, GDPR concern, channel-creation
  permission becomes a feature request)
- Slack DMs for tickets (kills audit trail; non-Slack users get cut out)
- Email-to-Slack bridges (latency + formatting issues; if email matters,
  it should hit a dedicated channel via webhook from a real provider)
