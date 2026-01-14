"""
CustomDocGenerator - Generates custom documentation based on user requests.

This is a standalone generator for custom documentation requests, separate from
the batch documentation orchestrator. It handles single-document, user-initiated
generation with a different progress UX pattern (modal-based vs page-level status).

Key features:
1. Single document generation (not batch)
2. User-specified parameters (doc type, format, audience)
3. Optional file focus for targeted documentation
4. Immediate content return (preview mode) or save to database
5. Progress reporting for background jobs via job store
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import UUID

import anthropic
from anthropic import APIError, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.models.product import Product
from app.models.repository import Repository
from app.services.docs.codebase_analyzer import CodebaseAnalyzer
from app.services.docs.custom_prompts import build_custom_prompt
from app.services.docs.job_store import (
    STAGE_ANALYZING,
    STAGE_FINALIZING,
    STAGE_GENERATING,
    STAGE_PLANNING,
)
from app.services.docs.types import CodebaseContext, CustomDocRequest, CustomDocResult
from app.services.github import GitHubService

logger = logging.getLogger(__name__)

# Model selection
MODEL_OPUS = "claude-opus-4-20250514"
MODEL_SONNET = "claude-sonnet-4-20250514"

# Document types that benefit from Opus's deeper reasoning
COMPLEX_DOC_TYPES = {"technical", "wiki"}

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]

# Generation limits
MAX_TOKENS_GENERATION = 8000


class CustomDocGenerator:
    """
    Generates custom documentation based on user requests.

    Unlike the batch DocumentGenerator, this handles single-document requests
    with user-specified parameters for doc type, format style, and audience.
    """

    def __init__(
        self,
        db: AsyncSession,
        github_service: GitHubService,
    ) -> None:
        self.db = db
        self.github_service = github_service
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate(
        self,
        request: CustomDocRequest,
        product: Product,
        repositories: list[Repository],
        user_id: str | UUID,
        save_immediately: bool = False,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
        cancellation_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> CustomDocResult:
        """
        Generate custom documentation based on user request.

        Args:
            request: The user's custom doc request with all parameters
            product: The product this documentation belongs to
            repositories: Repositories to analyze for context
            user_id: User who owns this document
            save_immediately: If True, save as Document; if False, return content only
            progress_callback: Optional async callback for progress updates (background jobs)
            cancellation_check: Optional async callback to check if job was cancelled

        Returns:
            CustomDocResult with generated content and optionally saved Document
        """
        start_time = time.time()

        async def report_progress(stage: str) -> None:
            """Report progress if callback provided."""
            if progress_callback:
                await progress_callback(stage)

        async def check_cancelled() -> bool:
            """Check if job was cancelled."""
            if cancellation_check:
                return await cancellation_check()
            return False

        try:
            # Step 1: Analyze codebase for context
            if await check_cancelled():
                return CustomDocResult(
                    success=False,
                    error="Cancelled by user",
                    generation_time_seconds=time.time() - start_time,
                )
            await report_progress(STAGE_ANALYZING)
            logger.info(f"Analyzing codebase for custom doc: {request.prompt[:50]}...")
            context = await self._get_codebase_context(repositories, request.focus_paths)

            # Step 2: Plan document structure
            if await check_cancelled():
                return CustomDocResult(
                    success=False,
                    error="Cancelled by user",
                    generation_time_seconds=time.time() - start_time,
                )
            await report_progress(STAGE_PLANNING)

            # Step 3: Generate content using Claude
            if await check_cancelled():
                return CustomDocResult(
                    success=False,
                    error="Cancelled by user",
                    generation_time_seconds=time.time() - start_time,
                )
            await report_progress(STAGE_GENERATING)
            logger.info("Generating custom document content...")
            content, suggested_title = await self._call_claude(request, context)

            # Step 4: Finalize
            if await check_cancelled():
                return CustomDocResult(
                    success=False,
                    error="Cancelled by user",
                    generation_time_seconds=time.time() - start_time,
                )
            await report_progress(STAGE_FINALIZING)

            # Use user's title if provided, otherwise use AI-suggested title
            final_title = request.title or suggested_title or "Untitled Document"

            # Step 3: Optionally save as Document
            document = None
            if save_immediately:
                document = await self._save_document(
                    product=product,
                    user_id=user_id,
                    title=final_title,
                    content=content,
                    doc_type=request.doc_type,
                )

            generation_time = time.time() - start_time
            logger.info(f"Custom document generated in {generation_time:.2f}s")

            return CustomDocResult(
                success=True,
                content=content,
                suggested_title=suggested_title,
                document=document,
                generation_time_seconds=generation_time,
            )

        except Exception as e:
            logger.error(f"Failed to generate custom document: {e}")
            return CustomDocResult(
                success=False,
                error=str(e),
                generation_time_seconds=time.time() - start_time,
            )

    async def _get_codebase_context(
        self,
        repositories: list[Repository],
        focus_paths: list[str] | None = None,
    ) -> CodebaseContext:
        """
        Get codebase context, optionally focused on specific paths.

        If focus_paths are provided, the analyzer will prioritize those files
        in the context window.
        """
        analyzer = CodebaseAnalyzer(self.github_service)
        context = await analyzer.analyze(repositories)

        # If focus paths specified, filter/prioritize those files
        if focus_paths:
            focused_files = [
                f for f in context.all_key_files if any(fp in f.path for fp in focus_paths)
            ]
            if focused_files:
                # Put focused files first, then others
                other_files = [f for f in context.all_key_files if f not in focused_files]
                context.all_key_files = focused_files + other_files

        return context

    async def _save_document(
        self,
        product: Product,
        user_id: str | UUID,
        title: str,
        content: str,
        doc_type: str,
    ) -> Document:
        """Save generated content as a Document entity."""
        doc = Document(
            product_id=product.id,
            user_id=str(user_id),
            title=title,
            content=content,
            type=doc_type,
            folder={"path": "blueprints"},  # Default folder for custom docs
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        logger.info(f"Saved custom document: {title}")
        return doc

    def _select_model(self, doc_type: str) -> str:
        """
        Select the appropriate model based on document complexity.

        Opus 4.5 for technical and wiki docs (need deeper reasoning).
        Sonnet for overview, guide, and how-to docs (more straightforward).
        """
        if doc_type in COMPLEX_DOC_TYPES:
            return MODEL_OPUS
        return MODEL_SONNET

    async def _call_claude(
        self,
        request: CustomDocRequest,
        context: CodebaseContext,
    ) -> tuple[str, str]:
        """
        Call Claude API to generate document content.

        Returns:
            Tuple of (content, suggested_title)
        """
        model = self._select_model(request.doc_type)
        prompt = build_custom_prompt(request, context)
        tool_schema = self._build_tool_schema()

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS_GENERATION,
                    tools=cast(Any, [tool_schema]),
                    tool_choice=cast(Any, {"type": "tool", "name": "save_document"}),
                    messages=[{"role": "user", "content": prompt}],
                )

                return self._parse_response(response)

            except (RateLimitError, APIError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Generation error (attempt {attempt + 1}/{MAX_RETRIES}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Custom doc generation failed after {MAX_RETRIES} attempts: {e}")

        raise last_error or RuntimeError("Custom doc generation failed after retries")

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build the tool schema for document generation."""
        return {
            "name": "save_document",
            "description": "Save the generated documentation with a suggested title",
            "input_schema": {
                "type": "object",
                "required": ["content", "suggested_title"],
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The full markdown content of the document.",
                    },
                    "suggested_title": {
                        "type": "string",
                        "description": (
                            "A concise, descriptive title for this document (2-6 words). "
                            "Should reflect the main topic covered."
                        ),
                    },
                },
            },
        }

    def _parse_response(self, response: anthropic.types.Message) -> tuple[str, str]:
        """
        Parse Claude's response to extract document content and title.

        Returns:
            Tuple of (content, suggested_title)
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "save_document":
                data = cast(dict[str, Any], block.input)
                content = data.get("content", "")
                title = data.get("suggested_title", "Untitled Document")
                if isinstance(content, str) and isinstance(title, str):
                    return content, title

        logger.warning("Claude did not return a save_document tool use")
        return "Content generation failed.", "Untitled Document"
