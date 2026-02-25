"""Tests for email sender tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter_agents.tools.email_sender import EmailSender
from job_hunter_core.exceptions import EmailDeliveryError


@pytest.mark.unit
class TestEmailSender:
    """Test EmailSender provider routing and error handling."""

    def test_defaults_to_smtp(self) -> None:
        """Default provider is smtp."""
        sender = EmailSender()
        assert sender._provider == "smtp"

    @pytest.mark.asyncio
    async def test_send_routes_to_smtp(self) -> None:
        """send() calls _send_smtp for smtp provider."""
        sender = EmailSender(provider="smtp")
        with patch.object(
            sender, "_send_smtp", new_callable=AsyncMock, return_value=True
        ) as mock_smtp:
            result = await sender.send("user@example.com", "Subject", "<p>hi</p>", "hi")

        assert result is True
        mock_smtp.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_routes_to_sendgrid(self) -> None:
        """send() calls _send_sendgrid for sendgrid provider."""
        sender = EmailSender(provider="sendgrid", sendgrid_api_key="sg-key")
        with patch.object(
            sender, "_send_sendgrid", new_callable=AsyncMock, return_value=True
        ) as mock_sg:
            result = await sender.send("user@example.com", "Subject", "<p>hi</p>", "hi")

        assert result is True
        mock_sg.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_wraps_errors(self) -> None:
        """send() wraps unexpected errors in EmailDeliveryError."""
        sender = EmailSender(provider="smtp")
        with patch.object(
            sender,
            "_send_smtp",
            new_callable=AsyncMock,
            side_effect=ConnectionError("refused"),
        ):
            with pytest.raises(EmailDeliveryError, match="refused"):
                await sender.send("user@example.com", "Subject", "<p>hi</p>", "hi")

    @pytest.mark.asyncio
    async def test_send_reraises_email_delivery_error(self) -> None:
        """send() re-raises EmailDeliveryError directly."""
        sender = EmailSender(provider="smtp")
        with patch.object(
            sender,
            "_send_smtp",
            new_callable=AsyncMock,
            side_effect=EmailDeliveryError("already wrapped"),
        ):
            with pytest.raises(EmailDeliveryError, match="already wrapped"):
                await sender.send("user@example.com", "Subject", "<p>hi</p>", "hi")

    @pytest.mark.asyncio
    async def test_send_smtp_builds_message(self) -> None:
        """_send_smtp builds proper MIME message and sends."""
        sender = EmailSender(
            smtp_user="sender@example.com",
            smtp_password="pass",
        )
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await sender._send_smtp(
                "to@example.com", "Test Subject", "<p>body</p>", "body"
            )

        assert result is True
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg["To"] == "to@example.com"
        assert msg["Subject"] == "Test Subject"

    def test_build_smtp_message_no_attachment(self) -> None:
        """_build_smtp_message creates message without attachment."""
        sender = EmailSender(smtp_user="sender@example.com")
        msg = sender._build_smtp_message("to@example.com", "Subject", "<p>html</p>", "text")
        assert msg["From"] == "sender@example.com"
        assert msg["To"] == "to@example.com"

    def test_build_smtp_message_with_attachment(self, tmp_path: Path) -> None:
        """_build_smtp_message includes file attachment."""
        sender = EmailSender(smtp_user="sender@example.com")
        attachment = tmp_path / "results.xlsx"
        attachment.write_bytes(b"fake xlsx content")

        msg = sender._build_smtp_message(
            "to@example.com", "Subject", "<p>html</p>", "text", str(attachment)
        )
        assert msg["From"] == "sender@example.com"
        payloads = msg.get_payload()
        assert len(payloads) == 2  # alt + attachment

    def test_build_smtp_message_with_nonexistent_attachment(self) -> None:
        """_build_smtp_message skips non-existent attachment."""
        sender = EmailSender(smtp_user="sender@example.com")
        msg = sender._build_smtp_message(
            "to@example.com", "Subject", "<p>html</p>", "text", "/nonexistent/file.xlsx"
        )
        payloads = msg.get_payload()
        assert len(payloads) == 1  # only alt, no attachment

    @pytest.mark.asyncio
    async def test_send_sendgrid(self) -> None:
        """_send_sendgrid calls SendGrid API."""
        sender = EmailSender(
            provider="sendgrid",
            sendgrid_api_key="sg-test-key",
            smtp_user="from@example.com",
        )

        mock_sg_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_sg_client.send.return_value = mock_response

        with patch("sendgrid.SendGridAPIClient", return_value=mock_sg_client):
            result = await sender._send_sendgrid(
                "to@example.com", "Subject", "<p>html</p>", "text"
            )

        assert result is True
        mock_sg_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_sendgrid_with_attachment(self, tmp_path: Path) -> None:
        """_send_sendgrid attaches file when path exists."""
        sender = EmailSender(
            provider="sendgrid",
            sendgrid_api_key="sg-test-key",
        )
        attachment = tmp_path / "results.xlsx"
        attachment.write_bytes(b"fake xlsx content")

        mock_sg_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_sg_client.send.return_value = mock_response

        with patch("sendgrid.SendGridAPIClient", return_value=mock_sg_client):
            result = await sender._send_sendgrid(
                "to@example.com", "Subject", "<p>html</p>", "text", str(attachment)
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_smtp_with_attachment(self, tmp_path: Path) -> None:
        """_send_smtp sends message with attachment."""
        sender = EmailSender(
            smtp_user="sender@example.com",
            smtp_password="pass",
        )
        attachment = tmp_path / "report.csv"
        attachment.write_text("col1,col2\n1,2")

        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await sender._send_smtp(
                "to@example.com", "Subject", "<p>body</p>", "body", str(attachment)
            )

        assert result is True
        mock_send.assert_called_once()
