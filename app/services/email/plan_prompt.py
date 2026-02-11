"""Plan selection prompt email job.

Periodically emails org owners/admins whose organization has no plan selected
(plan_tier="none", status="pending"), nudging them to pick a plan.

Uses the shared PostmarkService for delivery. Frequency is configurable via
PLAN_PROMPT_FREQUENCY_DAYS (default: 3 days between emails per org).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape as html_escape

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models.organization import MemberRole, Organization, OrganizationMember
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus
from app.models.user import User
from app.services.email.postmark import postmark_service

logger = logging.getLogger(__name__)


@dataclass
class PlanPromptReport:
    """Summary of a plan-prompt email run."""

    orgs_checked: int = 0
    orgs_emailed: int = 0
    emails_sent: int = 0
    errors: list[str] = field(default_factory=list)


def _build_html(org_name: str, cta_url: str) -> str:
    """Build the HTML email body."""
    safe_name = html_escape(org_name)
    return f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #f4f4f5;
             font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background-color: #f4f4f5;">
    <tr>
      <td align="center" style="padding: 40px 16px;">

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width: 520px; background-color: #ffffff;
                      border-radius: 8px; overflow: hidden;
                      box-shadow: 0 4px 24px rgba(0,0,0,0.08);">

          <!-- Accent bar -->
          <tr>
            <td style="background: linear-gradient(135deg, #c2410c 0%, #ea580c 100%);
                       height: 4px; font-size: 0; line-height: 0;">&nbsp;</td>
          </tr>

          <!-- Header -->
          <tr>
            <td style="background-color: #18181b; padding: 20px 32px; text-align: center;">
              <span style="font-size: 15px; font-weight: 600; color: #fafafa;
                           letter-spacing: 1.5px;">
                TRAJAN
              </span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding: 36px 32px 32px;">

              <!-- Status pill -->
              <table role="presentation" cellpadding="0" cellspacing="0"
                     style="margin: 0 0 20px;">
                <tr>
                  <td style="background-color: #fef2f2; border: 1px solid #fecaca;
                             border-radius: 20px; padding: 5px 14px;">
                    <span style="font-size: 12px; font-weight: 600; color: #dc2626;
                                 letter-spacing: 0.3px;">
                      &#9679;&ensp;WORKSPACE PAUSED
                    </span>
                  </td>
                </tr>
              </table>

              <h1 style="font-size: 22px; font-weight: 700; color: #18181b;
                         margin: 0 0 10px; line-height: 1.3;">
                {safe_name} is waiting on you
              </h1>
              <p style="font-size: 15px; color: #52525b; margin: 0 0 24px; line-height: 1.6;">
                Your workspace is connected but key features are on hold
                until you activate a plan. Here's what's ready to go the
                moment you do:
              </p>

              <!-- Feature rows -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="margin: 0 0 8px;">
                <tr>
                  <td style="padding: 12px 16px; background-color: #fafafa;
                             border-radius: 6px;">
                    <span style="font-size: 14px; color: #18181b; font-weight: 600;">
                      &#128214;&ensp;Auto-generated docs
                    </span>
                    <br>
                    <span style="font-size: 13px; color: #71717a; line-height: 1.5;">
                      Changelogs, blueprints &amp; architecture &mdash; built from your repos automatically
                    </span>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="margin: 0 0 8px;">
                <tr>
                  <td style="padding: 12px 16px; background-color: #fafafa;
                             border-radius: 6px;">
                    <span style="font-size: 14px; color: #18181b; font-weight: 600;">
                      &#128200;&ensp;Weekly progress insights
                    </span>
                    <br>
                    <span style="font-size: 13px; color: #71717a; line-height: 1.5;">
                      AI-powered summaries of what shipped, who contributed &amp; velocity trends
                    </span>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="margin: 0 0 28px;">
                <tr>
                  <td style="padding: 12px 16px; background-color: #fafafa;
                             border-radius: 6px;">
                    <span style="font-size: 14px; color: #18181b; font-weight: 600;">
                      &#128101;&ensp;Team collaboration
                    </span>
                    <br>
                    <span style="font-size: 13px; color: #71717a; line-height: 1.5;">
                      Invite your team, share project context &amp; manage access in one place
                    </span>
                  </td>
                </tr>
              </table>

              <!-- Primary CTA -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="border-radius: 8px;
                                   background: linear-gradient(135deg, #c2410c 0%, #ea580c 100%);
                                   box-shadow: 0 2px 8px rgba(194, 65, 12, 0.3);">
                          <a href="{cta_url}"
                             style="display: inline-block; padding: 16px 48px;
                                    font-size: 16px; font-weight: 600; color: #ffffff;
                                    text-decoration: none; border-radius: 8px;
                                    letter-spacing: 0.2px;">
                            Activate Your Workspace &rarr;
                          </a>
                        </td>
                      </tr>
                    </table>
                    <p style="font-size: 12px; color: #a1a1aa; margin: 10px 0 0;">
                      From $49/mo &middot; takes 30 seconds
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 20px 32px; border-top: 1px solid #f4f4f5;
                       background-color: #fafafa;">
              <p style="font-size: 12px; color: #a1a1aa; margin: 0; line-height: 1.5;
                        text-align: center;">
                You're receiving this as an admin of {safe_name} on Trajan.<br>
                These emails stop automatically once you activate a plan.
              </p>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""


def _build_text(org_name: str, cta_url: str) -> str:
    """Build the plain-text email body."""
    return (
        f"TRAJAN\n"
        f"{'=' * 40}\n\n"
        f"⏸ WORKSPACE PAUSED\n\n"
        f"{org_name} is waiting on you.\n\n"
        f"Your workspace is connected but key features are on hold until "
        f"you activate a plan. Here's what's ready to go:\n\n"
        f"  📖 Auto-generated docs — changelogs, blueprints & architecture from your repos\n"
        f"  📈 Weekly progress insights — AI summaries of what shipped & velocity trends\n"
        f"  👥 Team collaboration — invite your team & manage access in one place\n\n"
        f"Activate your workspace (from $49/mo, takes 30 seconds):\n"
        f"{cta_url}\n\n"
        f"---\n"
        f"You're receiving this as an admin of {org_name} on Trajan.\n"
        f"These emails stop automatically once you activate a plan."
    )


async def send_plan_selection_prompts(db: AsyncSession) -> PlanPromptReport:
    """
    Find orgs without a plan and email their owners/admins.

    Steps:
      1. Query orgs where subscription plan_tier="none" AND status="pending".
      2. Skip orgs emailed within plan_prompt_frequency_days.
      3. For each eligible org, fetch owner/admin emails and send.
      4. Stamp org.settings["last_plan_prompt_sent_at"] after sending.
    """
    report = PlanPromptReport()

    # --- Step 1: find orgs with no plan ---
    stmt = (
        select(Organization)
        .join(Subscription, Subscription.organization_id == Organization.id)
        .where(Subscription.plan_tier == PlanTier.NONE.value)
        .where(Subscription.status == SubscriptionStatus.PENDING.value)
    )
    orgs = (await db.execute(stmt)).scalars().all()
    report.orgs_checked = len(orgs)

    if not orgs:
        logger.info("[plan-prompt] No orgs without a plan — nothing to send")
        return report

    # --- Step 2: filter by frequency ---
    cutoff = datetime.now(UTC) - timedelta(days=settings.plan_prompt_frequency_days)
    eligible: list[Organization] = []

    for org in orgs:
        last_sent_str = (org.settings or {}).get("last_plan_prompt_sent_at")
        if last_sent_str:
            try:
                last_sent = datetime.fromisoformat(last_sent_str)
                if last_sent > cutoff:
                    logger.debug(f"[plan-prompt] Skipping {org.name} (emailed recently)")
                    continue
            except (ValueError, TypeError):
                pass  # corrupt value — treat as never sent
        eligible.append(org)

    if not eligible:
        logger.info(
            f"[plan-prompt] {report.orgs_checked} orgs checked, "
            f"all emailed recently — nothing to send"
        )
        return report

    # --- Step 3: send emails per org ---
    cta_base = settings.frontend_url.rstrip("/")

    for org in eligible:
        # Fetch owner/admin members with emails
        member_stmt = (
            select(User.email)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == org.id)
            .where(
                OrganizationMember.role.in_(  # type: ignore[union-attr]
                    [MemberRole.OWNER.value, MemberRole.ADMIN.value]
                )
            )
            .where(User.email.is_not(None))  # type: ignore[union-attr]
        )
        emails = (await db.execute(member_stmt)).scalars().all()

        if not emails:
            logger.debug(f"[plan-prompt] {org.name}: no admin/owner emails found")
            continue

        cta_url = f"{cta_base}/settings/billing"
        subject = f"{org.name} — your workspace is waiting"
        html_body = _build_html(org.name, cta_url)
        text_body = _build_text(org.name, cta_url)

        org_sent = 0
        for email in emails:
            sent = await postmark_service.send(
                to=email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
            if sent:
                org_sent += 1
            else:
                report.errors.append(f"Failed to send to {email} (org: {org.name})")

        if org_sent > 0:
            report.orgs_emailed += 1
            report.emails_sent += org_sent

            # --- Step 4: stamp last-sent timestamp ---
            if org.settings is None:
                org.settings = {}
            org.settings["last_plan_prompt_sent_at"] = datetime.now(UTC).isoformat()
            flag_modified(org, "settings")

        logger.info(f"[plan-prompt] {org.name}: sent {org_sent}/{len(emails)} emails")

    logger.info(
        f"[plan-prompt] Done — checked {report.orgs_checked}, "
        f"emailed {report.orgs_emailed} orgs, "
        f"{report.emails_sent} emails sent, "
        f"{len(report.errors)} errors"
    )
    return report
