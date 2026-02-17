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

    def send_invite_email(self, to_email: str, invite_link: str, inviter_name: str = "Administrator") -> bool:
        """
        Send invitation email.

        Args:
            to_email: Recipient email
            invite_link: Activation link
            inviter_name: Name of the person inviting

        Returns:
            bool: Success status
        """
        subject = f"You have been invited to join {settings.APP_NAME}"

        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 8px;">
              <h2 style="color: #1e3a5f;">Welcome to {settings.APP_NAME}</h2>
              <p>Hello,</p>
              <p>You have been invited by <strong>{inviter_name}</strong> to join the workspace.</p>
              <p>Please click the button below to accept the invitation and set your password:</p>
              <div style="text-align: center; margin: 30px 0;">
                <a href="{invite_link}" style="background-color: #3b82f6; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">Accept Invitation</a>
              </div>
              <p style="font-size: 12px; color: #777;">
                Or copy and paste this link into your browser:<br>
                <a href="{invite_link}">{invite_link}</a>
              </p>
              <p style="font-size: 12px; color: #999; margin-top: 30px;">
                This link will expire in 7 days.
              </p>
            </div>
          </body>
        </html>
        """

        text_content = f"""
        Welcome to {settings.APP_NAME}

        Hello,

        You have been invited by {inviter_name} to join the workspace.

        Please accept the invitation and set your password by visiting this link:
        {invite_link}

        This link will expire in 7 days.
        """

        return self.send_email(to_email, subject, html_content, text_content)
