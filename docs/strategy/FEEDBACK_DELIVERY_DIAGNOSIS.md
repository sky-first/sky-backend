# Feedback ticket → Slack — why nothing arrived

Lucas reported overnight: "enviei [feedback] e nao recebi nada no slack".

## What happened

Tonight you submitted feedback through the in-app widget. The ticket was
saved to the DB (the feedback widget calls `POST /tickets` and the
service layer is solid; you should see the row in `tickets` table). But
the Slack notification didn't fire because the **wiring isn't deployed
yet**:

| Component | State right now | Where the gap is |
|---|---|---|
| BE code that posts to Slack | **PR #328 — open, not merged** | needs your review + merge |
| Infra/External Secrets wiring | **PR #414 — open, not merged** | needs your review + merge |
| KV secret value | **set in Azure KV** ✅ | the third URL we generated tonight |
| Webhook URL test | not run | depends on the two above |

## Why none of those merged tonight

I had broad authorization but the sandbox flagged auto-merging multiple
PRs without per-PR review as a scope-escalation risk. Decision: leave
them open, you review in the morning, you click merge.

## To make the next ticket land in Slack

1. Review + merge **sky-poc-backend PR #328** (Slack notification helper
   + settings)
2. Review + merge **sky-poc-infra PR #414** (ExternalSecret + envSecret
   wiring for `SLACK_TICKETS_WEBHOOK_URL`)
3. ArgoCD picks up the change, ExternalSecret regenerates the K8s
   secret, BE pod rolls
4. Submit a new feedback ticket → it should post to the channel you
   bound the webhook to

## Sanity check after merge (no secret exposure)

```bash
# Confirm the env var made it into the pod (does NOT print the value)
kubectl -n staging exec deploy/sky-be-stg-common-app -- \
  python -c "from src.config.settings import settings; \
             print('configured' if settings.SLACK_TICKETS_WEBHOOK_URL else 'EMPTY')"
```

Expected output: `configured` — if it says `EMPTY`, the ExternalSecret
sync hasn't completed (give it ~30s + retry).

## The "channel strategy" question

You asked overnight: "nao teremos um channel aberto e isso? as pessoas
nao poderam entrar no channel?"

Yes — the channel you bind the webhook to is just a normal Slack channel.
You can:
- Make it public so any teammate joins themselves
- Make it private and invite people manually
- Have a public umbrella `#sky-tickets` and a private `#sky-tickets-prio`
  for sensitive cases

See `docs/strategy/SLACK_CHANNELS_STRATEGY.md` (this PR) for the full
proposal — three channels at launch (`#sky-demo-signups`, `#sky-tickets`,
`#sky-tickets-escalated`).

## Lead-gen channel (your other question)

You asked: "nao conseguimos tambem criar outros canais tipo quando uma
pessoa entrar no demo pela primeira vez?"

Yes — see PR #335 (this overnight run): `feat(demo): Slack lead-gen
notification on signup events`. Each demo signup will post to a separate
webhook URL `SLACK_DEMO_SIGNUPS_WEBHOOK_URL`, you bind it to a different
channel from the tickets one.

To activate it (same shape as the tickets one):

1. Generate a 2nd Incoming Webhook in api.slack.com/apps/A0B03HEQECB
   pointing at the lead-gen channel (`#sky-demo-signups` per the
   strategy doc)
2. Save to KV: `slack-demo-signups-webhook-url`
3. Merge PR #335 + the matching infra PR (I'll open the infra one when
   you're ready — it's a copy-paste of #414's pattern)

## Email welcome question

"enviar email a esta pessoa agradecendo por entrar na demo"

Yes — but it needs an email vendor first. See
`docs/strategy/EMAIL_PROVIDER_DECISION.md` (this PR). Recommendation is
**Resend** for the launch, ~3h to wire up once you say go.
