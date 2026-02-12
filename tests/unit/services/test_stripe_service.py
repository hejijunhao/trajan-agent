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
    def test_raises_for_unknown_tier(self, mock_stripe, mock_settings):
        mock_settings.stripe_price_indie_base = "price_indie_123"
        mock_settings.stripe_price_pro_base = "price_pro_456"
        mock_settings.stripe_price_scale_base = "price_scale_789"

        with pytest.raises(ValueError, match="No base price"):
            StripeService.create_checkout_session(
                "cus_123", "nonexistent", "http://success", "http://cancel"
            )


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
