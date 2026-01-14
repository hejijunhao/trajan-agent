"""Custom document generation API endpoints.

Endpoints for generating custom documentation based on user requests with
specific parameters (doc type, format style, target audience).

Supports both synchronous generation (for smaller requests) and background
generation with progress tracking (for longer requests).
"""

import asyncio
import logging
import uuid as uuid_pkg
from typing import Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain import preferences_ops, product_ops, repository_ops
from app.models.user import User
from app.schemas.docs import (
    CustomDocRequestSchema,
    CustomDocResponseSchema,
    CustomDocStatusSchema,
)
from app.services.docs.custom_generator import CustomDocGenerator
from app.services.docs.job_store import get_job_store
from app.services.docs.types import CustomDocRequest
from app.services.github import GitHubService

logger = logging.getLogger(__name__)


async def generate_custom_document(
    product_id: uuid_pkg.UUID,
    request: CustomDocRequestSchema,
    background: bool = Query(False, description="Run generation in background with progress"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomDocResponseSchema:
    """
    Generate a custom document based on user request.

    If background=False (default): Generates synchronously and returns content.
    If background=True: Starts background job and returns job_id for polling.

    Args:
        product_id: The product to generate documentation for
        request: The custom doc request with prompt and parameters
        background: If True, run async and return job ID
        current_user: The authenticated user
        db: Database session

    Returns:
        CustomDocResponseSchema with generated content or job_id
    """
    # Get the product
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Get user's GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    if not preferences or not preferences.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured. Please add your GitHub token in Settings.",
        )

    # Get repositories for the product
    repositories = await repository_ops.get_by_product(
        db,
        user_id=current_user.id,
        product_id=product_id,
    )

    if not repositories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No repositories linked to this product. Add a repository first.",
        )

    # Convert Pydantic schema to dataclass
    custom_request = CustomDocRequest(
        prompt=request.prompt,
        doc_type=request.doc_type,
        format_style=request.format_style,
        target_audience=request.target_audience,
        focus_paths=request.focus_paths,
        title=request.title,
    )

    if background:
        # Start background job
        job_store = get_job_store()
        job_id = await job_store.create_job(
            product_id=str(product_id),
            user_id=str(current_user.id),
        )

        # Run generation in background task
        asyncio.create_task(
            _run_background_generation(
                job_id=job_id,
                custom_request=custom_request,
                product=product,
                repositories=repositories,
                user_id=current_user.id,
                github_token=preferences.github_token,
            )
        )

        return CustomDocResponseSchema(
            status="generating",
            job_id=job_id,
        )
    else:
        # Synchronous generation
        github_service = GitHubService(preferences.github_token)
        generator = CustomDocGenerator(db, github_service)

        result = await generator.generate(
            request=custom_request,
            product=product,
            repositories=repositories,
            user_id=current_user.id,
            save_immediately=False,
        )

        if result.success:
            return CustomDocResponseSchema(
                status="completed",
                content=result.content,
                suggested_title=result.suggested_title,
                generation_time_seconds=result.generation_time_seconds,
            )
        else:
            return CustomDocResponseSchema(
                status="failed",
                error=result.error,
            )


async def _run_background_generation(
    job_id: str,
    custom_request: CustomDocRequest,
    product: Any,
    repositories: list[Any],
    user_id: Any,
    github_token: str,
) -> None:
    """
    Run custom doc generation in background with progress updates.

    This function is run as an asyncio task and updates the job store
    with progress as it runs.
    """
    from app.core.database import async_session_factory

    job_store = get_job_store()

    async def progress_callback(stage: str) -> None:
        await job_store.update_progress(job_id, stage)

    try:
        # Create a new database session for the background task
        async with async_session_factory() as db:
            github_service = GitHubService(github_token)
            generator = CustomDocGenerator(db, github_service)

            result = await generator.generate(
                request=custom_request,
                product=product,
                repositories=repositories,
                user_id=user_id,
                save_immediately=False,
                progress_callback=progress_callback,
            )

            if result.success:
                await job_store.set_completed(
                    job_id,
                    content=result.content or "",
                    suggested_title=result.suggested_title or "Untitled Document",
                )
            else:
                await job_store.set_failed(job_id, result.error or "Unknown error")

    except Exception as e:
        logger.exception(f"Background generation failed for job {job_id}")
        await job_store.set_failed(job_id, str(e))


async def get_custom_doc_status(
    product_id: uuid_pkg.UUID,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomDocStatusSchema:
    """
    Get the status of a background custom document generation job.

    Poll this endpoint to check progress and get the result when complete.

    Args:
        product_id: The product ID (for authorization)
        job_id: The job ID returned from generate endpoint
        current_user: The authenticated user
        db: Database session

    Returns:
        CustomDocStatusSchema with current status, progress, and content when done
    """
    job_store = get_job_store()
    job = await job_store.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found or expired",
        )

    # Verify the job belongs to this user and product
    if job.user_id != str(current_user.id) or job.product_id != str(product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this job",
        )

    return CustomDocStatusSchema(
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress,
        content=job.content,
        suggested_title=job.suggested_title,
        error=job.error,
    )


async def save_custom_document(
    product_id: uuid_pkg.UUID,
    title: str,
    content: str,
    doc_type: str,
    folder: str = "blueprints",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Save a generated custom document to the database.

    This is called after the user previews the generated content and
    decides to save it.

    Args:
        product_id: The product to save the document to
        title: Document title
        content: Document content (markdown)
        doc_type: Type of document
        folder: Folder to save in (default: blueprints)
        current_user: The authenticated user
        db: Database session

    Returns:
        The saved document
    """
    from app.models.document import Document

    # Verify product exists and belongs to user
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Create the document
    doc = Document(
        product_id=product_id,
        user_id=str(current_user.id),
        title=title,
        content=content,
        type=doc_type,
        folder={"path": folder},
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    logger.info(f"Saved custom document: {title}")

    # Import serialize_document from crud module
    from app.api.v1.documents.crud import serialize_document

    return serialize_document(doc)
