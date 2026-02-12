"""Unit tests for ReferralOperations — code generation, redemption, validation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.referral_operations import ReferralOperations, generate_referral_code

from tests.helpers.mock_factories import (
    make_mock_referral_code,
    make_mock_user,
    mock_scalar_result,
)


class TestGenerateReferralCode:
    """Pure logic tests for referral code generation."""

    def test_uses_first_name(self):
        code = generate_referral_code("Sarah Connor", "sarah@test.com")
        assert code.startswith("SARAH-")
        assert len(code.split("-")[1]) == 4

    def test_uses_email_when_no_name(self):
        code = generate_referral_code(None, "jane@example.com")
        assert code.startswith("JANE-")

    def test_fallback_to_trajan_when_nothing(self):
        code = generate_referral_code(None, None)
        assert code.startswith("TRAJAN-")

    def test_short_name_fallback(self):
        # Single char name → too short → fallback to TRAJAN
        code = generate_referral_code("X", None)
        assert code.startswith("TRAJAN-")

    def test_code_format_name_dash_4chars(self):
        code = generate_referral_code("Alice", "alice@test.com")
        parts = code.split("-")
        assert len(parts) == 2
        assert len(parts[1]) == 4
        # Suffix should only contain safe chars
        safe_chars = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        assert all(c in safe_chars for c in parts[1])

    def test_truncates_long_names(self):
        code = generate_referral_code("Bartholomew", None)
        name_part = code.split("-")[0]
        assert len(name_part) <= 6  # Max 6 chars


class TestRedeemCode:
    """Tests for referral code redemption logic."""

    def setup_method(self):
        self.ops = ReferralOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()
        self.recipient_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch.object(ReferralOperations, "get_by_code")
    async def test_raises_for_invalid_code(self, mock_get):
        mock_get.return_value = None
        with pytest.raises(ValueError, match="Invalid referral code"):
            await self.ops.redeem_code(self.db, "FAKE-CODE", self.recipient_id)

    @pytest.mark.asyncio
    @patch.object(ReferralOperations, "get_by_code")
    async def test_raises_for_already_used_code(self, mock_get):
        code = make_mock_referral_code(is_available=False)
        mock_get.return_value = code
        with pytest.raises(ValueError, match="already used"):
            await self.ops.redeem_code(self.db, code.code, self.recipient_id)

    @pytest.mark.asyncio
    @patch.object(ReferralOperations, "get_by_code")
    async def test_raises_for_self_referral(self, mock_get):
        owner_id = uuid.uuid4()
        code = make_mock_referral_code(user_id=owner_id, is_available=True)
        mock_get.return_value = code
        with pytest.raises(ValueError, match="Cannot redeem your own"):
            await self.ops.redeem_code(self.db, code.code, owner_id)

    @pytest.mark.asyncio
    @patch.object(ReferralOperations, "get_by_code")
    async def test_raises_for_already_redeemed_by_user(self, mock_get):
        code = make_mock_referral_code(is_available=True)
        mock_get.return_value = code

        # Simulate the user already having redeemed a different code
        existing_referral = make_mock_referral_code()
        self.db.execute.return_value = mock_scalar_result(existing_referral)

        with pytest.raises(ValueError, match="already redeemed"):
            await self.ops.redeem_code(self.db, code.code, self.recipient_id)

    @pytest.mark.asyncio
    @patch.object(ReferralOperations, "get_by_code")
    async def test_successful_redemption(self, mock_get):
        code = make_mock_referral_code(is_available=True)
        mock_get.return_value = code

        # No existing redemption
        self.db.execute.return_value = mock_scalar_result(None)
        self.db.refresh = AsyncMock()

        result = await self.ops.redeem_code(self.db, code.code, self.recipient_id)
        assert result.redeemed_by_user_id == self.recipient_id


class TestCreateCode:
    """Tests for referral code creation."""

    def setup_method(self):
        self.ops = ReferralOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()
        self.user_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch.object(ReferralOperations, "get_remaining_invites")
    async def test_raises_no_remaining_invites(self, mock_remaining):
        mock_remaining.return_value = 0
        with pytest.raises(ValueError, match="No remaining"):
            await self.ops.create_code(self.db, self.user_id)

    @pytest.mark.asyncio
    @patch.object(ReferralOperations, "get_by_code")
    @patch.object(ReferralOperations, "get_remaining_invites")
    async def test_creates_code_successfully(self, mock_remaining, mock_get_by_code):
        mock_remaining.return_value = 3

        # Mock user query
        user = make_mock_user(id=self.user_id, display_name="Alice")
        self.db.execute.return_value = mock_scalar_result(user)
        self.db.refresh = AsyncMock()

        # No collision
        mock_get_by_code.return_value = None

        result = await self.ops.create_code(self.db, self.user_id)
        # Verify db.add was called with a ReferralCode
        self.db.add.assert_called_once()
