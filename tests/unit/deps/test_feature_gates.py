"""Unit tests for feature gate dependencies."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.deps.feature_gates import (
    FeatureGate,
    SubscriptionContext,
    require_active_subscription,
    require_agent_enabled,
)
from app.config.plans import get_plan

from tests.helpers.mock_factories import make_mock_organization, make_mock_subscription


def _make_ctx(tier: str = "indie", status: str = "active", **sub_overrides) -> SubscriptionContext:
    """Helper to build a SubscriptionContext for testing."""
    org = make_mock_organization()
    sub = make_mock_subscription(tier=tier, status=status, **sub_overrides)
    plan = get_plan(tier)
    return SubscriptionContext(organization=org, subscription=sub, plan=plan)


class TestFeatureGate:
    """Tests for the FeatureGate dependency class."""

    @pytest.mark.asyncio
    async def test_allows_when_plan_has_feature(self):
        ctx = _make_ctx(tier="pro")  # Pro has team_collaboration
        gate = FeatureGate("team_collaboration")
        result = await gate(ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_raises_403_when_plan_lacks_feature(self):
        ctx = _make_ctx(tier="indie")  # Indie lacks team_collaboration
        gate = FeatureGate("team_collaboration")
        with pytest.raises(HTTPException) as exc_info:
            await gate(ctx)
        assert exc_info.value.status_code == 403
        assert "team_collaboration" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_raises_403_for_unknown_feature(self):
        ctx = _make_ctx(tier="scale")
        gate = FeatureGate("nonexistent_feature")
        with pytest.raises(HTTPException) as exc_info:
            await gate(ctx)
        assert exc_info.value.status_code == 403


class TestRequireActiveSubscription:
    """Tests for the require_active_subscription dependency."""

    @pytest.mark.asyncio
    async def test_allows_active_subscription(self):
        ctx = _make_ctx(tier="indie", status="active")
        result = await require_active_subscription(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_raises_402_for_none_tier(self):
        ctx = _make_ctx(tier="none", status="pending")
        with pytest.raises(HTTPException) as exc_info:
            await require_active_subscription(ctx)
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_raises_402_for_pending_status(self):
        ctx = _make_ctx(tier="indie", status="pending")
        with pytest.raises(HTTPException) as exc_info:
            await require_active_subscription(ctx)
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_402_detail_contains_subscription_required_code(self):
        ctx = _make_ctx(tier="none", status="pending")
        with pytest.raises(HTTPException) as exc_info:
            await require_active_subscription(ctx)
        assert exc_info.value.detail["code"] == "SUBSCRIPTION_REQUIRED"


class TestRequireAgentEnabled:
    """Tests for the require_agent_enabled dependency."""

    @pytest.mark.asyncio
    @patch("app.api.deps.feature_gates.subscription_ops")
    @patch("app.domain.repository_operations.repository_ops")
    async def test_allows_paid_plan(self, mock_repo_ops, mock_sub_ops):
        mock_repo_ops.count_by_org = AsyncMock(return_value=3)
        mock_sub_ops.is_agent_enabled = AsyncMock(return_value=True)
        db = AsyncMock()

        ctx = _make_ctx(tier="pro")
        result = await require_agent_enabled(ctx, db)
        assert result is ctx

    @pytest.mark.asyncio
    @patch("app.api.deps.feature_gates.subscription_ops")
    @patch("app.domain.repository_operations.repository_ops")
    async def test_raises_403_when_over_limit(self, mock_repo_ops, mock_sub_ops):
        mock_repo_ops.count_by_org = AsyncMock(return_value=10)
        mock_sub_ops.is_agent_enabled = AsyncMock(return_value=False)
        db = AsyncMock()

        ctx = _make_ctx(tier="indie")
        with pytest.raises(HTTPException) as exc_info:
            await require_agent_enabled(ctx, db)
        assert exc_info.value.status_code == 403
