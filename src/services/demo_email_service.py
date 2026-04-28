"""Demo welcome email — Resend transactional sender.

Purpose
-------
First sales touchpoint after a demo signup. The email is intentionally:

  - Personal: comes from lucas.ventura@skyfirstlabs.com (not noreply@)
    so replies go straight to Lucas's inbox
  - One-CTA: a single ask ("reply to this email") instead of a
    button forest
  - Curiosity-loaded: the body contains ONE specific question to ask
    the AI in the demo, designed to land the "this is impressive"
    moment in under 30 seconds
  - Bridge-builder: explicitly frames the demo as a preview of what
    the production product does on YOUR data, then offers a 30-min
    founder call as the next step

Why a separate service file (not extending email_service.py)
------------------------------------------------------------
The existing EmailService is a sync SMTP client; this one is async
+ Resend REST. Mixing the two would force every welcome-email caller
to know which transport to use. Keeping it isolated lets us:
  - Call from `async def signup` without a thread bridge
  - Add new Resend-backed templates (ticket replies, expiry
    reminders, etc.) here without touching the SMTP path

Best-effort delivery
--------------------
Failures (no API key, 4xx/5xx from Resend, network) are LOGGED and
SWALLOWED — never propagate out. The signup must complete even if
the email vendor is down. Same contract as the Slack webhooks.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from src.config.settings import settings

logger = logging.getLogger(__name__)


# ─── Welcome email content ──────────────────────────────────────────────────
#
# Three placeholders only — we keep templating dead-simple (str.format)
# so the copy stays editable by non-engineers and we don't need to pull
# Jinja2 just for one email.


_DEMO_WELCOME_SUBJECT = "Your SKY sandbox is live — try this in 10 seconds"


_DEMO_WELCOME_HTML = """\
<!doctype html>
<html lang="en">
  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
               Roboto, Helvetica, Arial, sans-serif;
               background:#f8fafc;color:#0f172a;margin:0;padding:32px;">
    <div style="max-width:560px;margin:0 auto;background:#ffffff;
                border:1px solid #e2e8f0;border-radius:12px;padding:32px;">

      <h1 style="font-size:22px;line-height:1.3;margin:0 0 16px 0;">
        Hi {first_name},
      </h1>

      <p style="font-size:15px;line-height:1.6;margin:0 0 20px 0;">
        Your SKY demo for <strong>{company}</strong> is live at
        <a href="{dashboard_url}" style="color:#0f766e;font-weight:600;">
          demo.skyfirstlabs.com
        </a>.
        TTL is {ttl_days} days — invite your team and we'll bring them
        into your sandbox automatically (same email domain).
      </p>

      <p style="font-size:15px;line-height:1.6;margin:0 0 12px 0;">
        Most teams ask the AI this first:
      </p>

      <div style="background:#f1f5f9;border-left:3px solid #0f766e;
                  padding:14px 18px;margin:0 0 20px 0;border-radius:6px;
                  font-family: 'SF Mono', Menlo, Consolas, monospace;
                  font-size:14px;line-height:1.5;color:#0f172a;">
        💬 What's our weakest revenue channel and why?
      </div>

      <p style="font-size:15px;line-height:1.6;margin:0 0 20px 0;">
        The synthetic dataset spans CRM, Marketing, Finance, Web Analytics
        and Product Usage. The AI joins all 5 schemas in plain English —
        no SQL, no clicking through six dashboards.
      </p>

      <p style="font-size:15px;line-height:1.6;margin:0 0 28px 0;">
        That's the demo. The real product does the same on
        <strong>your data</strong> — Salesforce, Snowflake, Postgres,
        anything you actually use. Same answer, your numbers.
      </p>

      <p style="font-size:15px;line-height:1.6;margin:0 0 8px 0;
                font-weight:600;">
        Next step
      </p>
      <p style="font-size:15px;line-height:1.6;margin:0 0 28px 0;">
        Reply to this email and we'll see SKY on your data in 30 minutes.
        Founder-led, no slides, real answers from your real systems.
      </p>

      <p style="font-size:14px;line-height:1.5;color:#64748b;margin:0;">
        — Lucas Ventura<br/>
        Founder, SKY<br/>
        <a href="mailto:lucas.ventura@skyfirstlabs.com"
           style="color:#64748b;">lucas.ventura@skyfirstlabs.com</a>
      </p>
    </div>

    <p style="max-width:560px;margin:16px auto 0 auto;font-size:11px;
              line-height:1.5;color:#94a3b8;text-align:center;">
      You're receiving this because you signed up for a SKY demo at
      demo.skyfirstlabs.com. The sandbox auto-deletes after {ttl_days}
      days.
    </p>
  </body>
