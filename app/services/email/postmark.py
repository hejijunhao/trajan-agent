"""Thin Postmark client for transactional email delivery.

Uses Postmark's REST API directly via httpx — no SDK needed.
Reusable by any feature that sends product emails (plan prompts, weekly digests, etc.).
Auth-related emails (invites, password reset) remain with Supabase.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

POSTMARK_API_URL = "https://api.postmarkapp.com/email"
POSTMARK_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}


class PostmarkService:
    """Send transactional emails via Postmark's REST API."""

    @asynccontextmanager
    async def batch(self) -> AsyncIterator["PostmarkService"]:
        """Context manager that holds an HTTP client open for multiple sends.

        Usage::

            async with postmark_service.batch() as pm:
                await pm.send(to="a@b.com", ...)
                await pm.send(to="c@d.com", ...)
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            self._shared_client = client
            try:
                yield self
            finally:
                self._shared_client = None

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        """
        Send a single transactional email.

        Returns True on success, False on failure (logs the error, never raises).
        When called inside a `batch()` context, reuses the shared HTTP client.
        """
        if not settings.postmark_enabled:
            logger.warning("[postmark] Skipped (POSTMARK_API_KEY not configured)")
            return False

        payload = {
            "From": settings.postmark_from_email,
            "To": to,
            "Subject": subject,
            "HtmlBody": html_body,
            "TextBody": text_body,
            "MessageStream": "outbound",
        }

        headers = {
            **POSTMARK_HEADERS,
            "X-Postmark-Server-Token": settings.postmark_api_key,
        }

        try:
            client = getattr(self, "_shared_client", None)
            if client:
                response = await client.post(
                    POSTMARK_API_URL,
                    json=payload,
                    headers=headers,
                )
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        POSTMARK_API_URL,
                        json=payload,
                        headers=headers,
                    )
            response.raise_for_status()
            logger.info(f"[postmark] Sent to {to}: {subject}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[postmark] HTTP {e.response.status_code} sending to {to}: {e.response.text}"
            )
            return False
        except httpx.RequestError as e:
            logger.error(f"[postmark] Request failed sending to {to}: {e}")
            return False

    async def send_team_invite(
        self,
        to: str,
        inviter_name: str | None,
        org_name: str | None,
        magic_link: str,
    ) -> bool:
        """Send a team invite email with an embedded magic link.

        Used when the invited user already has a Supabase auth account,
        so `invite_user_by_email` can't be used.

        Returns True on success, False on failure (never raises).
        """
        inviter = inviter_name or "A team member"
        workspace = org_name or "a workspace"

        subject = f"{inviter} invited you to {workspace} on Trajan"

        html_body = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 0;">
  <h2 style="margin: 0 0 16px;">You've been invited to {workspace}</h2>
  <p style="color: #374151; line-height: 1.6; margin: 0 0 8px;">
    {inviter} has invited you to join <strong>{workspace}</strong> on Trajan.
  </p>
  <p style="color: #374151; line-height: 1.6; margin: 0 0 24px;">
    You already have an account — clicking the button below will log you in
    and take you to your new workspace.
  </p>
  <a href="{magic_link}"
     style="display: inline-block; background: #c2410c; color: #fff;
            padding: 12px 28px; border-radius: 6px; text-decoration: none;
            font-weight: 600;">
    Join Workspace
  </a>
  <p style="color: #6b7280; font-size: 13px; margin: 24px 0 0;">
    If the button doesn't work, copy and paste this link into your browser:<br/>
    <a href="{magic_link}" style="color: #c2410c;">{magic_link}</a>
  </p>
</div>"""

        text_body = (
            f"{inviter} invited you to {workspace} on Trajan.\n\n"
            f"You already have an account — use the link below to log in "
            f"and access your new workspace:\n\n"
            f"{magic_link}\n"
        )

        return await self.send(to=to, subject=subject, html_body=html_body, text_body=text_body)

    _shared_client: httpx.AsyncClient | None = None


postmark_service = PostmarkService()
