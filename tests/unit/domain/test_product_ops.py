"""Unit tests for ProductOperations and RepositoryOperations — thin domain logic."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.product_operations import ProductOperations

from tests.helpers.mock_factories import make_mock_product


class TestEnableQuickAccess:
    """Tests for quick access token generation."""

    def setup_method(self):
        self.ops = ProductOperations()
        self.db = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()
        self.user_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch("app.domain.product_operations.generate_quick_access_token")
    async def test_generates_token_when_none_exists(self, mock_gen):
        mock_gen.return_value = "new_token_abc"
        product = make_mock_product(quick_access_token=None)
        product.quick_access_token = None

        result = await self.ops.enable_quick_access(self.db, product, self.user_id)
        assert result.quick_access_token == "new_token_abc"
        assert result.quick_access_enabled is True

    @pytest.mark.asyncio
    async def test_preserves_existing_token(self):
        product = make_mock_product()
        product.quick_access_token = "existing_token"

        result = await self.ops.enable_quick_access(self.db, product, self.user_id)
        assert result.quick_access_token == "existing_token"
        assert result.quick_access_enabled is True


class TestDisableQuickAccess:
    """Tests for quick access disabling."""

    def setup_method(self):
        self.ops = ProductOperations()
        self.db = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

    @pytest.mark.asyncio
    async def test_disables_without_removing_token(self):
        product = make_mock_product()
        product.quick_access_token = "keep_this"

        result = await self.ops.disable_quick_access(self.db, product)
        assert result.quick_access_enabled is False
        assert result.quick_access_token == "keep_this"
