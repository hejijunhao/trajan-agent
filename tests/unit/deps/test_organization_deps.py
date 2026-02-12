"""Unit tests for organization access control dependencies."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.deps.organization import require_org_admin, require_org_owner, require_system_admin

from tests.helpers.mock_factories import make_mock_organization, make_mock_user


class TestRequireOrgAdmin:
    """Tests for require_org_admin dependency."""

    @pytest.mark.asyncio
    @patch("app.api.deps.organization.organization_ops")
    async def test_allows_owner(self, mock_ops):
        mock_ops.get_member_role = AsyncMock(return_value="owner")
        user = make_mock_user()
        org = make_mock_organization()
        db = AsyncMock()

        result = await require_org_admin(user, org, db)
        assert result is org

    @pytest.mark.asyncio
    @patch("app.api.deps.organization.organization_ops")
    async def test_allows_admin(self, mock_ops):
        mock_ops.get_member_role = AsyncMock(return_value="admin")
        user = make_mock_user()
        org = make_mock_organization()
        db = AsyncMock()

        result = await require_org_admin(user, org, db)
        assert result is org

    @pytest.mark.asyncio
    @patch("app.api.deps.organization.organization_ops")
    async def test_raises_403_for_member(self, mock_ops):
        mock_ops.get_member_role = AsyncMock(return_value="member")
        user = make_mock_user()
        org = make_mock_organization()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await require_org_admin(user, org, db)
        assert exc_info.value.status_code == 403


class TestRequireOrgOwner:
    """Tests for require_org_owner dependency."""

    @pytest.mark.asyncio
    @patch("app.api.deps.organization.organization_ops")
    async def test_raises_403_for_admin(self, mock_ops):
        mock_ops.get_member_role = AsyncMock(return_value="admin")
        user = make_mock_user()
        org = make_mock_organization()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await require_org_owner(user, org, db)
        assert exc_info.value.status_code == 403


class TestRequireSystemAdmin:
    """Tests for require_system_admin dependency."""

    @pytest.mark.asyncio
    async def test_allows_system_admin(self):
        user = make_mock_user(is_admin=True)
        result = await require_system_admin(user)
        assert result is user

    @pytest.mark.asyncio
    async def test_raises_403_for_non_admin(self):
        user = make_mock_user(is_admin=False)
        with pytest.raises(HTTPException) as exc_info:
            await require_system_admin(user)
        assert exc_info.value.status_code == 403
