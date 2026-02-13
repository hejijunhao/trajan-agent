"""Unit tests for FeedbackOperations — all DB calls mocked."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.feedback_operations import FeedbackOperations

from tests.helpers.mock_factories import (
    make_mock_feedback,
    mock_scalar_result,
    mock_scalars_result,
)


class TestFeedbackCreateFeedback:
    """Tests for feedback submission."""

    def setup_method(self):
        self.ops = FeedbackOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_create_returns_feedback_with_correct_fields(self):
        user_id = uuid.uuid4()
        data = MagicMock()
        data.model_dump.return_value = {
            "type": "bug",
            "title": "Auth broken",
            "description": "Login fails",
        }

        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.create_feedback(self.db, user_id, data)
        assert result.user_id == user_id
        assert result.type == "bug"
        assert result.title == "Auth broken"


class TestFeedbackListByUser:
    """Tests for user-scoped feedback listing."""

    def setup_method(self):
        self.ops = FeedbackOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_feedback_for_user(self):
        feedbacks = [make_mock_feedback() for _ in range(3)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(feedbacks))

        result = await self.ops.list_by_user(self.db, uuid.uuid4())
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_feedback(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.list_by_user(self.db, uuid.uuid4())
        assert result == []


class TestFeedbackGetByStatus:
    """Tests for admin status-filtered listing."""

    def setup_method(self):
        self.ops = FeedbackOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_feedback_filtered_by_status(self):
        feedbacks = [make_mock_feedback(status="reviewed")]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(feedbacks))

        result = await self.ops.get_by_status(self.db, "reviewed")
        assert len(result) == 1


class TestFeedbackGetAll:
    """Tests for admin listing of all feedback."""

    def setup_method(self):
        self.ops = FeedbackOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_all_feedback(self):
        feedbacks = [make_mock_feedback() for _ in range(5)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(feedbacks))

        result = await self.ops.get_all(self.db)
        assert len(result) == 5


class TestFeedbackUpdateAiSummary:
    """Tests for AI summary updates."""

    def setup_method(self):
        self.ops = FeedbackOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_sets_ai_summary_and_processed_at(self):
        feedback = make_mock_feedback()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(feedback))
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.update_ai_summary(
            self.db, feedback.id, "AI says: bug in auth"
        )
        assert result.ai_summary == "AI says: bug in auth"
        assert result.ai_processed_at is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_feedback_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.update_ai_summary(self.db, uuid.uuid4(), "summary")
        assert result is None


class TestFeedbackUpdateStatus:
    """Tests for admin status updates."""

    def setup_method(self):
        self.ops = FeedbackOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_updates_status(self):
        feedback = make_mock_feedback(status="new")
        self.db.execute = AsyncMock(return_value=mock_scalar_result(feedback))
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.update_status(self.db, feedback.id, "reviewed")
        assert result.status == "reviewed"

    @pytest.mark.asyncio
    async def test_updates_status_with_admin_notes(self):
        feedback = make_mock_feedback(status="new")
        self.db.execute = AsyncMock(return_value=mock_scalar_result(feedback))
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.update_status(
            self.db, feedback.id, "resolved", admin_notes="Fixed in v0.9.27"
        )
        assert result.status == "resolved"
        assert result.admin_notes == "Fixed in v0.9.27"

    @pytest.mark.asyncio
    async def test_returns_none_when_feedback_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.update_status(self.db, uuid.uuid4(), "reviewed")
        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_overwrite_notes_when_none(self):
        feedback = make_mock_feedback(admin_notes="existing notes")
        self.db.execute = AsyncMock(return_value=mock_scalar_result(feedback))
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()

        await self.ops.update_status(self.db, feedback.id, "reviewed")
        # admin_notes=None means don't update, so existing notes should remain
        assert feedback.admin_notes == "existing notes"
