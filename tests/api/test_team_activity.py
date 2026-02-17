"""Tests for the organization team activity endpoint.

GET /api/v1/organizations/{org_id}/team-activity
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.api.v1.organizations.team_activity import _compute_streak, _merge_daily_activity

# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for helper functions
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeStreak:
    """Tests for _compute_streak helper."""

    def test_no_activity(self):
        assert _compute_streak([]) == 0

    def test_no_commits(self):
        today = datetime.now(UTC).date()
        activity = [{"date": today.strftime("%Y-%m-%d"), "commits": 0}]
        assert _compute_streak(activity) == 0

    def test_streak_today(self):
        today = datetime.now(UTC).date()
        activity = []
        for i in range(5):
            d = today - timedelta(days=i)
            activity.append({"date": d.strftime("%Y-%m-%d"), "commits": 1 if i < 3 else 0})
        assert _compute_streak(activity) == 3

    def test_streak_from_yesterday(self):
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)
        activity = [
            {"date": today.strftime("%Y-%m-%d"), "commits": 0},
            {"date": yesterday.strftime("%Y-%m-%d"), "commits": 2},
            {"date": (yesterday - timedelta(days=1)).strftime("%Y-%m-%d"), "commits": 1},
        ]
        assert _compute_streak(activity) == 2

    def test_streak_broken(self):
        today = datetime.now(UTC).date()
        activity = [
            {"date": today.strftime("%Y-%m-%d"), "commits": 1},
            {"date": (today - timedelta(days=1)).strftime("%Y-%m-%d"), "commits": 0},
            {"date": (today - timedelta(days=2)).strftime("%Y-%m-%d"), "commits": 5},
        ]
        assert _compute_streak(activity) == 1


class TestMergeDailyActivity:
    """Tests for _merge_daily_activity helper."""

    def test_single_source(self):
        today = datetime.now(UTC).date()
        ds = today.strftime("%Y-%m-%d")
        activity = [[{"date": ds, "commits": 3}]]
        merged = _merge_daily_activity(activity, 1)
        assert len(merged) == 1
        assert merged[0]["date"] == ds
        assert merged[0]["commits"] == 3

    def test_multiple_sources_merged(self):
        today = datetime.now(UTC).date()
        ds = today.strftime("%Y-%m-%d")
        sources = [
            [{"date": ds, "commits": 2}],
            [{"date": ds, "commits": 5}],
        ]
        merged = _merge_daily_activity(sources, 1)
        assert merged[0]["commits"] == 7

    def test_fills_missing_days(self):
        merged = _merge_daily_activity([], 7)
        assert len(merged) == 7
        assert all(d["commits"] == 0 for d in merged)


# ─────────────────────────────────────────────────────────────────────────────
# API endpoint tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_team_activity_requires_auth(unauth_client: AsyncClient, test_org):
    """Unauthenticated requests get 401."""
    resp = await unauth_client.get(f"/api/v1/organizations/{test_org.id}/team-activity")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_team_activity_non_member_403(second_user_client: AsyncClient, test_org):
    """Non-org members get 403."""
    resp = await second_user_client.get(
        f"/api/v1/organizations/{test_org.id}/team-activity"
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_team_activity_empty_org(api_client: AsyncClient, test_org):
    """Org with no products returns members as idle/pending."""
    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}/team-activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_days"] == 14
    assert data["aggregate"]["active_contributors"] == 0
    assert data["aggregate"]["total_commits"] == 0
    # Owner should appear as a member
    assert len(data["members"]) >= 1


@pytest.mark.anyio
async def test_team_activity_with_product_no_repos(
    api_client: AsyncClient, test_org, test_product  # noqa: ARG001
):
    """Org with product but no repos returns empty activity."""
    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}/team-activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["aggregate"]["total_commits"] == 0
    assert data["aggregate"]["products_touched"] == 0


@pytest.mark.anyio
async def test_team_activity_custom_days(api_client: AsyncClient, test_org):
    """Custom days parameter is respected."""
    resp = await api_client.get(
        f"/api/v1/organizations/{test_org.id}/team-activity?days=7"
    )
    assert resp.status_code == 200
    assert resp.json()["period_days"] == 7


@pytest.mark.anyio
async def test_team_activity_invalid_days_defaults(api_client: AsyncClient, test_org):
    """Invalid days parameter defaults to 14."""
    resp = await api_client.get(
        f"/api/v1/organizations/{test_org.id}/team-activity?days=999"
    )
    assert resp.status_code == 200
    assert resp.json()["period_days"] == 14


@pytest.mark.anyio
async def test_team_activity_sort_options(api_client: AsyncClient, test_org):
    """All sort options return 200."""
    for sort in ("commits", "additions", "last_active", "name"):
        resp = await api_client.get(
            f"/api/v1/organizations/{test_org.id}/team-activity?sort={sort}"
        )
        assert resp.status_code == 200


@pytest.mark.anyio
async def test_team_activity_response_structure(api_client: AsyncClient, test_org):
    """Response has the expected top-level structure."""
    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}/team-activity")
    assert resp.status_code == 200
    data = resp.json()

    assert "period_days" in data
    assert "aggregate" in data
    assert "members" in data

    agg = data["aggregate"]
    assert "active_contributors" in agg
    assert "total_commits" in agg
    assert "total_additions" in agg
    assert "total_deletions" in agg
    assert "products_touched" in agg


@pytest.mark.anyio
async def test_team_activity_member_fields(api_client: AsyncClient, test_org):
    """Each member has the expected fields."""
    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}/team-activity")
    assert resp.status_code == 200
    data = resp.json()

    for member in data["members"]:
        assert "user_id" in member
        assert "display_name" in member
        assert "status" in member
        assert member["status"] in ("active", "idle", "pending")
        assert "recent_commits" in member


@pytest.mark.anyio
async def test_team_activity_pending_member(
    api_client: AsyncClient, db_session, test_org
):
    """Members who haven't signed in show as pending."""
    from app.domain.org_member_operations import org_member_ops
    from app.models.user import User

    # Create a user that hasn't completed onboarding
    pending_user = User(
        id=uuid.uuid4(),
        email=f"pending_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Pending User",
        onboarding_completed_at=None,
        created_at=datetime.now(UTC),
    )
    db_session.add(pending_user)
    await db_session.flush()

    await org_member_ops.add_member(
        db_session,
        organization_id=test_org.id,
        user_id=pending_user.id,
        role="member",
    )
    await db_session.flush()

    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}/team-activity")
    assert resp.status_code == 200
    data = resp.json()

    pending_members = [m for m in data["members"] if m["status"] == "pending"]
    assert len(pending_members) >= 1
    pending_emails = [m["email"] for m in pending_members]
    assert pending_user.email in pending_emails


@pytest.mark.anyio
async def test_team_activity_nonexistent_org(api_client: AsyncClient):
    """Nonexistent org returns 403 (not a member)."""
    fake_id = uuid.uuid4()
    resp = await api_client.get(f"/api/v1/organizations/{fake_id}/team-activity")
    assert resp.status_code in (403, 404)
