"""Tests for email sender tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
