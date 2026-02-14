"""Unit tests for StripeService — payment integration."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.stripe_service import StripeService

from tests.helpers.mock_factories import make_mock_organization, make_mock_user


class TestGetPriceId:
    """Tests for tier → price ID mapping."""

    @patch("app.services.stripe_service.settings")
    def test_returns_indie_price(self, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"
        assert StripeService.get_price_id("indie") == "price_indie_123"

    @patch("app.services.stripe_service.settings")
    def test_returns_pro_price(self, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"
        assert StripeService.get_price_id("pro") == "price_pro_456"

    @patch("app.services.stripe_service.settings")
    def test_returns_empty_for_unknown(self, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"
        assert StripeService.get_price_id("unknown") == ""


class TestCreateCustomer:
    """Tests for Stripe customer creation."""

    @patch("app.services.stripe_service.stripe")
    def test_creates_customer_with_metadata(self, mock_stripe):
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_test_123")
        org = make_mock_organization(name="Test Org")
        user = make_mock_user(email="test@example.com")

        result = StripeService.create_customer(org, user)

        assert result == "cus_test_123"
        mock_stripe.Customer.create.assert_called_once()
        call_kwargs = mock_stripe.Customer.create.call_args[1]
        assert call_kwargs["email"] == "test@example.com"
        assert call_kwargs["name"] == "Test Org"
        assert "organization_id" in call_kwargs["metadata"]

    @patch("app.services.stripe_service.stripe")
    def test_raises_on_stripe_error(self, mock_stripe):
        from stripe import StripeError

        mock_stripe.Customer.create.side_effect = StripeError("API error")
        org = make_mock_organization()
        user = make_mock_user()

        with pytest.raises(StripeError):
            StripeService.create_customer(org, user)


class TestCreateCheckoutSession:
    """Tests for Stripe checkout session creation."""

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_creates_session_with_trial(self, mock_stripe, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"
        mock_settings.stripe_price_repo_overage = None

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test_session"
        mock_stripe.checkout.Session.create.return_value = mock_session

        result = StripeService.create_checkout_session(
            "cus_123", "indie", "https://app.com/success", "https://app.com/cancel"
        )

        assert result == "https://checkout.stripe.com/test_session"
        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        assert call_kwargs["customer"] == "cus_123"
        assert call_kwargs["subscription_data"]["trial_period_days"] == 14

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_creates_session_without_trial(self, mock_stripe, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"
        mock_settings.stripe_price_repo_overage = None

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test_session"
        mock_stripe.checkout.Session.create.return_value = mock_session

        result = StripeService.create_checkout_session(
            "cus_123", "indie", "https://app.com/success", "https://app.com/cancel",
            include_trial=False,
        )

        assert result == "https://checkout.stripe.com/test_session"
        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        assert "trial_period_days" not in call_kwargs["subscription_data"]

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_raises_for_unknown_tier(self, mock_stripe, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"

        with pytest.raises(ValueError, match="No base price"):
            StripeService.create_checkout_session(
                "cus_123", "nonexistent", "http://success", "http://cancel"
            )


class TestCreatePortalSession:
    """Tests for Stripe Customer Portal session creation."""

    @patch("app.services.stripe_service.stripe")
    def test_returns_portal_url(self, mock_stripe):
        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/portal/sess_abc"
        mock_stripe.billing_portal.Session.create.return_value = mock_session

        result = StripeService.create_portal_session("cus_123", "https://app.com/billing")

        assert result == "https://billing.stripe.com/portal/sess_abc"
        mock_stripe.billing_portal.Session.create.assert_called_once_with(
            customer="cus_123",
            return_url="https://app.com/billing",
        )


class TestCancelSubscription:
    """Tests for subscription cancellation at period end."""

    @patch("app.services.stripe_service.stripe")
    def test_sets_cancel_at_period_end(self, mock_stripe):
        StripeService.cancel_subscription("sub_test_456")

        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_test_456",
            cancel_at_period_end=True,
        )

    @patch("app.services.stripe_service.stripe")
    def test_raises_on_stripe_error(self, mock_stripe):
        from stripe import StripeError

        mock_stripe.Subscription.modify.side_effect = StripeError("API error")

        with pytest.raises(StripeError):
            StripeService.cancel_subscription("sub_test_456")


class TestReactivateSubscription:
    """Tests for undoing a pending cancellation."""

    @patch("app.services.stripe_service.stripe")
    def test_clears_cancel_at_period_end(self, mock_stripe):
        StripeService.reactivate_subscription("sub_test_789")

        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_test_789",
            cancel_at_period_end=False,
        )


class TestChangeSubscriptionPlan:
    """Tests for upgrading/downgrading between plan tiers."""

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_updates_base_item_price(self, mock_stripe, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"

        # Simulate subscription with a base item (quantity=1)
        mock_sub = {
            "items": {
                "data": [
                    {"id": "si_base_item", "quantity": 1, "price": {"id": "price_indie_123"}},
                    {"id": "si_metered_item", "quantity": None},
                ]
            }
        }
        mock_stripe.Subscription.retrieve.return_value = mock_sub

        StripeService.change_subscription_plan("sub_test", "pro")

        call_kwargs = mock_stripe.Subscription.modify.call_args[1]
        assert call_kwargs["items"] == [{"id": "si_base_item", "price": "price_pro_456"}]
        assert call_kwargs["proration_behavior"] == "create_prorations"

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_raises_when_no_base_item_found(self, mock_stripe, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"

        # Subscription with only metered items (no quantity=1)
        mock_sub = {"items": {"data": [{"id": "si_metered", "quantity": None}]}}
        mock_stripe.Subscription.retrieve.return_value = mock_sub

        with pytest.raises(ValueError, match="Could not find base subscription item"):
            StripeService.change_subscription_plan("sub_test", "pro")

    @patch("app.services.stripe_service.settings")
    def test_raises_for_unknown_tier(self, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"

        with pytest.raises(ValueError, match="No price configured"):
            StripeService.change_subscription_plan("sub_test", "enterprise")


class TestGetSubscription:
    """Tests for retrieving a Stripe subscription."""

    @patch("app.services.stripe_service.stripe")
    def test_returns_subscription_dict(self, mock_stripe):
        mock_stripe.Subscription.retrieve.return_value = MagicMock(
            __iter__=lambda self: iter([("id", "sub_123"), ("status", "active")]),
        )

        result = StripeService.get_subscription("sub_123")

        assert result is not None
        mock_stripe.Subscription.retrieve.assert_called_once_with("sub_123")

    @patch("app.services.stripe_service.stripe")
    def test_returns_none_on_stripe_error(self, mock_stripe):
        from stripe import StripeError

        mock_stripe.Subscription.retrieve.side_effect = StripeError("Not found")

        result = StripeService.get_subscription("sub_invalid")

        assert result is None


class TestConstructWebhookEvent:
    """Tests for webhook signature verification."""

    @patch("app.services.stripe_service.stripe")
    @patch("app.services.stripe_service.settings")
    def test_raises_on_invalid_signature(self, mock_settings, mock_stripe):
        from stripe import SignatureVerificationError

        mock_settings.stripe_webhook_secret = "whsec_test"
        mock_stripe.Webhook.construct_event.side_effect = SignatureVerificationError(
            "bad sig", "sig_header"
        )
        # Re-attach the error module so the except clause can catch it
        mock_stripe.error.SignatureVerificationError = SignatureVerificationError

        with pytest.raises(ValueError, match="Invalid webhook signature"):
            StripeService.construct_webhook_event(b"payload", "bad_sig")
