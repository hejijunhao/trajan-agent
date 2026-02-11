"""Weekly digest email job.

Sends a weekly summary of project progress to users who opted in.
Fires every hour; filters to users whose local time matches their
configured digest_hour on the configured digest day.
Reads pre-cached ProgressSummary and DashboardShippedSummary data —
zero AI cost at send time.
"""

import logging
import time
import uuid as uuid_pkg
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape as html_escape
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.domain.dashboard_shipped_operations import dashboard_shipped_ops
from app.domain.progress_summary_operations import progress_summary_ops
from app.models.organization import OrganizationMember
from app.models.product import Product
from app.models.user_preferences import UserPreferences
from app.services.email.postmark import postmark_service

logger = logging.getLogger(__name__)

PERIOD = "7d"


@dataclass
class WeeklyDigestReport:
    """Result summary for logging and the manual trigger endpoint."""

    users_checked: int = 0
    users_emailed: int = 0
    emails_sent: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    skipped_reasons: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Email template
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "feature": "New",
    "fix": "Fix",
    "improvement": "Improved",
    "refactor": "Refactor",
    "docs": "Docs",
    "infra": "Infra",
    "security": "Security",
}


def _build_product_html(product_name: str, narrative: str, items: list[dict]) -> str:
    """Render one product block for the HTML email."""
    items_html = ""
    for item in items[:8]:  # Cap at 8 items to keep email compact
        cat = item.get("category", "")
        label = CATEGORY_LABELS.get(cat, cat.capitalize()) if cat else ""
        badge = (
            f'<span style="display:inline-block;background:#f1f5f9;color:#475569;'
            f'font-size:11px;padding:1px 6px;border-radius:3px;margin-right:6px;">'
            f"{label}</span>"
            if label
            else ""
        )
        items_html += f'<li style="margin:4px 0;font-size:14px;color:#334155;">{badge}{html_escape(item.get("description", ""))}</li>\n'

    overflow = ""
    if len(items) > 8:
        overflow = f'<p style="font-size:12px;color:#94a3b8;margin:4px 0 0;">… and {len(items) - 8} more</p>'

    return f"""
    <div style="margin-bottom:24px;">
      <h2 style="font-size:16px;font-weight:600;color:#0f172a;margin:0 0 6px;">{html_escape(product_name)}</h2>
      <p style="font-size:14px;color:#475569;margin:0 0 10px;line-height:1.5;">{html_escape(narrative)}</p>
      {f'<ul style="list-style:none;padding:0;margin:0 0 4px;">{items_html}</ul>{overflow}' if items_html else ""}
    </div>"""


def _build_email_html(product_sections: list[str], frontend_url: str) -> str:
    """Build the full HTML email body from pre-rendered product sections."""
    sections_html = "\n".join(product_sections)

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:480px;margin:0 auto;padding:24px 16px;">
    <div style="margin-bottom:20px;">
      <h1 style="font-size:18px;font-weight:700;color:#0f172a;margin:0;">Weekly Progress</h1>
      <p style="font-size:13px;color:#94a3b8;margin:4px 0 0;">Your projects this week</p>
    </div>
    <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:20px;">
{sections_html}
    </div>
    <div style="margin-top:16px;text-align:center;">
      <a href="{frontend_url}" style="font-size:13px;color:#c2410c;text-decoration:none;">Open Trajan</a>
      <p style="font-size:11px;color:#cbd5e1;margin:8px 0 0;">
        You're receiving this because you enabled weekly digests.
        <a href="{frontend_url}/settings/general" style="color:#94a3b8;">Unsubscribe</a>
      </p>
    </div>
  </div>
</body>
</html>"""

    return html_body


def _build_plain_text(product_data: list[tuple[str, str, list[dict]]]) -> str:
    """Build a plain-text fallback from the same data."""
    lines = ["Weekly Progress — Your projects this week", "=" * 44, ""]
    for name, narrative, items in product_data:
        lines.append(f"## {name}")
        lines.append(narrative)
        for item in items[:8]:
            cat = item.get("category", "")
            prefix = f"[{cat}] " if cat else ""
            lines.append(f"  - {prefix}{item.get('description', '')}")
        if len(items) > 8:
            lines.append(f"  … and {len(items) - 8} more")
        lines.append("")
    lines.append(f"Open Trajan: {settings.frontend_url}")
    lines.append(f"Unsubscribe: {settings.frontend_url}/settings/general")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core job logic
# ---------------------------------------------------------------------------


async def _get_user_products(db: AsyncSession, user_id: uuid_pkg.UUID) -> list[Product]:
    """Get all products across the user's organization memberships."""
    stmt = (
        select(OrganizationMember)
        .where(OrganizationMember.user_id == user_id)  # type: ignore[arg-type]
        .options(selectinload(OrganizationMember.organization))  # type: ignore[arg-type]
    )
    result = await db.execute(stmt)
    memberships = list(result.scalars().all())

    products: list[Product] = []
    seen_ids: set[uuid_pkg.UUID] = set()

    for membership in memberships:
        org = membership.organization
        if not org:
            continue
        stmt2 = select(Product).where(
            Product.organization_id == org.id  # type: ignore[arg-type]
        )
        result2 = await db.execute(stmt2)
        for product in result2.scalars().all():
            if product.id not in seen_ids:
                products.append(product)
                seen_ids.add(product.id)

    return products


