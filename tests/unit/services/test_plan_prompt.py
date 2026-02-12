"""
Tests for the plan-selection prompt email job.

Verifies:
- Correct orgs are selected (plan_tier="none", status="pending")
- Orgs recently emailed are skipped (frequency gating)
- Only owners/admins receive emails
- Organization settings are updated after sending
- Report accurately reflects the run
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email.plan_prompt import (
    PlanPromptReport,
    _build_html,
    _build_text,
    send_plan_selection_prompts,
)


def _make_mock_org(
    name: str = "Test Org",
    settings: dict | None = None,
) -> MagicMock:
    """Create a mock Organization with the fields plan_prompt.py accesses."""
    org = MagicMock()
    org.id = uuid.uuid4()
    org.name = name
    org.settings = settings
    return org


def _mock_scalars_result(values: list) -> MagicMock:
    """Create a mock db.execute() result whose .scalars().all() returns `values`."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


class TestSendPlanSelectionPrompts:
    """Core job logic tests."""

    @pytest.mark.asyncio
    async def test_no_orgs_without_plan(self) -> None:
        """When no orgs match the query, nothing is sent."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        report = await send_plan_selection_prompts(db)

        assert report.orgs_checked == 0
        assert report.orgs_emailed == 0
        assert report.emails_sent == 0
        assert report.errors == []

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_sends_to_eligible_org(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """An org with no plan and never emailed should receive emails."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        mock_org = _make_mock_org(name="Acme Corp", settings=None)
        mock_postmark.send = AsyncMock(return_value=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),  # org query
                _mock_scalars_result(["owner@acme.com"]),  # member query
            ]
        )

        report = await send_plan_selection_prompts(db)

        assert report.orgs_checked == 1
        assert report.orgs_emailed == 1
        assert report.emails_sent == 1
        assert report.errors == []

        # Verify Postmark was called with correct args
        mock_postmark.send.assert_called_once()
        call_kwargs = mock_postmark.send.call_args.kwargs
        assert call_kwargs["to"] == "owner@acme.com"
        assert "Acme Corp" in call_kwargs["subject"]
        assert "settings/billing" in call_kwargs["html_body"]

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_skips_recently_emailed_org(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """An org emailed within frequency_days should be skipped."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        # Org was emailed 1 day ago (within 3-day window)
        recent_timestamp = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        mock_org = _make_mock_org(
            name="Recently Emailed",
            settings={"last_plan_prompt_sent_at": recent_timestamp},
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([mock_org]))

        report = await send_plan_selection_prompts(db)

        assert report.orgs_checked == 1
        assert report.orgs_emailed == 0
        assert report.emails_sent == 0
        mock_postmark.send.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_sends_to_org_past_frequency_window(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """An org emailed longer ago than frequency_days should get a new email."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        # Org was emailed 5 days ago (beyond 3-day window)
        old_timestamp = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        mock_org = _make_mock_org(
            name="Due For Reminder",
            settings={"last_plan_prompt_sent_at": old_timestamp},
        )
        mock_postmark.send = AsyncMock(return_value=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),  # org query
                _mock_scalars_result(["admin@due.com"]),  # member query
            ]
        )

        report = await send_plan_selection_prompts(db)

        assert report.orgs_emailed == 1
        assert report.emails_sent == 1
        mock_postmark.send.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_sends_to_multiple_admins(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """All owners/admins of an eligible org should receive emails."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        mock_org = _make_mock_org(name="Multi Admin Org", settings=None)
        mock_postmark.send = AsyncMock(return_value=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),
                _mock_scalars_result(["owner@org.com", "admin@org.com"]),
            ]
        )

        report = await send_plan_selection_prompts(db)

        assert report.emails_sent == 2
        assert report.orgs_emailed == 1
        assert mock_postmark.send.call_count == 2

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_handles_partial_send_failure(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """If one email fails, the rest still send and errors are recorded."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        mock_org = _make_mock_org(name="Partial Fail Org", settings=None)
        # First send succeeds, second fails
        mock_postmark.send = AsyncMock(side_effect=[True, False])

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),
                _mock_scalars_result(["good@org.com", "bad@org.com"]),
            ]
        )

        report = await send_plan_selection_prompts(db)

        assert report.emails_sent == 1
        assert report.orgs_emailed == 1  # at least 1 email succeeded
        assert len(report.errors) == 1
        assert "bad@org.com" in report.errors[0]

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_skips_org_with_no_admin_emails(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """An org with no owner/admin emails (all null) should be skipped."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        mock_org = _make_mock_org(name="No Emails Org", settings=None)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),
                _mock_scalars_result([]),  # no admin/owner emails
            ]
        )

        report = await send_plan_selection_prompts(db)

        assert report.orgs_checked == 1
        assert report.orgs_emailed == 0
        assert report.emails_sent == 0
        mock_postmark.send.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.flag_modified")
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_updates_settings_after_sending(
        self, mock_settings: MagicMock, mock_postmark: MagicMock, mock_flag: MagicMock
    ) -> None:
        """After sending, org.settings should have last_plan_prompt_sent_at stamped."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        mock_org = _make_mock_org(name="Stamp Test Org", settings=None)
        mock_postmark.send = AsyncMock(return_value=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),
                _mock_scalars_result(["admin@test.com"]),
            ]
        )

        await send_plan_selection_prompts(db)

        # Settings should now be initialized with the timestamp
        assert mock_org.settings is not None
        assert "last_plan_prompt_sent_at" in mock_org.settings

        # Verify the timestamp is a valid ISO datetime
        ts = datetime.fromisoformat(mock_org.settings["last_plan_prompt_sent_at"])
        assert (datetime.now(UTC) - ts).total_seconds() < 5

        # flag_modified must be called for JSONB change detection
        mock_flag.assert_called_once_with(mock_org, "settings")

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.flag_modified")
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_preserves_existing_settings(
        self, mock_settings: MagicMock, mock_postmark: MagicMock, _mock_flag: MagicMock
    ) -> None:
        """Existing settings keys should not be clobbered when stamping."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        existing_settings = {"auto_progress_enabled": True, "custom_key": "value"}
        mock_org = _make_mock_org(name="Existing Settings Org", settings=existing_settings)
        mock_postmark.send = AsyncMock(return_value=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),
                _mock_scalars_result(["admin@test.com"]),
            ]
        )

        await send_plan_selection_prompts(db)

        # Original keys preserved
        assert mock_org.settings["auto_progress_enabled"] is True
        assert mock_org.settings["custom_key"] == "value"
        # New key added
        assert "last_plan_prompt_sent_at" in mock_org.settings

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_handles_corrupt_timestamp_gracefully(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """A corrupt last_plan_prompt_sent_at value should be treated as never sent."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        mock_org = _make_mock_org(
            name="Corrupt Timestamp Org",
            settings={"last_plan_prompt_sent_at": "not-a-date"},
        )
        mock_postmark.send = AsyncMock(return_value=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([mock_org]),
                _mock_scalars_result(["admin@test.com"]),
            ]
        )

        report = await send_plan_selection_prompts(db)

        # Should treat corrupt timestamp as "never sent" and proceed
        assert report.orgs_emailed == 1
        assert report.emails_sent == 1

    @pytest.mark.asyncio
    @patch("app.services.email.plan_prompt.postmark_service")
    @patch("app.services.email.plan_prompt.settings")
    async def test_multiple_orgs_mixed_eligibility(
        self, mock_settings: MagicMock, mock_postmark: MagicMock
    ) -> None:
        """Mix of eligible and ineligible orgs — only eligible ones get emails."""
        mock_settings.plan_prompt_frequency_days = 3
        mock_settings.frontend_url = "https://app.trajancloud.com"

        # Org 1: never emailed (eligible)
        org_eligible = _make_mock_org(name="Eligible Org", settings=None)
        # Org 2: emailed yesterday (ineligible)
        recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        org_recent = _make_mock_org(
            name="Recent Org",
            settings={"last_plan_prompt_sent_at": recent},
        )

        mock_postmark.send = AsyncMock(return_value=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_result([org_eligible, org_recent]),  # org query
                _mock_scalars_result(["admin@eligible.com"]),  # emails for eligible
            ]
        )

        report = await send_plan_selection_prompts(db)

        assert report.orgs_checked == 2
        assert report.orgs_emailed == 1
        assert report.emails_sent == 1


