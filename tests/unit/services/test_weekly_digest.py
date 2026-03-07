"""
Tests for the digest email job (daily and weekly).

Verifies:
- Consolidated mode (all projects, single email)
- Per-project mode (one email per selected project)
- Empty digest skipping (no cached data → no email)
- Product deduplication via seen_ids
- digest_product_ids filtering
- Users with no email are skipped
- Postmark disabled → early return
- Partial send failure counting
- users_emailed only increments on success (Phase 1 fix)
- Daily digest: subject lines, period, no day-of-week gate
- Progress review HTML: contributor blocks, overflow, commit ref badges
- Plain-text contributor summaries
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email.weekly_digest import (
    WeeklyDigestReport,
    _build_email_html,
    _build_plain_text,
    _build_product_html,
    _build_progress_review_html,
    send_digests,
    send_weekly_digests,
)

# ---------------------------------------------------------------------------
# Time-matching constants — computed once at import so prefs pass the
# eligible-hour filter added in v0.9.23 (per-user local time delivery).
# ---------------------------------------------------------------------------

_NOW_UTC = datetime.now(UTC)
_CURRENT_DAY = _NOW_UTC.strftime("%a").lower()  # e.g. "mon", "tue", …
_CURRENT_HOUR = _NOW_UTC.hour

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_user(email: str | None = "user@example.com") -> MagicMock:
    """Create a mock User with an email."""
    user = MagicMock()
    user.email = email
    return user


def _make_mock_prefs(
    user: MagicMock | None = None,
    digest_product_ids: list[str] | None = None,
) -> MagicMock:
    """Create a mock UserPreferences with the fields weekly_digest.py accesses."""
    prefs = MagicMock()
    prefs.user_id = uuid.uuid4()
    prefs.user = user or _make_mock_user()
    prefs.email_digest = "weekly"
    prefs.digest_product_ids = digest_product_ids
    # Time-matching fields (v0.9.23): ensure prefs pass the eligible-hour filter
    prefs.digest_timezone = "UTC"
    prefs.digest_hour = _CURRENT_HOUR
    return prefs


def _configure_digest_settings(mock_settings: MagicMock) -> None:
    """Set required settings fields so the digest job runs normally."""
    mock_settings.postmark_enabled = True
    mock_settings.weekly_digest_day = _CURRENT_DAY
    mock_settings.frontend_url = "https://www.trajancloud.com"


def _make_mock_product(name: str = "Test Product") -> MagicMock:
    """Create a mock Product."""
    product = MagicMock()
    product.id = uuid.uuid4()
    product.name = name
    product.organization_id = uuid.uuid4()
    return product


def _make_mock_membership(org_id: uuid.UUID, org: MagicMock | None = None) -> MagicMock:
    """Create a mock OrganizationMember with an organization."""
    membership = MagicMock()
    membership.organization = org or MagicMock(id=org_id)
    return membership


def _make_mock_prefs_daily(
    user: MagicMock | None = None,
    digest_product_ids: list[str] | None = None,
) -> MagicMock:
    """Create a mock UserPreferences configured for daily digest."""
    prefs = _make_mock_prefs(user=user, digest_product_ids=digest_product_ids)
    prefs.email_digest = "daily"
    return prefs


def _make_mock_summary(
    text: str = "Great progress this week.",
    contributor_summaries: list[dict] | None = None,
) -> MagicMock:
    """Create a mock ProgressSummary."""
    summary = MagicMock()
    summary.summary_text = text
    summary.contributor_summaries = contributor_summaries
    return summary


def _make_mock_shipped(
    items: list[dict] | None = None,
    has_significant_changes: bool = True,
) -> MagicMock:
    """Create a mock DashboardShippedSummary."""
    shipped = MagicMock()
    shipped.items = items or [
        {"description": "Added auth", "category": "feature"},
        {"description": "Fixed login bug", "category": "fix"},
    ]
    shipped.has_significant_changes = has_significant_changes
    return shipped


def _mock_scalars_result(values: list) -> MagicMock:
    """Create a mock db.execute() result whose .scalars().all() returns `values`."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


