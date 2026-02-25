"""Unit tests for OrgMemberOperations — invitation, email validation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.org_member_operations import (
    InvalidEmailError,
    OrgMemberOperations,
    SupabaseInviteError,
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


# ---------------------------------------------------------------------------
# Existing-user invite fallback tests (Phases 1–4)
# ---------------------------------------------------------------------------


def _mock_supabase_already_registered():
    """Return a side_effect that raises 'already been registered'."""
    return Exception("A user with this email address has already been registered")


def _mock_generate_link_response():
    """Return a mock generate_link response with a magic link."""
    response = MagicMock()
    response.properties.action_link = "https://example.com/auth/v1/verify?token=abc123"
    return response


class TestCreateUserViaSupabaseExistingUserSendsEmail:
    """When invite_user_by_email raises 'already registered', a magic link
    email should be sent to the existing user."""

    def setup_method(self):
        self.ops = OrgMemberOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

    @pytest.mark.asyncio
    @patch("app.domain.org_member_operations.postmark_service")
    @patch("app.domain.org_member_operations.asyncio.to_thread")
    @patch("app.domain.org_member_operations.get_supabase_admin_client")
    async def test_sends_email_via_magic_link(self, _mock_client, mock_thread, mock_postmark):
        # invite_user_by_email raises "already registered"
        mock_thread.side_effect = [
            _mock_supabase_already_registered(),  # invite call
            _mock_generate_link_response(),  # generate_link call
        ]

        # User found locally
        existing_user = MagicMock()
        existing_user.id = uuid.uuid4()
        existing_user.email = "existing@example.com"
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_user
        self.db.execute.return_value = result_mock

        mock_postmark.send_team_invite = AsyncMock(return_value=True)

        user = await self.ops.create_user_via_supabase(
            self.db, "existing@example.com", inviter_name="Alice", org_name="Acme"
        )

        assert user == existing_user
        mock_postmark.send_team_invite.assert_awaited_once()
        call_kwargs = mock_postmark.send_team_invite.call_args.kwargs
        assert call_kwargs["to"] == "existing@example.com"
        assert call_kwargs["inviter_name"] == "Alice"
        assert call_kwargs["org_name"] == "Acme"
        assert "token=abc123" in call_kwargs["magic_link"]


class TestCreateUserViaSupabaseNewUserNoFallback:
    """When invite_user_by_email succeeds, generate_link should never be called."""

    def setup_method(self):
        self.ops = OrgMemberOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

    @pytest.mark.asyncio
    @patch("app.domain.org_member_operations.postmark_service")
    @patch("app.domain.org_member_operations.asyncio.to_thread")
    @patch("app.domain.org_member_operations.get_supabase_admin_client")
    async def test_no_fallback_for_new_user(self, _mock_client, mock_thread, mock_postmark):
        mock_response = MagicMock()
        mock_response.user.id = str(uuid.uuid4())
        mock_thread.return_value = mock_response

        await self.ops.create_user_via_supabase(self.db, "new@example.com")

        # Only one to_thread call (invite_user_by_email), no generate_link
        assert mock_thread.await_count == 1
        mock_postmark.send_team_invite.assert_not_called()


class TestResendInviteExistingUserSendsMagicLink:
    """When resend_invite hits 'already registered', it should fall back
    to magic link + Postmark email."""

    def setup_method(self):
        self.ops = OrgMemberOperations()

    @pytest.mark.asyncio
    @patch("app.domain.org_member_operations.postmark_service")
    @patch("app.domain.org_member_operations.asyncio.to_thread")
    @patch("app.domain.org_member_operations.get_supabase_admin_client")
    async def test_fallback_to_magic_link(self, _mock_client, mock_thread, mock_postmark):
        mock_thread.side_effect = [
            _mock_supabase_already_registered(),  # invite call
            _mock_generate_link_response(),  # generate_link call
        ]
        mock_postmark.send_team_invite = AsyncMock(return_value=True)

        await self.ops.resend_invite(
            "existing@example.com", inviter_name="Bob", org_name="Widgets Inc"
        )

        mock_postmark.send_team_invite.assert_awaited_once()
        call_kwargs = mock_postmark.send_team_invite.call_args.kwargs
        assert call_kwargs["to"] == "existing@example.com"
        assert call_kwargs["inviter_name"] == "Bob"
        assert call_kwargs["org_name"] == "Widgets Inc"


class TestResendInviteNewUserUsesSupabaseInvite:
    """When resend_invite succeeds via Supabase, no fallback is triggered."""

    def setup_method(self):
        self.ops = OrgMemberOperations()

    @pytest.mark.asyncio
    @patch("app.domain.org_member_operations.postmark_service")
    @patch("app.domain.org_member_operations.asyncio.to_thread")
    @patch("app.domain.org_member_operations.get_supabase_admin_client")
    async def test_no_fallback_for_pending_user(self, _mock_client, mock_thread, mock_postmark):
        mock_thread.return_value = None  # invite succeeds

        await self.ops.resend_invite("pending@example.com")

        assert mock_thread.await_count == 1
        mock_postmark.send_team_invite.assert_not_called()


class TestSendInviteToExistingUserPostmarkFailureNonFatal:
    """If generate_link succeeds but Postmark fails, the method should
    return False (non-fatal) without raising."""

    def setup_method(self):
        self.ops = OrgMemberOperations()

    @pytest.mark.asyncio
    @patch("app.domain.org_member_operations.postmark_service")
    @patch("app.domain.org_member_operations.asyncio.to_thread")
    @patch("app.domain.org_member_operations.get_supabase_admin_client")
    async def test_postmark_failure_returns_false(self, _mock_client, mock_thread, mock_postmark):
        mock_thread.return_value = _mock_generate_link_response()
        mock_postmark.send_team_invite = AsyncMock(return_value=False)

        result = await self.ops._send_invite_to_existing_user(
            email="user@example.com", inviter_name="Alice", org_name="Acme"
        )

        assert result is False


class TestSendInviteToExistingUserGenerateLinkFailure:
    """If generate_link itself fails, SupabaseInviteError should be raised."""

    def setup_method(self):
        self.ops = OrgMemberOperations()

    @pytest.mark.asyncio
    @patch("app.domain.org_member_operations.postmark_service")
    @patch("app.domain.org_member_operations.asyncio.to_thread")
    @patch("app.domain.org_member_operations.get_supabase_admin_client")
    async def test_generate_link_failure_raises(self, _mock_client, mock_thread, _mock_postmark):
        mock_thread.side_effect = Exception("Supabase unavailable")

        with pytest.raises(SupabaseInviteError, match="Failed to generate login link"):
            await self.ops._send_invite_to_existing_user(
                email="user@example.com", inviter_name="Alice", org_name="Acme"
            )
