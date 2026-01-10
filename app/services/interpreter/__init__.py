"""Modular message interpretation service.

This package provides a generic framework for converting unstructured
user messages into structured, actionable tickets. It's designed to be:

1. Reusable across different input sources (feedback, email, chat)
2. Extractable to other projects
3. Extensible for custom output formats

Quick start:
    from app.services.interpreter import MessageToTicketInterpreter, MessageInput

    interpreter = MessageToTicketInterpreter()
    result = await interpreter.interpret(MessageInput(
        content="The submit button doesn't work on mobile",
        title="Mobile bug",
        source="support_chat",
    ))
    print(result.summary)  # Actionable dev ticket summary
"""

from .base import BaseInterpreter, MessageToTicketInterpreter
from .feedback import FeedbackInterpreter
from .types import MessageInput, TicketOutput

__all__ = [
    "MessageInput",
    "TicketOutput",
    "BaseInterpreter",
    "MessageToTicketInterpreter",
    "FeedbackInterpreter",
]