</html>
"""


_DEMO_WELCOME_TEXT = """\
Hi {first_name},

Your SKY demo for {company} is live at {dashboard_url}.
TTL is {ttl_days} days — invite your team and they'll join your
sandbox automatically (same email domain).

Most teams ask the AI this first:

  > What's our weakest revenue channel and why?

The synthetic dataset spans CRM, Marketing, Finance, Web Analytics
and Product Usage. The AI joins all 5 schemas in plain English — no
SQL, no clicking through six dashboards.

That's the demo. The real product does the same on YOUR data —
Salesforce, Snowflake, Postgres, anything you actually use. Same
answer, your numbers.

Next step
---------
Reply to this email and we'll see SKY on your data in 30 minutes.
Founder-led, no slides, real answers from your real systems.

— Lucas Ventura
Founder, SKY
lucas.ventura@skyfirstlabs.com
"""


# ─── Resend POST helper ─────────────────────────────────────────────────────


async def _post_resend(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
) -> bool:
    """POST to the Resend API. Returns True on 2xx, False otherwise.

    Failures swallowed — caller should treat False as "logged, move
    on" not as an error to surface.
    """
    api_key = (settings.RESEND_API_KEY or "").strip()
    if not api_key:
        logger.info(
            "[email-dryrun] would send %r to %s (RESEND_API_KEY empty)",
            subject, to,
        )
        return True  # dry-run = success from the caller's POV

    from_header = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>"

    body = {
        "from": from_header,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.RESEND_TIMEOUT) as client:
            resp = await client.post(
                settings.RESEND_API_URL,
                json=body,
                headers=headers,
            )
        if resp.status_code >= 400:
            logger.error(
                "resend_send_failed status=%s to=%s subject=%r body=%r",
                resp.status_code, to, subject, resp.text[:500],
            )
            return False
        logger.info(
            "resend_send_delivered to=%s subject=%r status=%s",
            to, subject, resp.status_code,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort; never raise
        logger.exception(
            "resend_send_error to=%s subject=%r err=%s", to, subject, exc,
        )
        return False


# ─── Public API ─────────────────────────────────────────────────────────────


async def send_demo_welcome_email(
    *,
    name: str,
    email: str,
    company: str,
    expires_at: Optional[datetime],
) -> None:
    """Fire-and-forget welcome email after a fresh demo signup.

    Pulls only the first name from ``name`` (everything before the
    first space) so the greeting reads naturally even when the form
    captured a full name. Falls back to the literal value if there
    is no space.

    Caller doesn't await the result for routing decisions — the
    function returns None and any error is logged.
    """
    first_name = (name or "there").strip().split(" ", 1)[0] or "there"
    ttl_days = (
        max(1, (expires_at - datetime.now(expires_at.tzinfo)).days)
        if expires_at else 7
    )
    dashboard_url = (settings.EMAIL_DASHBOARD_URL or "").rstrip("/")

    html = _DEMO_WELCOME_HTML.format(
        first_name=first_name,
        company=company or "your team",
        dashboard_url=dashboard_url or "https://demo.skyfirstlabs.com",
        ttl_days=ttl_days,
    )
    text = _DEMO_WELCOME_TEXT.format(
        first_name=first_name,
        company=company or "your team",
        dashboard_url=dashboard_url or "https://demo.skyfirstlabs.com",
        ttl_days=ttl_days,
    )

    await _post_resend(
        to=email,
        subject=_DEMO_WELCOME_SUBJECT,
        html=html,
        text=text,
    )