# ---------------------------------------------------------------------------
# send_weekly_digests — top-level entry point
# ---------------------------------------------------------------------------


class TestSendWeeklyDigests:
    """Tests for the main send_weekly_digests() function."""

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.settings")
    async def test_postmark_disabled_returns_early(self, mock_settings: MagicMock) -> None:
        """When Postmark is not configured, the job returns immediately."""
        mock_settings.postmark_enabled = False

        db = AsyncMock()
        report = await send_weekly_digests(db)

        assert report.users_checked == 0
        assert report.users_emailed == 0
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.settings")
    async def test_no_opted_in_users(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """When no users have weekly digest enabled, nothing is sent."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        report = await send_weekly_digests(db)

        assert report.users_checked == 0
        assert report.users_emailed == 0
        assert report.emails_sent == 0

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.settings")
    async def test_skips_user_with_no_email(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """A user with no email address should be skipped."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        prefs = _make_mock_prefs(user=_make_mock_user(email=None))

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_checked == 1
        assert report.users_emailed == 0
        assert report.skipped_reasons.get("no_email") == 1

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.settings")
    async def test_skips_user_with_no_user_relation(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """A prefs record with user=None should be skipped."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        prefs = _make_mock_prefs()
        prefs.user = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_checked == 1
        assert report.skipped_reasons.get("no_email") == 1

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.settings")
    @patch("app.services.email.weekly_digest._send_digest_for_user")
    async def test_catches_exception_per_user(
        self,
        mock_send_digest: MagicMock,
        mock_settings: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """If processing one user throws, the job continues to the next."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        prefs1 = _make_mock_prefs(user=_make_mock_user("fail@test.com"))
        prefs2 = _make_mock_prefs(user=_make_mock_user("ok@test.com"))

        mock_send_digest.side_effect = [RuntimeError("boom"), None]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs1, prefs2]))

        report = await send_weekly_digests(db)

        assert report.users_checked == 2
        assert report.errors >= 1
        assert mock_send_digest.call_count == 2


# ---------------------------------------------------------------------------
# _send_digest_for_user — core per-user logic
# ---------------------------------------------------------------------------


