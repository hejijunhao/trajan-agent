"""Unit tests for ProductAccessOperations — access control logic."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.product_access_operations import ProductAccessOperations

from tests.helpers.mock_factories import mock_scalar_result, mock_scalars_result


class TestComputeEffectiveAccess:
    """Pure logic tests — no mocking required."""

    def setup_method(self):
        self.ops = ProductAccessOperations()

    def test_owner_gets_admin_access(self):
        assert self.ops._compute_effective_access("owner", None) == "admin"

    def test_admin_gets_admin_access(self):
        assert self.ops._compute_effective_access("admin", None) == "admin"

    def test_owner_ignores_explicit_access(self):
        assert self.ops._compute_effective_access("owner", "viewer") == "admin"

    def test_member_with_explicit_editor_gets_editor(self):
        assert self.ops._compute_effective_access("member", "editor") == "editor"

    def test_member_with_explicit_viewer_gets_viewer(self):
        assert self.ops._compute_effective_access("member", "viewer") == "viewer"

    def test_member_with_explicit_none_gets_none(self):
        assert self.ops._compute_effective_access("member", "none") == "none"

    def test_member_with_no_explicit_access_gets_none(self):
        assert self.ops._compute_effective_access("member", None) == "none"

    def test_viewer_with_no_explicit_access_gets_none(self):
        assert self.ops._compute_effective_access("viewer", None) == "none"


class TestGetEffectiveAccessBulk:
    """DB-mocked tests for bulk access resolution."""

    def setup_method(self):
        self.ops = ProductAccessOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_empty_product_ids_returns_empty_dict(self):
        result = await self.ops.get_effective_access_bulk(self.db, [], uuid.uuid4(), "member")
        assert result == {}

    @pytest.mark.asyncio
    async def test_owner_fast_path_returns_admin_for_all(self):
        pids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        result = await self.ops.get_effective_access_bulk(self.db, pids, uuid.uuid4(), "owner")
        assert all(v == "admin" for v in result.values())
        assert len(result) == 3
        # DB should NOT be queried for owners
        self.db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_member_gets_mixed_access_levels(self):
        pid1, pid2, pid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        user_id = uuid.uuid4()

        # Simulate DB returning explicit access for pid1 and pid2
        mock_pa1 = MagicMock()
        mock_pa1.product_id = pid1
        mock_pa1.access_level = "editor"
        mock_pa2 = MagicMock()
        mock_pa2.product_id = pid2
        mock_pa2.access_level = "viewer"

        self.db.execute.return_value = mock_scalars_result([mock_pa1, mock_pa2])

        result = await self.ops.get_effective_access_bulk(
            self.db, [pid1, pid2, pid3], user_id, "member"
        )
        assert result[pid1] == "editor"
        assert result[pid2] == "viewer"
        assert result[pid3] == "none"  # No explicit access


class TestUserCanAccessProduct:
    """Tests for access predicate methods."""

    def setup_method(self):
        self.ops = ProductAccessOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    @patch.object(ProductAccessOperations, "get_effective_access")
    async def test_admin_access_returns_true(self, mock_get):
        mock_get.return_value = "admin"
        result = await self.ops.user_can_access_product(
            self.db, uuid.uuid4(), uuid.uuid4(), "owner"
        )
        assert result is True

    @pytest.mark.asyncio
    @patch.object(ProductAccessOperations, "get_effective_access")
    async def test_none_access_returns_false(self, mock_get):
        mock_get.return_value = "none"
        result = await self.ops.user_can_access_product(
            self.db, uuid.uuid4(), uuid.uuid4(), "member"
        )
        assert result is False
