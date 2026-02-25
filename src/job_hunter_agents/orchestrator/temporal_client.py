"""Temporal client factory with connection testing and auth support."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from temporalio.client import Client, TLSConfig

from job_hunter_core.exceptions import TemporalConnectionError

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings

logger = structlog.get_logger()


async def create_temporal_client(settings: Settings) -> Client:
    """Create a Temporal client from settings.

    Supports three auth modes:
    - Plain TCP (no auth, local/self-hosted dev)
    - mTLS (Temporal Cloud or self-hosted with TLS cert/key)
    - API key (Temporal Cloud with bearer token)

    Raises:
        TemporalConnectionError: If the server is unreachable.
    """
    tls_config = _build_tls_config(settings)
    rpc_metadata = _build_rpc_metadata(settings)

    try:
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
            tls=tls_config,
            rpc_metadata=rpc_metadata,
        )
        logger.info(
            "temporal_connected",
            address=settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
        return client
    except Exception as exc:
        logger.warning(
            "temporal_connection_failed",
            address=settings.temporal_address,
            error=str(exc),
        )
        msg = f"Cannot connect to Temporal at {settings.temporal_address}: {exc}"
        raise TemporalConnectionError(msg) from exc


async def check_temporal_available(settings: Settings) -> bool:
    """Test if Temporal server is reachable. Returns False on failure."""
    try:
        await create_temporal_client(settings)
    except TemporalConnectionError:
        return False
    return True


def _build_tls_config(settings: Settings) -> TLSConfig | bool:
    """Build TLS configuration from settings."""
    cert_path = settings.temporal_tls_cert_path
    key_path = settings.temporal_tls_key_path

    if cert_path and key_path:
        with open(cert_path, "rb") as f:
            client_cert = f.read()
        with open(key_path, "rb") as f:
            client_key = f.read()
        return TLSConfig(client_cert=client_cert, client_private_key=client_key)

    return False


def _build_rpc_metadata(settings: Settings) -> dict[str, str]:
    """Build RPC metadata for API key authentication."""
    metadata: dict[str, str] = {}
    if settings.temporal_api_key:
        api_key = settings.temporal_api_key.get_secret_value()
        metadata["temporal-namespace"] = settings.temporal_namespace
        metadata["authorization"] = f"Bearer {api_key}"
    return metadata
