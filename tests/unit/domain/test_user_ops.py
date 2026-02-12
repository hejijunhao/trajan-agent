"""Unit tests for UserOperations — account deletion cascade."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.user_operations import (
    BasicOrgInfo,
    DeletionPreviewResult,
    OrgDeletionPreview,
    UserOperations,
)

from tests.helpers.mock_factories import make_mock_organization, make_mock_user


def _make_preview(
    sole_member_orgs: int = 0,
    multi_member_orgs: int = 0,
) -> DeletionPreviewResult:
    """Build a DeletionPreviewResult for testing."""
    owned = []
    for i in range(sole_member_orgs):
        owned.append(
            OrgDeletionPreview(
                org_id=uuid.uuid4(),
                org_name=f"Sole Org {i}",
                is_sole_member=True,
                member_count=1,
                other_members=[],
                product_count=2,
                work_item_count=5,
                document_count=3,
                has_active_subscription=False,
            )
        )
    for i in range(multi_member_orgs):
        owned.append(
            OrgDeletionPreview(
                org_id=uuid.uuid4(),
                org_name=f"Multi Org {i}",
                is_sole_member=False,
                member_count=3,
                other_members=[],
                product_count=4,
                work_item_count=10,
                document_count=6,
                has_active_subscription=True,
            )
        )
    return DeletionPreviewResult(
        owned_orgs=owned,
        member_only_orgs=[],
        total_products_affected=sum(o.product_count for o in owned if o.is_sole_member),
        total_work_items_affected=sum(o.work_item_count for o in owned if o.is_sole_member),
        total_documents_affected=sum(o.document_count for o in owned if o.is_sole_member),
    )


class TestDeleteWithCascade:
    """Tests for validated user deletion."""

    def setup_method(self):
        self.ops = UserOperations()
        self.db = AsyncMock()
        self.user_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch.object(UserOperations, "_delete_supabase_auth_user")
    @patch.object(UserOperations, "get_by_id")
    @patch.object(UserOperations, "get_deletion_preview")
    @patch("app.domain.organization_operations.organization_ops")
    async def test_successful_deletion_sole_member(
        self, mock_org_ops, mock_preview, mock_get_user, mock_supabase
    ):
        preview = _make_preview(sole_member_orgs=1)
        mock_preview.return_value = preview
        mock_get_user.return_value = make_mock_user(id=self.user_id)
        mock_org_ops.delete = AsyncMock()
        mock_supabase.return_value = True

        sole_org_id = preview.owned_orgs[0].org_id
        success, errors = await self.ops.delete_with_cascade(
            self.db, self.user_id, [sole_org_id]
        )
        assert success is True
        assert errors == []

    @pytest.mark.asyncio
    @patch.object(UserOperations, "get_deletion_preview")
    @patch("app.domain.organization_operations.organization_ops")
    async def test_raises_if_multi_member_org_not_transferred(
        self, mock_org_ops, mock_preview
    ):
        preview = _make_preview(multi_member_orgs=1)
        mock_preview.return_value = preview
        # Simulate org still owned by user
        mock_org = make_mock_organization(owner_id=self.user_id)
        mock_org_ops.get = AsyncMock(return_value=mock_org)

        with pytest.raises(ValueError, match="Must transfer ownership"):
            await self.ops.delete_with_cascade(self.db, self.user_id, [])

    @pytest.mark.asyncio
    @patch.object(UserOperations, "get_deletion_preview")
    async def test_raises_if_sole_member_org_missing_from_list(self, mock_preview):
        preview = _make_preview(sole_member_orgs=1)
        mock_preview.return_value = preview

        with pytest.raises(ValueError, match="sole-member"):
            await self.ops.delete_with_cascade(self.db, self.user_id, [])

    @pytest.mark.asyncio
    @patch.object(UserOperations, "get_deletion_preview")
    async def test_raises_if_extra_orgs_not_sole_member(self, mock_preview):
        preview = _make_preview(sole_member_orgs=0)
        mock_preview.return_value = preview

        with pytest.raises(ValueError, match="Cannot delete organizations"):
            await self.ops.delete_with_cascade(
                self.db, self.user_id, [uuid.uuid4()]
            )


class TestDeleteSupabaseAuthUser:
    """Tests for Supabase auth cleanup."""

    def setup_method(self):
        self.ops = UserOperations()

    @pytest.mark.asyncio
    @patch("app.services.supabase.get_supabase_admin_client")
    async def test_returns_true_on_success(self, mock_client):
        mock_supabase = MagicMock()
        mock_client.return_value = mock_supabase

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = None
            result = await self.ops._delete_supabase_auth_user(uuid.uuid4())
            assert result is True

    @pytest.mark.asyncio
    @patch("app.services.supabase.get_supabase_admin_client")
    async def test_returns_false_on_service_key_missing(self, mock_client):
        mock_client.side_effect = ValueError("No service key")

        result = await self.ops._delete_supabase_auth_user(uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    @patch("app.services.supabase.get_supabase_admin_client")
    async def test_returns_true_on_user_not_found(self, mock_client):
        mock_supabase = MagicMock()
        mock_client.return_value = mock_supabase

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.side_effect = Exception("User not found")
            result = await self.ops._delete_supabase_auth_user(uuid.uuid4())
            assert result is True
