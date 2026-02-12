"""Unit tests for OrganizationOperations — org creation, settings, and ownership."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.organization_operations import OrganizationOperations, generate_slug

from tests.helpers.mock_factories import (
    make_mock_organization,
    make_mock_org_member,
    make_mock_user,
    mock_scalar_result,
)


class TestGenerateSlug:
    """Pure logic tests for slug generation."""

    def test_generates_slug_from_name(self):
        slug = generate_slug("My Cool Project")
        assert slug.startswith("my-cool-project-")
        assert len(slug) > len("my-cool-project-")

    def test_strips_special_characters(self):
        slug = generate_slug("Hello! World? #42")
        # Special chars become hyphens, leading/trailing stripped
        assert slug.startswith("hello-world-42-")

    def test_adds_random_suffix(self):
        slug1 = generate_slug("Test")
        slug2 = generate_slug("Test")
        # Same name should produce different slugs (random suffix)
        assert slug1 != slug2

    def test_handles_empty_string_gracefully(self):
        slug = generate_slug("")
        # Empty name → just suffix
        assert len(slug) >= 6  # At least the hex suffix


class TestOrganizationCreate:
    """Tests for organization creation (creates org + member + subscription)."""

    def setup_method(self):
        self.ops = OrganizationOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()
        self.user_id = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_creates_org_member_and_subscription(self):
        # get_by_slug returns None (no collision)
        self.db.execute.return_value = mock_scalar_result(None)
        self.db.refresh = AsyncMock()

        org = await self.ops.create(self.db, name="Test Org", owner_id=self.user_id)

        # Should have called db.add 3 times: org, member, subscription
        assert self.db.add.call_count == 3
        # First add should be the org
        added_org = self.db.add.call_args_list[0][0][0]
        assert added_org.name == "Test Org"
        assert added_org.owner_id == self.user_id

    @pytest.mark.asyncio
    async def test_regenerates_slug_on_collision(self):
        # First get_by_slug returns existing org (collision), then None
        existing_org = make_mock_organization()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_scalar_result(existing_org)
            return mock_scalar_result(None)

        self.db.execute = mock_execute
        self.db.refresh = AsyncMock()

        org = await self.ops.create(self.db, name="Test Org", owner_id=self.user_id)
        assert org is not None


class TestCreatePersonalOrg:
    """Tests for personal org creation during signup."""

    def setup_method(self):
        self.ops = OrganizationOperations()
        self.db = AsyncMock()
        self.user_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch.object(OrganizationOperations, "create")
    async def test_uses_display_name(self, mock_create):
        mock_create.return_value = make_mock_organization()
        await self.ops.create_personal_org(
            self.db, self.user_id, user_name="Sarah", user_email="sarah@test.com"
        )
        mock_create.assert_called_once_with(
            self.db, name="Sarah's Workspace", owner_id=self.user_id
        )

    @pytest.mark.asyncio
    @patch.object(OrganizationOperations, "create")
    async def test_falls_back_to_email_prefix(self, mock_create):
        mock_create.return_value = make_mock_organization()
        await self.ops.create_personal_org(
            self.db, self.user_id, user_name=None, user_email="jane@example.com"
        )
        mock_create.assert_called_once_with(
            self.db, name="jane's Workspace", owner_id=self.user_id
        )

    @pytest.mark.asyncio
    @patch.object(OrganizationOperations, "create")
    async def test_falls_back_to_my_workspace(self, mock_create):
        mock_create.return_value = make_mock_organization()
        await self.ops.create_personal_org(
            self.db, self.user_id, user_name=None, user_email=None
        )
        mock_create.assert_called_once_with(
            self.db, name="My Workspace", owner_id=self.user_id
        )


class TestTransferOwnership:
    """Tests for ownership transfer validation."""

    def setup_method(self):
        self.ops = OrganizationOperations()
        self.db = AsyncMock()
        self.owner_id = uuid.uuid4()
        self.new_owner_id = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_raises_if_org_not_found(self):
        self.db.execute.return_value = mock_scalar_result(None)
        with pytest.raises(ValueError, match="Organization not found"):
            await self.ops.transfer_ownership(
                self.db, uuid.uuid4(), self.owner_id, self.new_owner_id
            )

    @pytest.mark.asyncio
    async def test_raises_if_not_current_owner(self):
        org = make_mock_organization(owner_id=uuid.uuid4())  # Different owner
        self.db.execute.return_value = mock_scalar_result(org)
        with pytest.raises(ValueError, match="Only the owner"):
            await self.ops.transfer_ownership(
                self.db, org.id, self.owner_id, self.new_owner_id
            )

    @pytest.mark.asyncio
    async def test_raises_if_transfer_to_self(self):
        org = make_mock_organization(owner_id=self.owner_id)
        self.db.execute.return_value = mock_scalar_result(org)
        with pytest.raises(ValueError, match="Cannot transfer ownership to yourself"):
            await self.ops.transfer_ownership(
                self.db, org.id, self.owner_id, self.owner_id
            )

    @pytest.mark.asyncio
    @patch.object(OrganizationOperations, "get_member")
    @patch.object(OrganizationOperations, "get")
    async def test_raises_if_target_not_member(self, mock_get, mock_get_member):
        org = make_mock_organization(owner_id=self.owner_id)
        mock_get.return_value = org
        mock_get_member.return_value = None
        with pytest.raises(ValueError, match="existing member"):
            await self.ops.transfer_ownership(
                self.db, org.id, self.owner_id, self.new_owner_id
            )


class TestGetSetting:
    """Tests for JSONB settings helpers."""

    def setup_method(self):
        self.ops = OrganizationOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    @patch.object(OrganizationOperations, "get")
    async def test_returns_default_when_no_settings(self, mock_get):
        org = make_mock_organization(settings=None)
        mock_get.return_value = org
        result = await self.ops.get_setting(self.db, org.id, "some_key", "default_val")
        assert result == "default_val"

    @pytest.mark.asyncio
    @patch.object(OrganizationOperations, "get")
    async def test_returns_value_when_key_exists(self, mock_get):
        org = make_mock_organization(settings={"some_key": "found"})
        mock_get.return_value = org
        result = await self.ops.get_setting(self.db, org.id, "some_key", "default_val")
        assert result == "found"
