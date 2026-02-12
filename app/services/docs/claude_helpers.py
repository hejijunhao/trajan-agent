"""Shared constants and utilities for Claude-powered doc service agents.

Centralizes model selection, retry configuration, and the retry loop
that was previously duplicated across document_generator, custom_generator,
document_refresher, blueprint_agent, and documentation_planner.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from anthropic import APIError, RateLimitError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------
MODEL_OPUS = "claude-opus-4-20250514"
MODEL_SONNET = "claude-sonnet-4-20250514"

# Document types that benefit from Opus's deeper reasoning
COMPLEX_DOC_TYPES = {"architecture", "concept"}

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]

T = TypeVar("T")


def select_model(doc_type: str) -> str:
    """Select the appropriate Claude model based on document complexity.

    Opus for architecture and concept docs (need deeper reasoning).
    Sonnet for overview, guide, and reference docs (more straightforward).
    """
    if doc_type in COMPLEX_DOC_TYPES:
        return MODEL_OPUS
    return MODEL_SONNET


async def call_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    operation_name: str = "API call",
) -> T:
    """Execute an async function with retry on Anthropic rate-limit / API errors.

    Args:
        fn: Zero-arg async callable that performs the API call.
        operation_name: Label for log messages (e.g. "Document generation").

    Returns:
        The value returned by *fn* on a successful attempt.

    Raises:
        The last caught exception after all retries are exhausted,
        or RuntimeError if no exception was captured.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            return await fn()
        except (RateLimitError, APIError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    f"{operation_name} error (attempt {attempt + 1}/{MAX_RETRIES}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"{operation_name} failed after {MAX_RETRIES} attempts: {e}"
                )

    raise last_error or RuntimeError(f"{operation_name} failed after retries")
