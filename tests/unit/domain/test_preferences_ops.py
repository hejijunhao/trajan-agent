"""Unit tests for PreferencesOperations — get/create, encryption, token validation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.preferences_operations import PreferencesOperations

from tests.helpers.mock_factories import make_mock_preferences, mock_scalar_result


class TestGetOrCreate:
    """Tests for preferences get-or-create pattern."""

    def setup_method(self):
        self.ops = PreferencesOperations()
        self.db = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()
        self.user_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch.object(PreferencesOperations, "get_by_user_id")
    async def test_returns_existing_preferences(self, mock_get):
        prefs = make_mock_preferences(user_id=self.user_id)
        mock_get.return_value = prefs

        result = await self.ops.get_or_create(self.db, self.user_id)
        assert result is prefs

    @pytest.mark.asyncio
    @patch.object(PreferencesOperations, "get_by_user_id")
    async def test_creates_default_when_none_exists(self, mock_get):
        mock_get.return_value = None

        result = await self.ops.get_or_create(self.db, self.user_id)
        assert result is not None
        assert result.user_id == self.user_id


class TestGetDecryptedToken:
    """Tests for GitHub token decryption."""

    def setup_method(self):
        self.ops = PreferencesOperations()

    @patch("app.domain.preferences_operations.token_encryption")
    def test_returns_decrypted_token(self, mock_enc):
        mock_enc.decrypt.return_value = "ghp_real_token"
        prefs = make_mock_preferences(github_token="encrypted_value")

        result = self.ops.get_decrypted_token(prefs)
        assert result == "ghp_real_token"
        mock_enc.decrypt.assert_called_once_with("encrypted_value")

    def test_returns_none_when_no_token(self):
        prefs = make_mock_preferences(github_token=None)
        result = self.ops.get_decrypted_token(prefs)
        assert result is None


class TestValidateGithubToken:
    """Tests for GitHub token validation via API."""

    def setup_method(self):
        self.ops = PreferencesOperations()

    @pytest.mark.asyncio
    @patch("app.domain.preferences_operations.httpx.AsyncClient")
    async def test_valid_token_returns_username(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "octocat", "name": "Octo Cat"}
        mock_response.headers = {"X-OAuth-Scopes": "repo, read:org"}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await self.ops.validate_github_token("ghp_test_token")
        assert result["valid"] is True
        assert result["username"] == "octocat"
        assert result["has_repo_scope"] is True
