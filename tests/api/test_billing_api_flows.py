"""Billing API flow tests — webhook handlers and endpoint lifecycle flows.

Tests the Stripe webhook handler for each event type, plus API-level
tests for portal, reactivation, and downgrade flows.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _webhook_event(event_id: str, event_type: str, obj: dict) -> dict:
    """Build a minimal Stripe webhook event dict."""
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": obj},
    }


async def _send_webhook(
    api_client: AsyncClient,
    event: dict,
    mock_stripe: MagicMock,
) -> object:
    """Post a webhook event, mocking construct_webhook_event to return it."""
    mock_stripe.construct_webhook_event.return_value = event
    return await api_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=b"{}",
        headers={"stripe-signature": "test_sig"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Webhook: checkout.session.completed
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookCheckoutCompleted:
    """checkout.session.completed activates subscription and sets plan tier."""

    @pytest.mark.anyio
    async def test_activates_subscription_as_trialing(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_wh_checkout",
                "is_manually_assigned": False,
                "plan_tier": "none",
                "status": "pending",
            },
        )
        await db_session.flush()

        event = _webhook_event(
            "evt_checkout_001",
            "checkout.session.completed",
            {
                "customer": "cus_wh_checkout",
                "subscription": "sub_new_123",
                "metadata": {"plan_tier": "indie"},
            },
        )

        with patch("app.api.v1.billing.stripe_service") as mock_stripe:
            mock_stripe.construct_webhook_event.return_value = event
            mock_stripe.get_subscription.return_value = {"status": "trialing"}
            mock_stripe.apply_referral_reward.return_value = False

            resp = await api_client.post(
                "/api/v1/billing/webhooks/stripe",
                content=b"{}",
                headers={"stripe-signature": "test_sig"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        await db_session.refresh(test_subscription)
        assert test_subscription.plan_tier == "indie"
        assert test_subscription.stripe_subscription_id == "sub_new_123"
        assert test_subscription.status == "trialing"


# ─────────────────────────────────────────────────────────────────────────────
# Webhook: customer.subscription.updated
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookSubscriptionUpdated:
    """customer.subscription.updated syncs status, period, and cancel flag."""

    @pytest.mark.anyio
    async def test_syncs_status_and_cancel_flag(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_wh_update",
                "is_manually_assigned": False,
                "status": "trialing",
            },
        )
        await db_session.flush()

        event = _webhook_event(
            "evt_sub_updated_001",
            "customer.subscription.updated",
            {
                "customer": "cus_wh_update",
                "status": "active",
                "cancel_at_period_end": True,
                "current_period_start": 1707868800,  # 2024-02-14
                "current_period_end": 1710288000,  # 2024-03-13
            },
        )

        with patch("app.api.v1.billing.stripe_service") as mock_stripe:
            resp = await _send_webhook(api_client, event, mock_stripe)

        assert resp.status_code == 200

        await db_session.refresh(test_subscription)
        assert test_subscription.status == "active"
        assert test_subscription.cancel_at_period_end is True
        assert test_subscription.current_period_start is not None
        assert test_subscription.current_period_end is not None


# ─────────────────────────────────────────────────────────────────────────────
# Webhook: customer.subscription.deleted
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookSubscriptionDeleted:
    """customer.subscription.deleted triggers organization deletion."""

    @pytest.mark.anyio
    async def test_deletes_organization(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        from app.domain.organization_operations import organization_ops
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_wh_delete",
                "is_manually_assigned": False,
            },
        )
        await db_session.flush()

        event = _webhook_event(
            "evt_sub_deleted_001",
            "customer.subscription.deleted",
            {"customer": "cus_wh_delete"},
        )

        with patch("app.api.v1.billing.stripe_service") as mock_stripe:
            resp = await _send_webhook(api_client, event, mock_stripe)

        assert resp.status_code == 200

        # Organization should have been cascade-deleted
        org = await organization_ops.get(db_session, test_org.id)
        assert org is None


# ─────────────────────────────────────────────────────────────────────────────
# Webhook: invoice.payment_failed
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookPaymentFailed:
    """invoice.payment_failed marks subscription as past_due."""

    @pytest.mark.anyio
    async def test_marks_subscription_past_due(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_wh_fail",
                "is_manually_assigned": False,
                "status": "active",
            },
        )
        await db_session.flush()

        event = _webhook_event(
            "evt_payment_fail_001",
            "invoice.payment_failed",
            {"customer": "cus_wh_fail", "id": "in_failed_123"},
        )

        with patch("app.api.v1.billing.stripe_service") as mock_stripe:
            resp = await _send_webhook(api_client, event, mock_stripe)

        assert resp.status_code == 200

        await db_session.refresh(test_subscription)
        assert test_subscription.status == "past_due"


# ─────────────────────────────────────────────────────────────────────────────
# Webhook: Edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookEdgeCases:
    """Duplicate events, unknown types, and invalid signatures."""

    @pytest.mark.anyio
    async def test_duplicate_event_skipped(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        """Second webhook with the same event ID returns already_processed."""
        from app.domain.subscription_operations import subscription_ops
        from app.models.billing import BillingEvent, BillingEventType

        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_wh_dup",
                "is_manually_assigned": False,
            },
        )

        # Pre-insert a BillingEvent with the same stripe_event_id
        existing_event = BillingEvent(
            organization_id=test_org.id,
            event_type=BillingEventType.SUBSCRIPTION_UPDATED.value,
            stripe_event_id="evt_duplicate_001",
            description="Already processed",
        )
        db_session.add(existing_event)
        await db_session.flush()

        event = _webhook_event(
            "evt_duplicate_001",
            "customer.subscription.updated",
            {"customer": "cus_wh_dup", "status": "active", "cancel_at_period_end": False},
        )

        with patch("app.api.v1.billing.stripe_service") as mock_stripe:
            resp = await _send_webhook(api_client, event, mock_stripe)

        assert resp.status_code == 200
        assert resp.json()["status"] == "already_processed"

    @pytest.mark.anyio
    async def test_unknown_event_type_returns_ok(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
    ):
        """Unhandled event types are acknowledged with 200."""
        event = _webhook_event(
            "evt_unknown_001",
            "source.chargeable",
            {"customer": "cus_irrelevant"},
        )

        with patch("app.api.v1.billing.stripe_service") as mock_stripe:
            resp = await _send_webhook(api_client, event, mock_stripe)

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.anyio
    async def test_invalid_signature_returns_400(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
    ):
        """Bad Stripe signature triggers 400."""
        with patch("app.api.v1.billing.stripe_service") as mock_stripe:
            mock_stripe.construct_webhook_event.side_effect = ValueError(
                "Invalid webhook signature"
            )
            resp = await api_client.post(
                "/api/v1/billing/webhooks/stripe",
                content=b"{}",
                headers={"stripe-signature": "bad_sig"},
            )

        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Portal session flow
# ─────────────────────────────────────────────────────────────────────────────


class TestPortalFlow:
    """POST /billing/portal creates a Stripe Customer Portal session."""

    @pytest.mark.anyio
    async def test_returns_portal_url(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_portal_test",
                "is_manually_assigned": False,
            },
        )
        await db_session.flush()

        with (
            patch("app.api.v1.billing.settings") as mock_settings,
            patch("app.api.v1.billing.stripe_service") as mock_stripe,
        ):
            mock_settings.stripe_enabled = True
            mock_settings.frontend_url = "http://test"
            mock_stripe.create_portal_session.return_value = (
                "https://billing.stripe.com/portal/sess_test"
            )

            resp = await api_client.post(
                "/api/v1/billing/portal",
                json={"organization_id": str(test_org.id)},
            )

        assert resp.status_code == 200
        assert resp.json()["portal_url"] == "https://billing.stripe.com/portal/sess_test"


# ─────────────────────────────────────────────────────────────────────────────
# Reactivation flow
# ─────────────────────────────────────────────────────────────────────────────


class TestReactivateFlow:
    """POST /billing/reactivate undoes a pending cancellation."""

    @pytest.mark.anyio
    async def test_reactivates_canceled_subscription(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        from app.domain.subscription_operations import subscription_ops

        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_react_test",
                "stripe_subscription_id": "sub_react_123",
                "is_manually_assigned": False,
                "cancel_at_period_end": True,
            },
        )
        await db_session.flush()

        with (
            patch("app.api.v1.billing.settings") as mock_settings,
            patch("app.api.v1.billing.stripe_service") as mock_stripe,
        ):
            mock_settings.stripe_enabled = True
            mock_settings.frontend_url = "http://test"

            resp = await api_client.post(
                "/api/v1/billing/reactivate",
                json={"organization_id": str(test_org.id)},
            )

        assert resp.status_code == 200
        assert "reactivated" in resp.json()["message"].lower()

        # Verify the Stripe SDK was called
        mock_stripe.reactivate_subscription.assert_called_once_with("sub_react_123")

        # Verify local subscription updated
        await db_session.refresh(test_subscription)
        assert test_subscription.cancel_at_period_end is False


# ─────────────────────────────────────────────────────────────────────────────
# Downgrade flow
# ─────────────────────────────────────────────────────────────────────────────


class TestDowngradeFlow:
    """POST /billing/downgrade changes to a lower plan tier."""

    @pytest.mark.anyio
    async def test_downgrades_plan_tier(
        self,
        api_client: AsyncClient,
        test_org,
        test_subscription,
        db_session: AsyncSession,
    ):
        from app.domain.subscription_operations import subscription_ops

        # Start on pro (higher tier) so downgrade to indie is valid
        await subscription_ops.update(
            db_session,
            test_subscription,
            {
                "stripe_customer_id": "cus_down_test",
                "stripe_subscription_id": "sub_down_123",
                "is_manually_assigned": False,
                "plan_tier": "pro",
                "base_repo_limit": 10,
            },
        )
        await db_session.flush()

        with (
            patch("app.api.v1.billing.settings") as mock_settings,
            patch("app.api.v1.billing.stripe_service") as mock_stripe,
        ):
            mock_settings.stripe_enabled = True
            mock_settings.frontend_url = "http://test"

            resp = await api_client.post(
                "/api/v1/billing/downgrade",
                json={
                    "organization_id": str(test_org.id),
                    "target_plan_tier": "indie",
                    "repos_to_keep": [],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["deleted_repo_count"] == 0

        mock_stripe.change_subscription_plan.assert_called_once_with("sub_down_123", "indie")

        await db_session.refresh(test_subscription)
        assert test_subscription.plan_tier == "indie"
