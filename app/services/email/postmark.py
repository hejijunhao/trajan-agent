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
                    POSTMARK_API_URL, json=payload, headers=headers,
                )
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        POSTMARK_API_URL, json=payload, headers=headers,
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

    _shared_client: httpx.AsyncClient | None = None


postmark_service = PostmarkService()
