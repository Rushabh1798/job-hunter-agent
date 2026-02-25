"""Email delivery via SendGrid or SMTP."""

from __future__ import annotations

import asyncio
from email.mime.multipart import MIMEMultipart

import structlog

from job_hunter_core.exceptions import EmailDeliveryError

logger = structlog.get_logger()


class EmailSender:
    """Send emails via SMTP or SendGrid."""

    def __init__(
        self,
        provider: str = "smtp",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        sendgrid_api_key: str = "",
    ) -> None:
        """Initialize with email provider configuration."""
        self._provider = provider
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password
        self._sendgrid_api_key = sendgrid_api_key

    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        attachment_path: str | None = None,
    ) -> bool:
        """Send an email with optional attachment."""
        try:
            if self._provider == "sendgrid":
                return await self._send_sendgrid(
                    to_email, subject, html_body, text_body, attachment_path
                )
            return await self._send_smtp(to_email, subject, html_body, text_body, attachment_path)
        except EmailDeliveryError:
            raise
        except Exception as e:
            logger.error("email_send_failed", to=to_email, error=str(e))
            raise EmailDeliveryError(str(e)) from e

    async def _send_smtp(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        attachment_path: str | None = None,
    ) -> bool:
        """Send via SMTP using aiosmtplib."""
        import aiosmtplib

        msg = await asyncio.to_thread(
            self._build_smtp_message,
            to_email,
            subject,
            html_body,
            text_body,
            attachment_path,
        )
        await aiosmtplib.send(
            msg,
            hostname=self._smtp_host,
            port=self._smtp_port,
            username=self._smtp_user,
            password=self._smtp_password,
            start_tls=True,
        )
        logger.info("email_sent_smtp", to=to_email)
        return True

    def _build_smtp_message(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        attachment_path: str | None = None,
    ) -> MIMEMultipart:
        """Build MIME message (sync, runs in thread)."""
        from email import encoders
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from pathlib import Path

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = self._smtp_user
        msg["To"] = to_email

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text_body, "plain"))
        alt.attach(MIMEText(html_body, "html"))
        msg.attach(alt)

        if attachment_path:
            path = Path(attachment_path)
            if path.exists():
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={path.name}",
                )
                msg.attach(part)

        return msg

    async def _send_sendgrid(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        attachment_path: str | None = None,
    ) -> bool:
        """Send via SendGrid API."""

        def _send() -> bool:
            import base64
            from pathlib import Path

            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import (
                Attachment,
                Content,
                Email,
                Mail,
                To,
            )

            message = Mail(
                from_email=Email(self._smtp_user or "noreply@jobhunter.dev"),
                to_emails=To(to_email),
                subject=subject,
            )
            message.content = [
                Content("text/plain", text_body),
                Content("text/html", html_body),
            ]

            if attachment_path:
                path = Path(attachment_path)
                if path.exists():
                    with open(path, "rb") as f:
                        data = base64.b64encode(f.read()).decode()
                    attachment = Attachment()
                    attachment.file_content = data
                    attachment.file_name = path.name
                    xlsx_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    attachment.file_type = xlsx_type
                    message.attachment = attachment

            sg = SendGridAPIClient(self._sendgrid_api_key)
            response = sg.send(message)
            return response.status_code in (200, 201, 202)

        result = await asyncio.to_thread(_send)
        logger.info("email_sent_sendgrid", to=to_email)
        return result
