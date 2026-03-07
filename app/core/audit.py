"""Structured audit logging for security-relevant events.

Logs are emitted as structured JSON via Python logging.
Ship these to your log aggregator for querying.

This is NOT a database-backed audit trail — it's application logging
with consistent fields for security review.
"""

import logging
from uuid import UUID

logger = logging.getLogger("audit")


def log_token_resolved(user_id: UUID, repository: str, method: str) -> None:
    """Log which token method was used to access a repo."""
    logger.info(
        "token_resolved",
        extra={
            "user_id": str(user_id),
            "repository": repository,
            "method": method,
        },
    )


def log_installation_event(action: str, installation_id: int, org_id: str | None = None) -> None:
    """Log GitHub App installation lifecycle events."""
    logger.info(
        "github_app_event",
        extra={
            "action": action,
            "installation_id": installation_id,
            "organization_id": org_id,
        },
    )


def log_webhook_received(event: str, action: str | None) -> None:
    """Log incoming webhook events."""
    logger.info(
        "webhook_received",
        extra={"event": event, "action": action},
    )
