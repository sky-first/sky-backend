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


# Template adapted from the marketing email_preview.html design (Lucas's
# 2026-04-29 brief): hero band with the SkyFirst Labs banner, framed
# personal note from Lucas, single CTA, signature card with social
# buttons. Social URLs are placeholders until Lucas sends the final
# links — they fall back to the website root if {social_*} is empty so
# the layout never breaks.
_DEMO_WELCOME_HTML = """\
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8"/></head>
  <body style="margin:0;padding:0;background:#e8e8ea;
               font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#f4f4f5;padding:40px 0;">
      <tr>
        <td align="center">
          <table width="580" cellpadding="0" cellspacing="0"
                 style="background:#ffffff;border-radius:12px;overflow:hidden;
                        box-shadow:0 2px 12px rgba(0,0,0,0.07);">
            <tr>
              <td style="background:#0a0a0a;padding:0;text-align:center;">
                <a href="https://www.skyfirstlabs.com" target="_blank">
                  <img src="https://i.postimg.cc/8z6WZG7V/Chat-GPT-Image-Apr-28-2026-04-25-58-PM.png"
                       alt="SkyFirst Labs"
                       width="580"
                       style="display:block;width:100%;max-width:580px;height:auto;border:0;"/>
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:40px 40px 32px;">
                <p style="margin:0 0 20px;font-size:16px;color:#111;line-height:1.6;">
                  Hi {first_name},
                </p>
                <p style="margin:0 0 20px;font-size:16px;color:#333;line-height:1.7;">
                  Your <strong>SKY</strong> sandbox for <strong>{company}</strong> is live.
                  No installs, no SQL — five connected datasets and the AI is
                  ready to answer the same questions you'd normally send to
                  an analyst.
                </p>
                <p style="margin:0 0 20px;font-size:16px;color:#333;line-height:1.7;">
                  The fastest way to feel the product:<br/>
                  open the chat and ask <em>"What's our weakest revenue
                  channel and why?"</em><br/>
                  In 10 seconds you'll have an answer that joins CRM,
                  Marketing, Finance, Product Usage and Web Analytics — no
                  ticket, no waiting.
                </p>
                <p style="margin:0 0 28px;font-size:16px;color:#333;line-height:1.7;">
                  Sandbox auto-deletes after <strong>{ttl_days} days</strong>.
                  Invite teammates with the same email domain — they'll join
                  the same workspace automatically.
                </p>
                <table cellpadding="0" cellspacing="0" style="margin:0 0 32px;">
                  <tr>
                    <td style="background:#0a0a0a;border-radius:8px;">
                      <a href="{dashboard_url}"
                         target="_blank"
                         style="display:inline-block;padding:14px 32px;color:#ffffff;
                                font-size:15px;font-weight:600;text-decoration:none;">
                        Open your sandbox &rarr;
                      </a>
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 8px;font-size:15px;color:#555;line-height:1.6;">
                  When you're ready to see SKY on <strong>your real data</strong>,
                  just reply — I'll set up a 30-minute founder-led session.
                </p>
              </td>
            </tr>
            <tr><td style="padding:0 40px;"><hr style="border:none;border-top:1px solid #ebebeb;margin:0;"/></td></tr>
            <tr>
              <td style="padding:28px 40px 36px;background:#fafafa;">
                <table cellpadding="0" cellspacing="0" width="100%">
                  <tr>
                    <td style="vertical-align:middle;">
                      <p style="margin:0 0 2px;font-size:15px;font-weight:700;color:#111;letter-spacing:-0.2px;">
                        Lucas Ventura
                      </p>
                      <p style="margin:0 0 16px;font-size:12px;color:#999;text-transform:uppercase;letter-spacing:0.5px;">
                        Founder &middot; SkyFirst Labs
                      </p>
                      <table cellpadding="0" cellspacing="0">
                        <tr>
                          <td style="padding-right:8px;">
                            <a href="https://www.skyfirstlabs.com" target="_blank"
                               style="display:inline-block;padding:8px 16px;background:#0a0a0a;border-radius:6px;font-size:12px;font-weight:600;color:#ffffff;text-decoration:none;letter-spacing:0.2px;">
                              &#127758;&nbsp; Website
                            </a>
                          </td>
                          <td>
                            <a href="https://www.linkedin.com/company/skyfirstlabs/" target="_blank"
                               style="display:inline-block;padding:8px 16px;background:#0A66C2;border-radius:6px;font-size:12px;font-weight:600;color:#ffffff;text-decoration:none;letter-spacing:0.2px;">
                              &#x1F517;&nbsp; LinkedIn
                            </a>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
          <p style="margin:20px 0 0;font-size:11px;color:#aaa;text-align:center;">
            SkyFirst Labs &mdash; You're receiving this because you signed up
            for a SKY sandbox at demo.skyfirstlabs.com.
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


_DEMO_WELCOME_TEXT = """\
Hi {first_name},

Your SKY sandbox for {company} is live: {dashboard_url}

The fastest way to feel the product:
open the chat and ask "What's our weakest revenue channel and why?"
In 10 seconds you'll have an answer that joins CRM, Marketing,
Finance, Product Usage and Web Analytics — no ticket, no waiting.

Sandbox auto-deletes after {ttl_days} days. Invite teammates with
the same email domain — they'll join the same workspace automatically.

When you're ready to see SKY on your real data, just reply — I'll
set up a 30-minute founder-led session.

— Lucas Ventura
Founder, SkyFirst Labs
https://www.skyfirstlabs.com
https://www.linkedin.com/company/skyfirstlabs/
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
