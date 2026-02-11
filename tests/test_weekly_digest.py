"""
Tests for the weekly digest email job.

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
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email.weekly_digest import (
    WeeklyDigestReport,
    _build_email_html,
    _build_plain_text,
    _build_product_html,
    send_weekly_digests,
)


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
    return prefs


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


def _make_mock_summary(text: str = "Great progress this week.") -> MagicMock:
    """Create a mock ProgressSummary."""
    summary = MagicMock()
    summary.summary_text = text
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
        mock_settings.postmark_enabled = True
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
        mock_settings.postmark_enabled = True
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
        mock_settings.postmark_enabled = True
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
        mock_settings.postmark_enabled = True
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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
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

        prefs = _make_mock_prefs(
            digest_product_ids=[str(product_a.id), str(product_b.id)]
        )

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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
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
        mock_shipped_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_shipped()
        )

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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
        mock_postmark.batch.return_value.__aenter__ = AsyncMock(return_value=mock_postmark)
        mock_postmark.batch.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_postmark.send = AsyncMock(return_value=False)  # all sends fail

        product = _make_mock_product("Fail Project")
        mock_get_products.return_value = [product]

        mock_progress_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_summary("Some progress")
        )
        mock_shipped_ops.get_by_product_period = AsyncMock(
            return_value=_make_mock_shipped()
        )

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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
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

        prefs = _make_mock_prefs(
            digest_product_ids=[str(product_a.id), str(product_b.id)]
        )

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
        mock_settings.postmark_enabled = True
        mock_settings.frontend_url = "https://app.trajancloud.com"
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
        db.execute = AsyncMock(
            return_value=_mock_scalars_result([membership])
        )

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
        html = _build_email_html(["<div>Section</div>"], "https://app.trajancloud.com")
        assert "settings/general" in html
        assert "Unsubscribe" in html

    def test_email_html_contains_open_trajan_link(self) -> None:
        html = _build_email_html(["<div>Section</div>"], "https://app.trajancloud.com")
        assert "https://app.trajancloud.com" in html
        assert "Open Trajan" in html

    def test_plain_text_contains_product_data(self) -> None:
        data = [("My App", "Good week", [{"description": "New feature", "category": "feature"}])]
        text = _build_plain_text(data)
        assert "My App" in text
        assert "Good week" in text
        assert "[feature] New feature" in text

    def test_plain_text_caps_at_8_items(self) -> None:
        items = [{"description": f"Item {i}", "category": "fix"} for i in range(10)]
        text = _build_plain_text([("App", "Narrative", items)])
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
