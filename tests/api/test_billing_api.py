"""Billing API endpoint tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_plans(api_client: AsyncClient):
    """GET /api/v1/billing/plans returns available plans."""
    resp = await api_client.get("/api/v1/billing/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    tiers = [p["tier"] for p in data]
    assert "indie" in tiers


@pytest.mark.anyio
async def test_get_subscription(
    api_client: AsyncClient, test_org, test_subscription
):
    """GET /api/v1/billing/subscription/{org_id} returns subscription info."""
    resp = await api_client.get(f"/api/v1/billing/subscription/{test_org.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_tier"] == "indie"


@pytest.mark.anyio
async def test_create_checkout(
    api_client: AsyncClient,
    test_org,
    test_subscription,
    db_session,
    mock_external_services,
):
    """POST /api/v1/billing/checkout returns checkout URL."""
    from app.domain.subscription_operations import subscription_ops

    # Fixture sets is_manually_assigned=True; checkout rejects manual subs
    await subscription_ops.update(
        db_session,
        test_subscription,
        {"is_manually_assigned": False},
    )
    await db_session.flush()

    with patch("app.api.v1.billing.settings") as mock_settings:
        mock_settings.stripe_enabled = True
        mock_settings.frontend_url = "http://test"
        resp = await api_client.post(
            "/api/v1/billing/checkout",
            json={
                "plan_tier": "indie",
                "organization_id": str(test_org.id),
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "checkout_url" in data


@pytest.mark.anyio
async def test_cancel_subscription(
    api_client: AsyncClient,
    test_org,
    test_subscription,
    db_session,
    mock_external_services,
):
    """POST /api/v1/billing/cancel schedules cancellation."""
    from app.domain.subscription_operations import subscription_ops

    # Set up required Stripe fields for cancellation
    await subscription_ops.update(
        db_session,
        test_subscription,
        {
            "stripe_subscription_id": "sub_test_123",
            "stripe_customer_id": "cus_test_123",
            "is_manually_assigned": False,
        },
    )
    await db_session.flush()

    mock_external_services["stripe"].cancel_subscription = MagicMock(return_value=True)
    mock_external_services["stripe"].get_subscription = MagicMock(return_value=None)

    with patch("app.api.v1.billing.settings") as mock_settings:
        mock_settings.stripe_enabled = True
        mock_settings.frontend_url = "http://test"
        resp = await api_client.post(
            "/api/v1/billing/cancel",
            json={"organization_id": str(test_org.id)},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "cancel_at" in data


@pytest.mark.anyio
async def test_non_member_subscription(
    second_user_client: AsyncClient, test_org, test_subscription
):
    """GET /api/v1/billing/subscription/{org_id} returns 403 for non-members."""
    resp = await second_user_client.get(
        f"/api/v1/billing/subscription/{test_org.id}"
    )
    assert resp.status_code == 403
