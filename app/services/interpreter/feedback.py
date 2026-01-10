"""Feedback-specific interpreter adapter.

Thin wrapper that adapts the Feedback model to the generic
MessageToTicketInterpreter, keeping both independently reusable.
"""

from app.models.feedback import Feedback

from .base import MessageToTicketInterpreter
from .types import MessageInput


class FeedbackInterpreter:
    """Thin wrapper that adapts Feedback model to generic interpreter.

    This keeps the Feedback model decoupled from the interpreter internals,
    making both independently reusable.
    """

    def __init__(self) -> None:
        self._interpreter = MessageToTicketInterpreter()

    async def interpret(self, feedback: Feedback) -> str:
        """Convert Feedback to MessageInput, interpret, return summary.

        Args:
            feedback: The Feedback model instance to interpret.

        Returns:
            The AI-generated summary string for storage in ai_summary column.
        """
        # Adapt Feedback -> MessageInput
        message_input = MessageInput(
            content=feedback.description,
            title=feedback.title,
            metadata={
                "type": feedback.type,
                "tags": feedback.tags or [],
                "severity": feedback.severity,
            },
            source="feedback_modal",
            source_url=feedback.page_url,
            user_id=str(feedback.user_id),
            timestamp=feedback.created_at,
        )

        # Interpret
        ticket = await self._interpreter.interpret(message_input)

        # Return the summary (stored in ai_summary column)
        return ticket.summary
