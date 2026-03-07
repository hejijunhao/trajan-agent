"""Unit tests for OrgDigestPreferenceOperations."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.org_digest_preference_operations import OrgDigestPreferenceOperations
from tests.helpers.mock_factories import make_mock_org_digest_preference


class TestGetByUserAndOrg:
    """Tests for fetching a specific user+org preference."""

    def setup_method(self):
        self.ops = OrgDigestPreferenceOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.user_id = uuid.uuid4()
        self.org_id = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_returns_preference_when_found(self):
        pref = make_mock_org_digest_preference(
            user_id=self.user_id, organization_id=self.org_id
        )
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = pref
        self.db.execute.return_value = result_mock

        result = await self.ops.get_by_user_and_org(self.db, self.user_id, self.org_id)
        assert result is pref

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        self.db.execute.return_value = result_mock

        result = await self.ops.get_by_user_and_org(self.db, self.user_id, self.org_id)
        assert result is None


class TestGetOrCreate:
    """Tests for get-or-create pattern."""

    def setup_method(self):
        self.ops = OrgDigestPreferenceOperations()
        self.db = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()
        self.user_id = uuid.uuid4()
        self.org_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch.object(OrgDigestPreferenceOperations, "get_by_user_and_org")
    async def test_returns_existing_preference(self, mock_get):
        pref = make_mock_org_digest_preference(
            user_id=self.user_id, organization_id=self.org_id
        )
        mock_get.return_value = pref

        result = await self.ops.get_or_create(self.db, self.user_id, self.org_id)
        assert result is pref
        self.db.flush.assert_not_called()

    @pytest.mark.asyncio
    @patch.object(OrgDigestPreferenceOperations, "get_by_user_and_org")
    async def test_creates_default_when_none_exists(self, mock_get):
        mock_get.return_value = None

        result = await self.ops.get_or_create(self.db, self.user_id, self.org_id)
        assert result is not None
        assert result.user_id == self.user_id
        assert result.organization_id == self.org_id
        assert result.email_digest == "none"
        self.db.add.assert_called_once()
        self.db.flush.assert_called_once()


class TestGetAllForUser:
    """Tests for fetching all org preferences for a user."""

    def setup_method(self):
        self.ops = OrgDigestPreferenceOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()
        self.user_id = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_returns_all_preferences(self):
        pref1 = make_mock_org_digest_preference(user_id=self.user_id)
        pref2 = make_mock_org_digest_preference(user_id=self.user_id)

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [pref1, pref2]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        self.db.execute.return_value = result_mock

        result = await self.ops.get_all_for_user(self.db, self.user_id)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        self.db.execute.return_value = result_mock

        result = await self.ops.get_all_for_user(self.db, self.user_id)
        assert result == []


class TestGetAllActiveForFrequency:
    """Tests for querying active preferences by frequency."""

    def setup_method(self):
        self.ops = OrgDigestPreferenceOperations()
        self.db = MagicMock()
        self.db.execute = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_daily_preferences(self):
        pref = make_mock_org_digest_preference(email_digest="daily")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [pref]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        self.db.execute.return_value = result_mock

        result = await self.ops.get_all_active_for_frequency(self.db, "daily")
        assert len(result) == 1
        assert result[0].email_digest == "daily"


class TestUpdate:
    """Tests for updating a preference."""

    def setup_method(self):
        self.ops = OrgDigestPreferenceOperations()
        self.db = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

    @pytest.mark.asyncio
    async def test_updates_allowed_fields(self):
        pref = make_mock_org_digest_preference(email_digest="none")

        result = await self.ops.update(
            self.db, pref, {"email_digest": "daily", "digest_hour": 9}
        )

        assert result.email_digest == "daily"
        assert result.digest_hour == 9
        self.db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_disallowed_fields(self):
        pref = make_mock_org_digest_preference()
        original_user_id = pref.user_id

        await self.ops.update(self.db, pref, {"user_id": uuid.uuid4()})
        assert pref.user_id == original_user_id


class TestDelete:
    """Tests for deleting a preference."""

    def setup_method(self):
        self.ops = OrgDigestPreferenceOperations()
        self.db = MagicMock()
        self.db.delete = AsyncMock()
        self.db.flush = AsyncMock()

    @pytest.mark.asyncio
    async def test_deletes_preference(self):
        pref = make_mock_org_digest_preference()

        await self.ops.delete(self.db, pref)
        self.db.delete.assert_called_once_with(pref)
        self.db.flush.assert_called_once()
