"""
Shared HTTP client for GitHub API operations.

Provides a singleton AsyncClient with connection pooling for all GitHub API calls.
This eliminates ~50-100ms SSL handshake overhead per request by reusing connections.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# Module-level singleton client
_client: httpx.AsyncClient | None = None


def get_github_client() -> httpx.AsyncClient:
    """
    Get or create the shared HTTP client for GitHub API calls.

    The client is shared across all GitHubService instances to maximize
    connection reuse. Auth headers are passed per-request, not stored on the client.

    Returns:
        Shared httpx.AsyncClient configured for GitHub API
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            http2=True,  # Enable HTTP/2 for GitHub API
        )
        logger.debug("Created new GitHub HTTP client with connection pooling")
    return _client


async def close_github_client() -> None:
    """
    Close the shared HTTP client.

    Call on app shutdown for graceful termination.
    """
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        logger.debug("Closed GitHub HTTP client")
