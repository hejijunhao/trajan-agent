"""Unit tests for product access dependency functions."""

import uuid

import pytest
from fastapi import HTTPException

from app.api.deps.product_access import (
    ProductAccessContext,
    require_product_admin,
    require_product_editor,
    require_variables_access,
)


def _make_ctx(access_level: str = "admin") -> ProductAccessContext:
    """Helper to build a ProductAccessContext for testing."""
    return ProductAccessContext(
        product_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        access_level=access_level,
    )


class TestRequireProductEditor:
    """Tests for require_product_editor dependency."""

    @pytest.mark.asyncio
    async def test_allows_admin_access(self):
        ctx = _make_ctx("admin")
        result = await require_product_editor(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_allows_editor_access(self):
        ctx = _make_ctx("editor")
        result = await require_product_editor(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_raises_403_for_viewer(self):
        ctx = _make_ctx("viewer")
        with pytest.raises(HTTPException) as exc_info:
            await require_product_editor(ctx)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_403_for_none(self):
        ctx = _make_ctx("none")
        with pytest.raises(HTTPException) as exc_info:
            await require_product_editor(ctx)
        assert exc_info.value.status_code == 403


class TestRequireProductAdmin:
    """Tests for require_product_admin dependency."""

    @pytest.mark.asyncio
    async def test_allows_admin_access(self):
        ctx = _make_ctx("admin")
        result = await require_product_admin(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_raises_403_for_editor(self):
        ctx = _make_ctx("editor")
        with pytest.raises(HTTPException) as exc_info:
            await require_product_admin(ctx)
        assert exc_info.value.status_code == 403


class TestRequireVariablesAccess:
    """Tests for require_variables_access dependency."""

    @pytest.mark.asyncio
    async def test_allows_editor_access(self):
        ctx = _make_ctx("editor")
        result = await require_variables_access(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_raises_403_for_viewer(self):
        ctx = _make_ctx("viewer")
        with pytest.raises(HTTPException) as exc_info:
            await require_variables_access(ctx)
        assert exc_info.value.status_code == 403
        assert "environment variables" in str(exc_info.value.detail).lower()
