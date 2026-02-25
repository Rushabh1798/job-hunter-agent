"""Unit tests for Temporal client factory."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from job_hunter_core.exceptions import TemporalConnectionError

pytestmark = pytest.mark.unit


@pytest.fixture
def temporal_settings(mock_settings: MagicMock) -> MagicMock:
    """Settings configured for Temporal."""
    mock_settings.temporal_address = "localhost:7233"
    mock_settings.temporal_namespace = "default"
    mock_settings.temporal_tls_cert_path = None
    mock_settings.temporal_tls_key_path = None
    mock_settings.temporal_api_key = None
    return mock_settings


@pytest.mark.asyncio
async def test_create_client_plain_tcp(temporal_settings: MagicMock) -> None:
    """Plain TCP connection succeeds."""
    mock_client = AsyncMock()
    with patch(
        "job_hunter_agents.orchestrator.temporal_client.Client.connect",
        return_value=mock_client,
    ) as connect:
        from job_hunter_agents.orchestrator.temporal_client import create_temporal_client

        client = await create_temporal_client(temporal_settings)
        assert client is mock_client
        connect.assert_awaited_once_with(
            "localhost:7233",
            namespace="default",
            tls=False,
            rpc_metadata={},
        )


@pytest.mark.asyncio
async def test_create_client_mtls(temporal_settings: MagicMock) -> None:
    """mTLS connection reads cert and key files."""
    temporal_settings.temporal_tls_cert_path = "/certs/client.pem"
    temporal_settings.temporal_tls_key_path = "/certs/client.key"
    mock_client = AsyncMock()

    cert_data = b"cert-content"
    key_data = b"key-content"

    def fake_open(path: str, mode: str = "r") -> MagicMock:
        if "client.pem" in path:
            return mock_open(read_data=cert_data)()
        return mock_open(read_data=key_data)()

    with (
        patch("builtins.open", side_effect=fake_open),
        patch(
            "job_hunter_agents.orchestrator.temporal_client.Client.connect",
            return_value=mock_client,
        ) as connect,
    ):
        from job_hunter_agents.orchestrator.temporal_client import create_temporal_client

        await create_temporal_client(temporal_settings)
        call_kwargs = connect.call_args.kwargs
        assert call_kwargs["tls"] is not False


@pytest.mark.asyncio
async def test_create_client_api_key(temporal_settings: MagicMock) -> None:
    """API key auth sets authorization header in RPC metadata."""
    api_key_mock = MagicMock()
    api_key_mock.get_secret_value.return_value = "test-api-key"
    temporal_settings.temporal_api_key = api_key_mock

    mock_client = AsyncMock()
    with patch(
        "job_hunter_agents.orchestrator.temporal_client.Client.connect",
        return_value=mock_client,
    ) as connect:
        from job_hunter_agents.orchestrator.temporal_client import create_temporal_client

        await create_temporal_client(temporal_settings)
        call_kwargs = connect.call_args.kwargs
        assert call_kwargs["rpc_metadata"]["authorization"] == "Bearer test-api-key"
        assert call_kwargs["rpc_metadata"]["temporal-namespace"] == "default"


@pytest.mark.asyncio
async def test_create_client_connection_failure_raises(
    temporal_settings: MagicMock,
) -> None:
    """Connection failure raises TemporalConnectionError."""
    with patch(
        "job_hunter_agents.orchestrator.temporal_client.Client.connect",
        side_effect=OSError("Connection refused"),
    ):
        from job_hunter_agents.orchestrator.temporal_client import create_temporal_client

        with pytest.raises(TemporalConnectionError, match="Connection refused"):
            await create_temporal_client(temporal_settings)


@pytest.mark.asyncio
async def test_check_temporal_available_true(temporal_settings: MagicMock) -> None:
    """Returns True when Temporal is reachable."""
    with patch(
        "job_hunter_agents.orchestrator.temporal_client.Client.connect",
        return_value=AsyncMock(),
    ):
        from job_hunter_agents.orchestrator.temporal_client import check_temporal_available

        assert await check_temporal_available(temporal_settings) is True


@pytest.mark.asyncio
async def test_check_temporal_available_false(temporal_settings: MagicMock) -> None:
    """Returns False when Temporal is unreachable."""
    with patch(
        "job_hunter_agents.orchestrator.temporal_client.Client.connect",
        side_effect=OSError("refused"),
    ):
        from job_hunter_agents.orchestrator.temporal_client import check_temporal_available

        assert await check_temporal_available(temporal_settings) is False
