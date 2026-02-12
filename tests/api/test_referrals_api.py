"""Referral API endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_referral_codes(api_client: AsyncClient, test_referral_code):
    """GET /api/v1/referrals/codes returns codes and stats."""
    resp = await api_client.get("/api/v1/referrals/codes")
    assert resp.status_code == 200
    data = resp.json()
    assert "codes" in data
    assert "stats" in data
    assert isinstance(data["codes"], list)


@pytest.mark.anyio
async def test_create_referral_code(api_client: AsyncClient):
    """POST /api/v1/referrals/codes generates a new code."""
    resp = await api_client.post("/api/v1/referrals/codes")
    assert resp.status_code == 201
    data = resp.json()
    assert "code" in data
    assert isinstance(data["code"], str)


@pytest.mark.anyio
async def test_get_referral_stats(api_client: AsyncClient, test_referral_code):
    """GET /api/v1/referrals/stats returns referral statistics."""
    resp = await api_client.get("/api/v1/referrals/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_codes" in data
    assert "remaining_invites" in data


@pytest.mark.anyio
async def test_validate_code(api_client: AsyncClient, test_referral_code):
    """GET /api/v1/referrals/validate/{code} validates a code."""
    resp = await api_client.get(f"/api/v1/referrals/validate/{test_referral_code.code}")
    assert resp.status_code == 200
    data = resp.json()
    assert "valid" in data
    assert data["valid"] is True
