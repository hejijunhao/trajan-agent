"""Input/output types for message interpretation.

These types are designed to be source-agnostic, enabling reuse across
different input channels (feedback forms, emails, chat messages, etc.).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MessageInput:
    """Generic input for any message-to-ticket interpretation.

    Designed to be source-agnostic: works for feedback forms, emails,
    chat messages, or any user input that needs interpretation.
    """

    # Core content
    content: str  # The main user message/description
    title: str | None = None  # Optional subject/title

    # Structured metadata (source-specific)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Examples:
    #   feedback: {"type": "bug", "tags": ["ui"], "severity": "high"}
    #   email: {"from": "user@example.com", "subject": "..."}
    #   chat: {"channel": "#support", "thread_id": "..."}

    # Context
    source: str = "unknown"  # "feedback_modal", "email", "slack", etc.
    source_url: str | None = None  # Where the message originated
    user_id: str | None = None  # Who sent it (if known)
    user_email: str | None = None  # User's email (for follow-up)
    timestamp: datetime | None = None  # When it was sent


@dataclass
class TicketOutput:
    """Structured output from interpretation - a dev-ready ticket.

    This is the "interpreted" version of user input, ready for
    engineering consumption or automation.
    """

    # Core ticket fields
    summary: str  # 2-3 sentence actionable summary
    ticket_type: str = "task"  # "bug", "feature", "task", "question"
    priority: str = "medium"  # "low", "medium", "high", "critical"

    # Optional enrichment
    suggested_labels: list[str] = field(default_factory=list)
    suggested_assignee: str | None = None  # If determinable from content
    acceptance_criteria: list[str] = field(default_factory=list)

    # Metadata
    confidence: float = 1.0  # 0-1, how confident the interpretation is
    raw_response: str | None = None  # Full LLM response for debugging
