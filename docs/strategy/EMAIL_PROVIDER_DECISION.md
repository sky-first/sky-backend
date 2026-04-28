# Email provider — decision required

Lucas asked overnight: send a welcome email to every demo signup ("thanks
for entering the demo, here's how to get the most out of it"). The BE
already has `src/services/email_service.py` with a stub `send_invite_email`
method that uses SMTP — but we're not actually sending email today.

This doc compares the realistic options for production-grade email so we
can pick a vendor + plug it in.

## What we need

- **Transactional email** (welcome, ticket replies, password reset) —
  high deliverability, < 1s latency, retries, bounce/complaint webhooks.
- **Templating** — at minimum a way to pass variables into HTML+text
  templates. Bonus: WYSIWYG editor for non-eng to tweak.
- **Sender domain auth** — DKIM/SPF/DMARC on `skyfirstlabs.com` so we
  don't end up in spam.
- **Sandbox / dev mode** — emails go nowhere when running locally.
- **NOT** broadcast / newsletter (that's a separate concern, use
  Mailchimp/Loops/etc when we get there).

## Options shortlist

| Vendor | $ for low volume | DX | Setup time | Notes |
|---|---|---|---|---|
| **Resend** | Free tier 3k/mo, $20/mo for 50k | Excellent (great docs, React Email templates) | ~30 min | Modern, founder-friendly. **Recommended for us.** |
| **SendGrid** (Twilio) | Free tier 100/day, $20/mo for 50k | OK (legacy API, decent SDK) | ~1h | Battle-tested. Heavier than we need. |
| **AWS SES** | $0.10 per 1k after first 62k free | Worst (manual templating, raw API) | ~3h | Cheapest at scale. Worst DX. Skip until we hit $100/mo on Resend. |
| **Postmark** | Free 100/mo, $15/mo for 10k | Good | ~45 min | Excellent for transactional (separate streams for txn vs broadcast). |
| **Mailgun** | $35/mo flagship plan | Good | ~45 min | Solid, but starting price higher than alternatives. |

## Recommendation

**Resend** for staging + first 6 months of prod.

Why:
- Free tier covers our launch volume comfortably
- React Email integration matches our FE stack (same JSX templates can
  serve in-app + email)
- Founder/team is responsive on Twitter; if we hit a deliverability
  issue we can ping them
- Migration path to AWS SES later is clean if we outgrow Resend's
  pricing — both expose plain SMTP + REST APIs, so the
  `EmailService` abstraction we already have absorbs the swap

Why not SendGrid: heavier API, more historical baggage, worse DX. Fine
choice if we already had Twilio for SMS, but we don't.

Why not SES yet: too much setup overhead for the volume we're at. Worth
revisiting when monthly Resend bill hits ~$50.

## Wire-up plan (~3h, one PR)

### Step 1 — Resend account

1. Sign up at https://resend.com (free tier)
2. Add `skyfirstlabs.com` as a verified domain
3. Add the DNS records they generate (SPF, DKIM, DMARC) to Cloudflare
4. Generate an API key, store in Azure KV as `resend-api-key`

### Step 2 — BE wiring (~1h)

- New env var `RESEND_API_KEY` in `src/config/settings.py`
- Add `pip install resend` to requirements
- Refactor `src/services/email_service.py` to call Resend API:
  ```python
  import resend
  resend.api_key = settings.RESEND_API_KEY
  resend.Emails.send({
      "from": "Sky <noreply@skyfirstlabs.com>",
      "to": [recipient],
      "subject": ...,
      "html": ...,
      "text": ...,
  })
  ```
- Empty API key = dry-run mode (log what would be sent, don't send) —
  same pattern we use for `TURNSTILE_SECRET_KEY` in `_verify_turnstile`

### Step 3 — Welcome email on demo signup (~1h)

- New template `src/templates/emails/demo_welcome.html` (+ plain-text
  variant) — keep simple: greeting, reminder of TTL, link to demo
  dashboard, CTA to schedule a call with Lucas
- Hook into `demo_service.signup` after the DB commit. Best-effort
  send, swallow failures (mirror the Slack webhook pattern at PR #335)
- Don't send on `_issue_returning` (returning visitor doesn't need
  another welcome)
- Don't send on `_join_sibling_demo_space` either (their teammate just
  invited them — different copy needed; defer to a `#email-team-up`
  template in a follow-up)

### Step 4 — Testing

- Local: empty `RESEND_API_KEY` → service logs "would send to X" but
  doesn't hit network
- Staging: real key, but Resend default sandbox-ish mode is OK
- Prod: monitor the bounce/complaint webhooks Resend sends back

## Out of scope for this PR

- **Email digest of weekly demo signups** — easy to add later as a
  cron task using the same EmailService
- **Re-engagement sequences** (drip campaigns) — that's marketing
  automation territory; pick a tool (Loops, Customer.io) when needed
- **Inbound email parsing** (replies to tickets via email) — Postmark
  is best at this; revisit when ticket volume justifies

## Decision needed from Lucas

- ✅ / ❌ on Resend as the vendor
- Email address that emails should send FROM (`noreply@skyfirstlabs.com`?
  `lucas@`? `welcome@`?)
- Welcome-email body — do you want to draft the copy or should I draft
  and you edit?

Once those three are answered, I can ship the wire-up PR.
