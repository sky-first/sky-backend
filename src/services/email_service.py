"""Email service for sending notifications."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.config.settings import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Email service."""

    def __init__(self):
        """Initialize email service."""
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL
        self.use_tls = settings.SMTP_USE_TLS

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """
        Send an email.

        Args:
            to_email: Recipient email
            subject: Email subject
            html_content: HTML content
            text_content: Plain text content (optional)

        Returns:
            bool: True if sent successfully or mocked, False otherwise
        """
        # If no SMTP host is configured, just log it (Mock mode)
        if not self.smtp_host:
            logger.info(f"📧 [MOCK EMAIL] To: {to_email} | Subject: {subject}")
            logger.info(f"   Content: {html_content[:100]}...")
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = to_email

            # Create the body of the message (a plain-text and an HTML version)
            if text_content:
                part1 = MIMEText(text_content, "plain")
                msg.attach(part1)

            part2 = MIMEText(html_content, "html")
            msg.attach(part2)

            # Connect to SMTP server
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()

                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)

                server.sendmail(self.from_email, to_email, msg.as_string())

            logger.info(f"✅ Email sent to {to_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send email to {to_email}: {str(e)}")
            return False

    def send_invite_email(
        self,
        to_email: str,
        invite_link: str,
        inviter_name: str = "Administrator",
        workspace_name: Optional[str] = None,
    ) -> bool:
        """
        Send invitation email.

        Args:
            to_email: Recipient email
            invite_link: Activation link to ``/auth/accept-invite?token=…``
            inviter_name: Name of the person inviting (rendered into the
                preheader + body so the invitee recognises the sender)

        Returns:
            bool: Success status

        Template notes
        --------------
        The HTML body is hand-tuned for the major email clients (Gmail,
        Outlook, Apple Mail, mobile webviews). Three constraints drove
        the design:

        * Inline styles only — ``<style>`` blocks are dropped by Gmail
          in some flows, and Outlook (desktop) ignores most CSS that
          isn't on the element.
        * Tables for layout — flexbox/grid render unreliably in
          Outlook. Two nested centred tables (600px) cover the wide
          majority of clients.
        * Single CTA button — rendered as a styled ``<a>`` so it shows
          even when "display images" is off.

        Brand: black ``#1b1b1b`` header band with gold ``#fbbf24``
        (amber-400, the canonical brand primary used across the
        product) logotype + gold CTA on black text. The logotype is
        rendered as text rather than an ``<img>`` so the email stays
        self-contained — no remote asset fetch, no broken-image
        fallback when corporate firewalls block the image.

        ``inviter_name`` is whatever the caller passes — the same
        template ships to every tenant, so the only thing
        customer-specific in the body is the person doing the
        inviting and the workspace name.
        """
        # Brand the email with the tenant's OWN workspace name, not the
        # platform-wide ``APP_NAME`` (which is the generic backend project
        # name, e.g. "AI SaaS Dashboard Backend"). Resolution order:
        # explicit override → current tenant's display_name → APP_NAME →
        # "Sky". Reading the tenant from the contextvar means every invite
        # path (generate + resend) gets correct branding with no threading.
        if not workspace_name:
            try:
                from src.core.tenant_context import current_tenant

                ctx = current_tenant()
                if ctx is not None and not ctx.is_default:
                    workspace_name = ctx.display_name or None
            except Exception:  # pragma: no cover — defensive, never block send
                workspace_name = None
        app_name = workspace_name or getattr(settings, "APP_NAME", "Sky")
        # Pre-header text: the snippet most clients show next to the
        # subject in the inbox list. Worth ~50 chars of plain copy.
        preheader = (
            f"{inviter_name} invited you to join {app_name}. "
            "Accept your invitation and set your password to get started."
        )
        subject = f"{inviter_name} invited you to join {app_name}"

        html_content = f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="x-apple-disable-message-reformatting">
    <meta name="color-scheme" content="light only">
    <meta name="supported-color-schemes" content="light only">
    <title>{subject}</title>
  </head>
  <body style="margin:0; padding:0; background-color:#F1F5F9; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; color:#1b1b1b;">
    <!-- Pre-header (hidden, but read by inbox preview) -->
    <div style="display:none; max-height:0; overflow:hidden; mso-hide:all; font-size:1px; line-height:1px; color:#F1F5F9;">
      {preheader}
    </div>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#F1F5F9;">
      <tr>
        <td align="center" style="padding:32px 16px;">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px; width:100%; background-color:#FFFFFF; border-radius:16px; overflow:hidden; box-shadow:0 1px 2px rgba(15,23,42,0.06);">

            <!-- Brand band -->
            <tr>
              <td align="center" bgcolor="#1b1b1b" style="background-color:#1b1b1b; padding:36px 24px;">
                <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; font-size:28px; font-weight:800; letter-spacing:8px; color:#FBBF24;">
                  {app_name.upper()}
                </div>
                <div style="margin-top:8px; font-size:10px; font-weight:600; letter-spacing:3px; color:#FBBF24; opacity:0.7; text-transform:uppercase;">
                  Enterprise Collective Intelligence
                </div>
              </td>
            </tr>

            <!-- Body -->
            <tr>
              <td style="padding:40px 40px 8px 40px;">
                <h1 style="margin:0 0 16px 0; font-size:22px; line-height:30px; font-weight:700; color:#1b1b1b;">
                  You&rsquo;re invited to {app_name}
                </h1>
                <p style="margin:0 0 16px 0; font-size:15px; line-height:24px; color:#334155;">
                  <strong>{inviter_name}</strong> has invited you to join the workspace on {app_name} &mdash; the
                  context graph and signals platform their team uses to coordinate decisions.
                </p>
                <p style="margin:0 0 32px 0; font-size:15px; line-height:24px; color:#334155;">
                  Click the button below to accept the invitation and set your password.
                </p>
              </td>
            </tr>

            <!-- CTA: brand gold on black text -->
            <tr>
              <td align="center" style="padding:0 40px 32px 40px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center" bgcolor="#FBBF24" style="border-radius:10px;">
                      <a href="{invite_link}" target="_blank"
                         style="display:inline-block; padding:14px 28px; font-size:14px; font-weight:800; letter-spacing:2px; text-transform:uppercase; color:#1b1b1b; text-decoration:none; border-radius:10px;">
                        Accept invitation
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Fallback link + expiry -->
            <tr>
              <td style="padding:0 40px 32px 40px;">
                <p style="margin:0 0 12px 0; font-size:12px; line-height:18px; color:#64748B;">
                  Button not working? Copy and paste this link into your browser:
                </p>
                <p style="margin:0 0 24px 0; font-size:12px; line-height:18px; color:#D97706; word-break:break-all;">
                  <a href="{invite_link}" style="color:#D97706; text-decoration:underline;">{invite_link}</a>
                </p>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #E2E8F0;">
                  <tr>
                    <td style="padding-top:20px;">
                      <p style="margin:0; font-size:12px; line-height:18px; color:#64748B;">
                        <span style="display:inline-block; padding:2px 8px; background-color:#F1F5F9; color:#475569; border-radius:6px; font-weight:600; font-size:10px; letter-spacing:1px; text-transform:uppercase;">Security</span>
                        &nbsp; This invitation link expires in <strong>7 days</strong>. If you didn&rsquo;t expect this email, you can safely ignore it.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Footer -->
            <tr>
              <td align="center" style="background-color:#F8FAFC; padding:24px 40px;">
                <p style="margin:0; font-size:11px; line-height:16px; color:#94A3B8;">
                  Sent by {app_name} on behalf of {inviter_name}.<br>
                  &copy; Sky First Labs
                </p>
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

        text_content = (
            f"You're invited to {app_name}\n"
            f"\n"
            f"{inviter_name} has invited you to join the workspace on {app_name}.\n"
            f"\n"
            f"Accept the invitation and set your password by opening this link:\n"
            f"{invite_link}\n"
            f"\n"
            f"This link expires in 7 days. If you didn't expect this email, you\n"
            f"can safely ignore it.\n"
            f"\n"
            f"— Sky First Labs\n"
        )
        return self.send_email(to_email, subject, html_content, text_content)