class TestEmailTemplates:
    """Tests for the HTML and text email builders."""

    def test_html_contains_org_name(self) -> None:
        html = _build_html("Acme Corp", "https://app.trajancloud.com/settings/billing")
        assert "Acme Corp" in html

    def test_html_contains_cta_link(self) -> None:
        url = "https://app.trajancloud.com/settings/billing"
        html = _build_html("Acme Corp", url)
        assert url in html

    def test_html_uses_terracotta_accent(self) -> None:
        html = _build_html("Acme Corp", "https://example.com")
        assert "#c2410c" in html

    def test_text_contains_org_name(self) -> None:
        text = _build_text("Acme Corp", "https://app.trajancloud.com/settings/billing")
        assert "Acme Corp" in text

    def test_text_contains_cta_url(self) -> None:
        url = "https://app.trajancloud.com/settings/billing"
        text = _build_text("Acme Corp", url)
        assert url in text

    def test_text_mentions_role_context(self) -> None:
        text = _build_text("Acme Corp", "https://example.com")
        assert "admin" in text

    def test_html_escapes_special_characters(self) -> None:
        """Org names with HTML special chars must be escaped to prevent XSS."""
        html = _build_html('<script>alert("xss")</script> & Co', "https://example.com")
        assert "&lt;script&gt;" in html
        assert "<script>" not in html
        assert "&amp; Co" in html


class TestPlanPromptReport:
    """Tests for the report dataclass."""

    def test_defaults(self) -> None:
        report = PlanPromptReport()
        assert report.orgs_checked == 0
        assert report.orgs_emailed == 0
        assert report.emails_sent == 0
        assert report.errors == []

    def test_error_accumulation(self) -> None:
        report = PlanPromptReport()
        report.errors.append("fail 1")
        report.errors.append("fail 2")
        assert len(report.errors) == 2
