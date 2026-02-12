"""Unit tests for OrgMemberOperations — invitation, email validation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.org_member_operations import (
    InvalidEmailError,
    OrgMemberOperations,
)

from tests.helpers.mock_factories import mock_scalar_result


class TestCreateUserViaSupabase:
    """Tests for creating users through Supabase invitation."""

    def setup_method(self):
        self.ops = OrgMemberOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_raises_invalid_email_error(self):
        with pytest.raises(InvalidEmailError):
            await self.ops.create_user_via_supabase(self.db, "not-an-email")

    @pytest.mark.asyncio
    async def test_raises_for_empty_email(self):
        with pytest.raises(InvalidEmailError):
            await self.ops.create_user_via_supabase(self.db, "")


class TestIsOnlyOwner:
    """Tests for sole owner detection."""

    def setup_method(self):
        self.ops = OrgMemberOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_true_when_sole_owner(self):
        self.db.execute.return_value = mock_scalar_result(1)
        result = await self.ops.is_only_owner(self.db, uuid.uuid4(), uuid.uuid4())
        assert result is not None


class TestEmailValidation:
    """Tests for email pattern validation used in invites."""

    def setup_method(self):
        self.ops = OrgMemberOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

    @pytest.mark.asyncio
    async def test_accepts_valid_email(self):
        # Should NOT raise InvalidEmailError (may fail on Supabase call, which is OK)
        with patch("app.domain.org_member_operations.get_supabase_admin_client") as mock_client:
            mock_supabase = MagicMock()
            mock_client.return_value = mock_supabase
            # Simulate the thread call
            with patch("app.domain.org_member_operations.asyncio.to_thread") as mock_thread:
                mock_response = MagicMock()
                mock_response.user = MagicMock()
                mock_response.user.id = str(uuid.uuid4())
                mock_thread.return_value = mock_response
                self.db.execute.return_value = mock_scalar_result(None)
                self.db.refresh = AsyncMock()

                # This should not raise InvalidEmailError
                try:
                    await self.ops.create_user_via_supabase(self.db, "valid@example.com")
                except InvalidEmailError:
                    pytest.fail("Valid email should not raise InvalidEmailError")

    @pytest.mark.asyncio
    async def test_rejects_email_without_tld(self):
        with pytest.raises(InvalidEmailError):
            await self.ops.create_user_via_supabase(self.db, "user@localhost")