class TestSendDigestForUser:
    """Tests for the per-user digest logic via the full send_weekly_digests path."""

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_consolidated_mode_sends_single_email(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Consolidated mode (digest_product_ids=None): one email with all projects."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=True)

        product_a = _make_mock_product("Project Alpha")
        product_b = _make_mock_product("Project Beta")
        mock_get_products.return_value = [product_a, product_b]

        mock_progress_ops.get_by_product_period = AsyncMock(
            side_effect=[_make_mock_summary("Alpha progress"), _make_mock_summary("Beta progress")]
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(
            side_effect=[_make_mock_shipped(), _make_mock_shipped()]
        )

        prefs = _make_mock_prefs(digest_product_ids=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_checked == 1
        assert report.users_emailed == 1
        assert report.emails_sent == 1
        mock_postmark.send.assert_called_once()

        call_kwargs = mock_postmark.send.call_args.kwargs
        assert call_kwargs["subject"] == "Your Weekly Progress"
        assert "Project Alpha" in call_kwargs["html_body"]
        assert "Project Beta" in call_kwargs["html_body"]

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_per_project_mode_sends_multiple_emails(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Per-project mode: one email per selected product."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=True)

        product_a = _make_mock_product("Project Alpha")
        product_b = _make_mock_product("Project Beta")
        mock_get_products.return_value = [product_a, product_b]

        mock_progress_ops.get_by_product_period = AsyncMock(
            side_effect=[_make_mock_summary("Alpha"), _make_mock_summary("Beta")]
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(
            side_effect=[_make_mock_shipped(), _make_mock_shipped()]
        )

        prefs = _make_mock_prefs(digest_product_ids=[str(product_a.id), str(product_b.id)])

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_emailed == 1
        assert report.emails_sent == 2
        assert mock_postmark.send.call_count == 2

        # Each email should have the project name in the subject
        subjects = [c.kwargs["subject"] for c in mock_postmark.send.call_args_list]
        assert "Weekly: Project Alpha" in subjects
        assert "Weekly: Project Beta" in subjects

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_skips_user_with_no_products(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """User with no products should be skipped."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_get_products.return_value = []

        prefs = _make_mock_prefs(digest_product_ids=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_emailed == 0
        assert report.skipped_reasons.get("no_products") == 1
        mock_postmark.send.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_skips_user_with_no_activity(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """User whose products all have no cached data should be skipped."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        product = _make_mock_product("Empty Project")
        mock_get_products.return_value = [product]

        # No cached data
        mock_progress_ops.get_by_product_period = AsyncMock(return_value=None)
        mock_shipped_ops.get_by_product_period = AsyncMock(return_value=None)

        prefs = _make_mock_prefs(digest_product_ids=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_emailed == 0
        assert report.skipped_reasons.get("no_activity") == 1
        mock_postmark.send.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_digest_product_ids_filters_products(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Only selected products should be included when digest_product_ids is set."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=True)

        product_a = _make_mock_product("Selected")
        product_b = _make_mock_product("Not Selected")
        mock_get_products.return_value = [product_a, product_b]

        # Only product_a's ops should be called
        mock_progress_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_summary("Selected progress")
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(return_value=_make_mock_shipped())

        prefs = _make_mock_prefs(digest_product_ids=[str(product_a.id)])

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.emails_sent == 1
        # Only 1 product queried (the selected one)
        assert mock_progress_ops.get_by_product_period.call_count == 1

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_users_emailed_not_incremented_on_all_failures(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """If all sends fail for a user, users_emailed should NOT increment (Phase 1 fix)."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=False)  # all sends fail

        product = _make_mock_product("Fail Project")
        mock_get_products.return_value = [product]

        mock_progress_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_summary("Some progress")
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(return_value=_make_mock_shipped())

        prefs = _make_mock_prefs(digest_product_ids=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_emailed == 0  # NOT incremented
        assert report.emails_sent == 0
        assert report.errors == 1

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_per_project_partial_failure(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Per-project mode: partial send failure still counts user as emailed."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        # First send succeeds, second fails
        mock_postmark.send = AsyncMock(side_effect=[True, False])

        product_a = _make_mock_product("Good Project")
        product_b = _make_mock_product("Bad Project")
        mock_get_products.return_value = [product_a, product_b]

        mock_progress_ops.get_by_product_period = AsyncMock(
            side_effect=[_make_mock_summary("Good"), _make_mock_summary("Bad")]
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(
            side_effect=[_make_mock_shipped(), _make_mock_shipped()]
        )

        prefs = _make_mock_prefs(digest_product_ids=[str(product_a.id), str(product_b.id)])

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.users_emailed == 1  # at least one succeeded
        assert report.emails_sent == 1
        assert report.errors == 1

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_shipped_not_significant_excluded(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Products where shipped.has_significant_changes=False should exclude items."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=True)

        product = _make_mock_product("Minor Changes")
        mock_get_products.return_value = [product]

        mock_progress_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_summary("Some narrative")
        )
        # has_significant_changes=False → items should be ignored
        mock_shipped_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_shipped(
                items=[{"description": "Minor tweak", "category": "fix"}],
                has_significant_changes=False,
            )
        )

        prefs = _make_mock_prefs(digest_product_ids=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        # Email still sent (narrative exists), but items should not appear
        assert report.emails_sent == 1
        call_kwargs = mock_postmark.send.call_args.kwargs
        assert "Minor tweak" not in call_kwargs["text_body"]


# ---------------------------------------------------------------------------
# _get_user_products — product resolution and deduplication
# ---------------------------------------------------------------------------


class TestGetUserProducts:
    """Tests for product resolution across org memberships."""

    @pytest.mark.asyncio
    async def test_deduplicates_products_across_orgs(self) -> None:
        """A product seen via multiple orgs should appear only once."""
        from app.services.email.weekly_digest import _get_user_products

        shared_product = _make_mock_product("Shared")
        org_a = MagicMock(id=uuid.uuid4())
        org_b = MagicMock(id=uuid.uuid4())

        membership_a = _make_mock_membership(org_a.id, org=org_a)
        membership_b = _make_mock_membership(org_b.id, org=org_b)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([membership_a, membership_b]),  # memberships
                _mock_scalars_result([shared_product]),  # org_a products
                _mock_scalars_result([shared_product]),  # org_b products (same product)
            ]
        )

        products = await _get_user_products(db, uuid.uuid4())

        assert len(products) == 1
        assert products[0].name == "Shared"

    @pytest.mark.asyncio
    async def test_skips_membership_with_no_org(self) -> None:
        """Memberships where organization is None should be skipped."""
        from app.services.email.weekly_digest import _get_user_products

        membership = MagicMock()
        membership.organization = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([membership]))

        products = await _get_user_products(db, uuid.uuid4())

        assert len(products) == 0


# ---------------------------------------------------------------------------
# Email template tests
# ---------------------------------------------------------------------------


class TestEmailTemplates:
    """Tests for the HTML and plain-text email builders."""

    def test_product_html_contains_name_and_narrative(self) -> None:
        html = _build_product_html("My App", "Shipped many features.", [])
        assert "My App" in html
        assert "Shipped many features." in html

    def test_product_html_renders_items_with_badges(self) -> None:
        items = [
            {"description": "Added dashboard", "category": "feature"},
            {"description": "Fixed crash", "category": "fix"},
        ]
        html = _build_product_html("App", "Progress", items)
        assert "Added dashboard" in html
        assert "Fixed crash" in html
        assert "New" in html  # "feature" → "New" label
        assert "Fix" in html  # "fix" → "Fix" label

    def test_product_html_caps_at_8_items(self) -> None:
        items = [{"description": f"Item {i}", "category": "feature"} for i in range(12)]
        html = _build_product_html("App", "Progress", items)
        assert "Item 7" in html  # 8th item (0-indexed)
        assert "Item 8" not in html  # 9th item should be hidden
        assert "… and 4 more" in html

    def test_email_html_contains_unsubscribe_link(self) -> None:
        html = _build_email_html(["<div>Section</div>"], "https://www.trajancloud.com")
        assert "settings/notifications" in html
        assert "Unsubscribe" in html

    def test_email_html_contains_open_trajan_link(self) -> None:
        html = _build_email_html(["<div>Section</div>"], "https://www.trajancloud.com")
        assert "https://www.trajancloud.com" in html
        assert "Open Trajan" in html

    def test_plain_text_contains_product_data(self) -> None:
        data = [
            ("My App", "Good week", [{"description": "New feature", "category": "feature"}], None)
        ]
        text = _build_plain_text(data)
        assert "My App" in text
        assert "Good week" in text
        assert "[feature] New feature" in text

    def test_plain_text_caps_at_8_items(self) -> None:
        items = [{"description": f"Item {i}", "category": "fix"} for i in range(10)]
        text = _build_plain_text([("App", "Narrative", items, None)])
        assert "Item 7" in text
        assert "Item 8" not in text
        assert "… and 2 more" in text


# ---------------------------------------------------------------------------
# WeeklyDigestReport dataclass
# ---------------------------------------------------------------------------


class TestWeeklyDigestReport:
    """Tests for the report dataclass."""

    def test_defaults(self) -> None:
        report = WeeklyDigestReport()
        assert report.users_checked == 0
        assert report.users_emailed == 0
        assert report.emails_sent == 0
        assert report.errors == 0
        assert report.duration_seconds == 0.0
        assert report.skipped_reasons == {}

    def test_skipped_reasons_accumulate(self) -> None:
        report = WeeklyDigestReport()
        report.skipped_reasons["no_email"] = 2
        report.skipped_reasons["no_products"] = 1
        assert report.skipped_reasons == {"no_email": 2, "no_products": 1}


# ---------------------------------------------------------------------------
# send_digests — daily frequency path
# ---------------------------------------------------------------------------


class TestSendDailyDigests:
    """Tests for the daily digest path via send_digests(frequency='daily')."""

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_daily_sends_with_daily_subject(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Daily digest uses 'Your Daily Progress' subject and '1d' period."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=True)

        product = _make_mock_product("My Project")
        mock_get_products.return_value = [product]

        mock_progress_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_summary("Daily progress")
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(return_value=_make_mock_shipped())

        prefs = _make_mock_prefs_daily(digest_product_ids=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_digests(db, frequency="daily")

        assert report.users_emailed == 1
        assert report.emails_sent == 1

        call_kwargs = mock_postmark.send.call_args.kwargs
        assert call_kwargs["subject"] == "Your Daily Progress"
        assert "Daily Progress" in call_kwargs["html_body"]

        # Verify it queries the "1d" period, not "7d"
        # Call signature: get_by_product_period(db, product_id, period)
        period_args = [
            c.kwargs.get("period") or c.args[2]
            for c in mock_progress_ops.get_by_product_period.call_args_list
        ]
        assert all(p == "1d" for p in period_args)

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_daily_per_project_uses_daily_subject(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Per-project daily digest uses 'Daily Progress: {name}' subjects."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=True)

        product = _make_mock_product("Acme App")
        mock_get_products.return_value = [product]

        mock_progress_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_summary("Daily update")
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(return_value=_make_mock_shipped())

        prefs = _make_mock_prefs_daily(digest_product_ids=[str(product.id)])

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_digests(db, frequency="daily")

        assert report.emails_sent == 1
        call_kwargs = mock_postmark.send.call_args.kwargs
        assert call_kwargs["subject"] == "Daily Progress: Acme App"

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.settings")
    async def test_daily_runs_any_day_of_week(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """Daily digest doesn't gate on day-of-week — eligible any day."""
        _configure_digest_settings(mock_settings)
        # Set weekly_digest_day to a day that is NOT today — daily should still work
        mock_settings.weekly_digest_day = "zzz"  # impossible day
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        prefs = _make_mock_prefs_daily()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_digests(db, frequency="daily")

        # The user should be eligible (hour matches), even though day is wrong
        # They'll be skipped for no_products, but the point is they weren't
        # filtered out by day-of-week
        assert report.users_checked == 1

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.settings")
    async def test_weekly_skips_wrong_day(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """Weekly digest skips users when day-of-week doesn't match (contrast with daily)."""
        _configure_digest_settings(mock_settings)
        mock_settings.weekly_digest_day = "zzz"  # impossible day
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)

        prefs = _make_mock_prefs()  # weekly

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_digests(db, frequency="weekly")

        # No eligible users because the day is wrong
        assert report.users_checked == 1
        assert report.users_emailed == 0


# ---------------------------------------------------------------------------
# send_digests — contributor summaries in emails
# ---------------------------------------------------------------------------


class TestDigestWithContributorSummaries:
    """Tests that contributor summaries flow through to the email."""

    @pytest.mark.asyncio
    @patch("app.services.email.weekly_digest.postmark_service")
    @patch("app.services.email.weekly_digest.dashboard_shipped_ops")
    @patch("app.services.email.weekly_digest.progress_summary_ops")
    @patch("app.services.email.weekly_digest._get_user_products")
    @patch("app.services.email.weekly_digest.settings")
    async def test_contributor_summaries_appear_in_email(
        self,
        mock_settings: MagicMock,
        mock_get_products: MagicMock,
        mock_progress_ops: MagicMock,
        mock_shipped_ops: MagicMock,
        mock_postmark: MagicMock,
    ) -> None:
        """Contributor summaries from ProgressSummary should appear in both HTML and text."""
        _configure_digest_settings(mock_settings)
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=True)

        product = _make_mock_product("Project X")
        mock_get_products.return_value = [product]

        contribs = [
            {
                "name": "Alice",
                "summary_text": "Implemented OAuth flow.",
                "commit_count": 5,
                "additions": 200,
                "deletions": 30,
                "commit_refs": [{"sha": "abc1234", "branch": "main"}],
            },
        ]
        mock_progress_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_summary("Good week.", contributor_summaries=contribs)
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(return_value=_make_mock_shipped())

        prefs = _make_mock_prefs(digest_product_ids=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([prefs]))

        report = await send_weekly_digests(db)

        assert report.emails_sent == 1
        call_kwargs = mock_postmark.send.call_args.kwargs

        # HTML should contain contributor name and summary
        assert "Alice" in call_kwargs["html_body"]
        assert "Implemented OAuth flow." in call_kwargs["html_body"]
        assert "abc1234" in call_kwargs["html_body"]
        assert "Progress Review" in call_kwargs["html_body"]

        # Plain text too
        assert "Alice" in call_kwargs["text_body"]
        assert "Implemented OAuth flow." in call_kwargs["text_body"]


# ---------------------------------------------------------------------------
# _build_progress_review_html — progress review rendering
# ---------------------------------------------------------------------------


class TestBuildProgressReviewHtml:
    """Tests for the per-contributor progress review HTML builder."""

    def test_empty_list_returns_empty_string(self) -> None:
        assert _build_progress_review_html([]) == ""

    def test_renders_contributor_name_and_summary(self) -> None:
        data = [
            {
                "name": "Bob",
                "summary_text": "Fixed login bug.",
                "commit_count": 3,
                "commit_refs": [],
            },
        ]
        html = _build_progress_review_html(data)
        assert "Bob" in html
        assert "Fixed login bug." in html
        assert "3 commits" in html
        assert "Progress Review" in html

    def test_singular_commit_label(self) -> None:
        data = [{"name": "Solo", "summary_text": "One fix.", "commit_count": 1, "commit_refs": []}]
        html = _build_progress_review_html(data)
        assert "1 commit)" in html
        assert "1 commits" not in html

    def test_renders_commit_ref_badges(self) -> None:
        data = [
            {
                "name": "Charlie",
                "summary_text": "Refactored auth.",
                "commit_count": 2,
                "commit_refs": [
                    {"sha": "a1b2c3d", "branch": "main"},
                    {"sha": "e4f5g6h", "branch": "feature/x"},
                ],
            },
        ]
        html = _build_progress_review_html(data)
        assert "a1b2c3d" in html
        assert "e4f5g6h" in html

    def test_caps_ref_badges_at_3(self) -> None:
        refs = [{"sha": f"sha{i}abc", "branch": "main"} for i in range(5)]
        data = [{"name": "Dev", "summary_text": "Busy.", "commit_count": 5, "commit_refs": refs}]
        html = _build_progress_review_html(data)
        assert "sha0abc" in html
        assert "sha2abc" in html
        assert "sha3abc" not in html  # 4th ref should be omitted

    def test_caps_contributors_at_5_with_overflow(self) -> None:
        data = [
            {"name": f"Dev{i}", "summary_text": f"Work {i}.", "commit_count": 1, "commit_refs": []}
            for i in range(7)
        ]
        html = _build_progress_review_html(data)
        assert "Dev0" in html
        assert "Dev4" in html
        assert "Dev5" not in html  # 6th contributor hidden
        assert "… and 2 more contributors" in html

    def test_overflow_singular(self) -> None:
        data = [
            {"name": f"Dev{i}", "summary_text": "Work.", "commit_count": 1, "commit_refs": []}
            for i in range(6)
        ]
        html = _build_progress_review_html(data)
        assert "… and 1 more contributor" in html
        assert "contributors" not in html

    def test_html_escapes_names(self) -> None:
        data = [
            {
                "name": "<script>alert('xss')</script>",
                "summary_text": "Normal work.",
                "commit_count": 1,
                "commit_refs": [],
            },
        ]
        html = _build_progress_review_html(data)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Email template tests — daily frequency
# ---------------------------------------------------------------------------


class TestEmailTemplatesDaily:
    """Tests for frequency-aware email templates."""

    def test_daily_email_html_heading(self) -> None:
        html = _build_email_html(["<div>Section</div>"], "https://app.test.com", frequency="daily")
        assert "Daily Progress" in html
        assert "Your projects today" in html
        assert "daily digests" in html

    def test_weekly_email_html_heading(self) -> None:
        html = _build_email_html(["<div>Section</div>"], "https://app.test.com", frequency="weekly")
        assert "Weekly Progress" in html
        assert "Your projects this week" in html
        assert "weekly digests" in html

    def test_daily_plain_text_heading(self) -> None:
        data = [("App", "Progress.", [{"description": "Fix", "category": "fix"}], None)]
        text = _build_plain_text(data, frequency="daily")
        assert "Daily Progress" in text
        assert "Your projects today" in text

    def test_plain_text_includes_contributor_summaries(self) -> None:
        contribs = [
            {"name": "Alice", "summary_text": "Shipped auth flow.", "commit_count": 4},
            {"name": "Bob", "summary_text": "Fixed tests.", "commit_count": 2},
        ]
        data = [
            ("App", "Good week.", [{"description": "Feature", "category": "feature"}], contribs)
        ]
        text = _build_plain_text(data)
        assert "Progress Review:" in text
        assert "Alice (4 commits)" in text
        assert "Shipped auth flow." in text
        assert "Bob (2 commits)" in text
        assert "Fixed tests." in text

    def test_plain_text_contributor_overflow(self) -> None:
        contribs = [
            {"name": f"Dev{i}", "summary_text": f"Work {i}.", "commit_count": 1} for i in range(7)
        ]
        data = [("App", "Busy.", [], contribs)]
        text = _build_plain_text(data)
        assert "Dev4" in text
        assert "Dev5" not in text
        assert "… and 2 more contributors" in text

    def test_product_html_with_contributor_summaries(self) -> None:
        contribs = [
            {
                "name": "Dana",
                "summary_text": "Built the API.",
                "commit_count": 8,
                "commit_refs": [{"sha": "f1a2b3c", "branch": "main"}],
            }
        ]
        html = _build_product_html("My App", "Narrative.", [], contributor_summaries=contribs)
        assert "Dana" in html
        assert "Built the API." in html
        assert "f1a2b3c" in html
        assert "Progress Review" in html

    def test_product_html_without_contributor_summaries(self) -> None:
        html = _build_product_html("My App", "Narrative.", [], contributor_summaries=None)
        assert "Progress Review" not in html


# ---------------------------------------------------------------------------
# ContributorSummarizer — output parsing
# ---------------------------------------------------------------------------


class TestContributorSummarizer:
    """Tests for the ContributorSummarizer parse/build logic."""

    def test_parse_output_single_contributor(self) -> None:
        from app.services.progress.summarizer import ContributorSummarizer

        summarizer = ContributorSummarizer()
        raw = (
            "CONTRIBUTOR: Alice\n"
            "Implemented OAuth login with Google and GitHub providers [a1b2c3d]. "
            "Also fixed a session timeout bug [e4f5a6b]."
        )
        result = summarizer.parse_output(raw)

        assert len(result.items) == 1
        assert result.items[0].name == "Alice"
        assert "OAuth" in result.items[0].summary_text
        assert len(result.items[0].commit_refs) == 2
        assert result.items[0].commit_refs[0]["sha"] == "a1b2c3d"
        assert result.items[0].commit_refs[1]["sha"] == "e4f5a6b"

    def test_parse_output_multiple_contributors(self) -> None:
        from app.services.progress.summarizer import ContributorSummarizer

        summarizer = ContributorSummarizer()
        raw = (
            "CONTRIBUTOR: Alice\n"
            "Built the auth system [a1b2c3d].\n"
            "\n"
            "CONTRIBUTOR: Bob\n"
            "Fixed database migrations [f7a8b9c]."
        )
        result = summarizer.parse_output(raw)

        assert len(result.items) == 2
        assert result.items[0].name == "Alice"
        assert result.items[1].name == "Bob"
        assert result.items[1].commit_refs[0]["sha"] == "f7a8b9c"

    def test_parse_output_empty_text(self) -> None:
        from app.services.progress.summarizer import ContributorSummarizer

        summarizer = ContributorSummarizer()
        result = summarizer.parse_output("")

        assert len(result.items) == 0

    def test_parse_output_no_sha_refs(self) -> None:
        from app.services.progress.summarizer import ContributorSummarizer

        summarizer = ContributorSummarizer()
        raw = "CONTRIBUTOR: Charlie\nDid some work without specific commits."
        result = summarizer.parse_output(raw)

        assert len(result.items) == 1
        assert result.items[0].name == "Charlie"
        assert result.items[0].commit_refs == []

    def test_build_item_extracts_sha_refs(self) -> None:
        from app.services.progress.summarizer import ContributorSummarizer

        summarizer = ContributorSummarizer()
        item = summarizer._build_item("Alice", ["Shipped OAuth [a1b2c3d] and SSO [e4f5a6b]."])

        assert item.name == "Alice"
        assert len(item.commit_refs) == 2
        assert item.commit_refs[0] == {"sha": "a1b2c3d", "branch": ""}
        assert item.commit_refs[1] == {"sha": "e4f5a6b", "branch": ""}
        # Stats are zero — caller fills them in
        assert item.commit_count == 0

    @pytest.mark.asyncio
    async def test_interpret_empty_contributors(self) -> None:
        """Empty contributor list returns immediately without calling AI."""
        from app.services.progress.summarizer import ContributorInput, ContributorSummarizer

        summarizer = ContributorSummarizer()
        result = await summarizer.interpret(
            ContributorInput(period="7d", product_name="Test", contributors=[])
        )

        assert result.items == []

    def test_format_input_caps_at_5_contributors(self) -> None:
        from app.services.progress.summarizer import (
            ContributorCommitData,
            ContributorInput,
            ContributorSummarizer,
        )

        summarizer = ContributorSummarizer()
        contributors = [
            ContributorCommitData(
                name=f"Dev{i}",
                commits=[{"message": "fix", "sha": f"sha{i}abc"}],
                commit_count=1,
            )
            for i in range(8)
        ]
        text = summarizer.format_input(
            ContributorInput(period="7d", product_name="App", contributors=contributors)
        )

        assert "Dev4" in text
        assert "Dev5" not in text  # 6th contributor omitted

    def test_format_input_caps_at_10_commits_per_contributor(self) -> None:
        from app.services.progress.summarizer import (
            ContributorCommitData,
            ContributorInput,
            ContributorSummarizer,
        )

        summarizer = ContributorSummarizer()
        # Use 7-char hex SHAs since format_input truncates to [:7]
        commits = [{"message": f"commit {i}", "sha": f"a{i:02d}b{i:02d}c"} for i in range(15)]
        contributors = [ContributorCommitData(name="Alice", commits=commits, commit_count=15)]
        text = summarizer.format_input(
            ContributorInput(period="7d", product_name="App", contributors=contributors)
        )

        assert "commit 9" in text  # 10th commit present
        assert "commit 10" not in text  # 11th commit omitted
        assert "and 5 more commits" in text
