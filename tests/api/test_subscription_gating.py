"""Subscription gating API tests — verify 402 enforcement on write endpoints.

Uses the work-items endpoint as a representative gated endpoint.
Tests that the require_product_subscription() dependency correctly
blocks pending subscriptions (402) and allows active/trialing ones (200/201).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _work_item_payload(product_id: str) -> dict:
    """Minimal valid work item creation payload."""
    return {
        "product_id": product_id,
        "title": "Test gating work item",
        "type": "feature",
        "status": "todo",
    }


class TestSubscriptionGatingOnCreate:
    """Write endpoints return 402 when subscription is pending/none."""

    @pytest.mark.anyio
    async def test_pending_subscription_returns_402(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session: AsyncSession,
    ):
        """Subscription with status=pending and tier=none blocks writes."""
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {"plan_tier": "none", "status": "pending"},
        )
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/work-items",
            json=_work_item_payload(str(test_product.id)),
        )

        assert resp.status_code == 402
        data = resp.json()
        assert data["detail"]["code"] == "SUBSCRIPTION_REQUIRED"

    @pytest.mark.anyio
    async def test_none_tier_active_status_returns_402(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session: AsyncSession,
    ):
        """Even with status=active, tier=none still blocks (no plan selected)."""
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {"plan_tier": "none", "status": "active"},
        )
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/work-items",
            json=_work_item_payload(str(test_product.id)),
        )

        assert resp.status_code == 402

    @pytest.mark.anyio
    async def test_active_subscription_allows_create(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session: AsyncSession,
    ):
        """Active indie subscription allows work item creation (201)."""
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {"plan_tier": "indie", "status": "active"},
        )
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/work-items",
            json=_work_item_payload(str(test_product.id)),
        )

        assert resp.status_code == 201

    @pytest.mark.anyio
    async def test_trialing_subscription_allows_create(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session: AsyncSession,
    ):
        """Trialing subscription allows writes (trial is like active)."""
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {"plan_tier": "indie", "status": "trialing"},
        )
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/work-items",
            json=_work_item_payload(str(test_product.id)),
        )

        assert resp.status_code == 201

    @pytest.mark.anyio
    async def test_past_due_subscription_still_allows_create(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session: AsyncSession,
    ):
        """Past-due subscription is NOT blocked — only pending/none are."""
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {"plan_tier": "indie", "status": "past_due"},
        )
        await db_session.flush()

        resp = await api_client.post(
            "/api/v1/work-items",
            json=_work_item_payload(str(test_product.id)),
        )

        assert resp.status_code == 201


class TestSubscriptionGatingOnRead:
    """Read endpoints are NOT gated by subscription status."""

    @pytest.mark.anyio
    async def test_pending_subscription_allows_read(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session: AsyncSession,
    ):
        """Work item listing works even with pending subscription."""
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {"plan_tier": "none", "status": "pending"},
        )
        await db_session.flush()

        resp = await api_client.get(
            "/api/v1/work-items",
            params={"product_id": str(test_product.id)},
        )

        # Read should succeed (list returns empty array)
        assert resp.status_code == 200