async def _send_digest_for_user(
    db: AsyncSession,
    prefs: UserPreferences,
    user_email: str,
    report: WeeklyDigestReport,
) -> None:
    """Build and send the digest email for a single user."""
    # Resolve products
    all_products = await _get_user_products(db, prefs.user_id)

    # Filter by digest_product_ids if set
    if prefs.digest_product_ids:
        selected = {str(pid) for pid in prefs.digest_product_ids}
        products = [p for p in all_products if str(p.id) in selected]
    else:
        products = all_products

    if not products:
        report.skipped_reasons["no_products"] = report.skipped_reasons.get("no_products", 0) + 1
        return

    # Gather cached progress data per product
    product_data: list[tuple[str, str, list[dict]]] = []  # (name, narrative, items)

    for product in products:
        summary = await progress_summary_ops.get_by_product_period(db, product.id, PERIOD)
        shipped = await dashboard_shipped_ops.get_by_product_period(db, product.id, PERIOD)

        narrative = summary.summary_text if summary else ""
        items = shipped.items if shipped and shipped.has_significant_changes else []

        # Skip products with no cached data (no activity that week)
        if not narrative and not items:
            continue

        product_data.append((product.name or "Untitled Project", narrative, items))

    if not product_data:
        report.skipped_reasons["no_activity"] = report.skipped_reasons.get("no_activity", 0) + 1
        return

    # Decide: consolidated email or per-project emails
    if prefs.digest_product_ids:
        # Per-project mode: one email per product
        emails_sent_for_user = 0
        for name, narrative, items in product_data:
            section = _build_product_html(name, narrative, items)
            html_body = _build_email_html([section], settings.frontend_url)
            text_body = _build_plain_text([(name, narrative, items)])

            sent = await postmark_service.send(
                to=user_email,
                subject=f"Weekly: {name}",
                html_body=html_body,
                text_body=text_body,
            )
            if sent:
                report.emails_sent += 1
                emails_sent_for_user += 1
            else:
                report.errors += 1
    else:
        # Consolidated mode: all projects in one email
        sections = [
            _build_product_html(name, narrative, items) for name, narrative, items in product_data
        ]
        html_body = _build_email_html(sections, settings.frontend_url)
        text_body = _build_plain_text(product_data)
        emails_sent_for_user = 0

        sent = await postmark_service.send(
            to=user_email,
            subject="Your Weekly Progress",
            html_body=html_body,
            text_body=text_body,
        )
        if sent:
            report.emails_sent += 1
            emails_sent_for_user += 1
        else:
            report.errors += 1

    if emails_sent_for_user > 0:
        report.users_emailed += 1


async def send_weekly_digests(db: AsyncSession) -> WeeklyDigestReport:
    """Main entry point: send weekly digest emails to eligible users.

    Called hourly by the scheduler. Filters to users whose local time
    matches their configured digest_hour on the configured digest day.
    Also callable via the manual trigger endpoint.
    """
    report = WeeklyDigestReport()
    start = time.monotonic()

    if not settings.postmark_enabled:
        logger.warning("[weekly-digest] Skipped — Postmark not configured")
        report.duration_seconds = time.monotonic() - start
        return report

    # Find all users with weekly digest enabled, eagerly load User for email
    stmt = (
        select(UserPreferences)
        .where(UserPreferences.email_digest == "weekly")  # type: ignore[arg-type]
        .options(selectinload(UserPreferences.user))  # type: ignore[arg-type]
    )
    result = await db.execute(stmt)
    weekly_prefs = list(result.scalars().all())

    report.users_checked = len(weekly_prefs)
    logger.info(f"[weekly-digest] Found {len(weekly_prefs)} users with weekly digest enabled")

    # Filter to users whose local time matches right now
    now_utc = datetime.now(UTC)
    target_day = settings.weekly_digest_day  # e.g. "fri"

    eligible: list[UserPreferences] = []
    for prefs in weekly_prefs:
        try:
            tz = ZoneInfo(prefs.digest_timezone or "UTC")
        except (KeyError, ValueError):
            tz = ZoneInfo("UTC")
        local_now = now_utc.astimezone(tz)
        day_abbrev = local_now.strftime("%a").lower()  # "mon", "tue", …, "fri"
        if day_abbrev == target_day and local_now.hour == (
            prefs.digest_hour if prefs.digest_hour is not None else 17
        ):
            eligible.append(prefs)

    logger.info(f"[weekly-digest] {len(eligible)} users eligible for current hour")

    if not eligible:
        report.duration_seconds = round(time.monotonic() - start, 2)
        return report

    async with postmark_service.batch():
        for prefs in eligible:
            user = prefs.user
            if not user or not user.email:
                report.skipped_reasons["no_email"] = report.skipped_reasons.get("no_email", 0) + 1
                continue

            try:
                await _send_digest_for_user(db, prefs, user.email, report)
            except Exception:
                logger.exception(f"[weekly-digest] Error processing user {prefs.user_id}")
                report.errors += 1

    report.duration_seconds = round(time.monotonic() - start, 2)

    logger.info(
        f"[weekly-digest] Done: {report.users_emailed} emailed, "
        f"{report.emails_sent} emails sent, {report.errors} errors, "
        f"{report.duration_seconds}s"
    )

    return report
