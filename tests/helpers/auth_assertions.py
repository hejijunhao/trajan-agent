"""Shared assertion helpers for authorization boundary tests.

Usage:
    await assert_requires_auth(unauth_client, "get", "/api/v1/products/")
    await assert_non_member_blocked(second_user_client, "get", url)
    await assert_viewer_cannot_write(viewer_client, "post", url, json={...})
"""

from __future__ import annotations

from httpx import AsyncClient


async def assert_requires_auth(
    client: AsyncClient, method: str, url: str, **kwargs
) -> None:
    """Verify endpoint returns 401 without auth."""
    resp = await getattr(client, method)(url, **kwargs)
    assert resp.status_code == 401, (
        f"{method.upper()} {url} expected 401, got {resp.status_code}: {resp.text}"
    )


async def assert_non_member_blocked(
    client: AsyncClient, method: str, url: str, **kwargs
) -> None:
    """Verify endpoint returns 403 or 404 for non-members."""
    resp = await getattr(client, method)(url, **kwargs)
    assert resp.status_code in (403, 404), (
        f"{method.upper()} {url} expected 403/404, got {resp.status_code}: {resp.text}"
    )


async def assert_viewer_cannot_write(
    client: AsyncClient, method: str, url: str, **kwargs
) -> None:
    """Verify write endpoints return 403 for viewers."""
    resp = await getattr(client, method)(url, **kwargs)
    assert resp.status_code == 403, (
        f"{method.upper()} {url} expected 403, got {resp.status_code}: {resp.text}"
    )
