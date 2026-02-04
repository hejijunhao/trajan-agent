"""Product documentation generation: AI-powered docs creation."""

import logging
import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    check_product_editor_access,
    get_current_user,
    get_db_with_rls,
)
from app.domain import product_ops
from app.domain.organization_operations import organization_ops
from app.domain.preferences_operations import preferences_ops
from app.domain.product_access_operations import product_access_ops
from app.models.user import User
from app.schemas.docs import DocsStatusResponse, GenerateDocsRequest, GenerateDocsResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# Stale job detection: mark as failed if generating for longer than this
DOCS_GENERATION_TIMEOUT_MINUTES = 15


@router.post("/{product_id}/generate-docs", response_model=GenerateDocsResponse)
async def generate_documentation(
    product_id: uuid_pkg.UUID,
    background_tasks: BackgroundTasks,
    request: GenerateDocsRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> GenerateDocsResponse:
    """
    Trigger DocumentOrchestrator to analyze and generate documentation.

    Requires Editor or Admin access to the product.

    Args:
        request: Optional request body with generation mode
            - mode="full": Regenerate all documentation from scratch (default)
            - mode="additive": Only add new docs, preserve existing

    Runs as a background task with progress updates. Poll GET /products/{id}/docs-status
    for real-time progress.
    """
    # Check product access first (verifies user has editor access via org membership)
    await check_product_editor_access(db, product_id, current_user.id)

    # Get product (no user_id filter since access is checked above)
    product = await product_ops.get(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check if already running
    if product.docs_generation_status == "generating":
        return GenerateDocsResponse(
            status="already_running",
            message="Documentation generation already in progress",
        )

    # Get user's GitHub token from preferences (check existence only - token fetched in background task)
    prefs = await preferences_ops.get_by_user_id(db, user_id=current_user.id)
    if not prefs or not preferences_ops.get_decrypted_token(prefs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token required for documentation generation. "
            "Configure it in Settings → General.",
        )

    # Parse mode from request (default to "full")
    mode = request.mode if request else "full"

    # Update status
    product.docs_generation_status = "generating"
    product.docs_generation_error = None
    product.docs_generation_progress = None
    db.add(product)
    await db.commit()

    # Start background task
    background_tasks.add_task(
        run_document_orchestrator,
        product_id=str(product.id),
        user_id=str(current_user.id),
        mode=mode,
    )

    return GenerateDocsResponse(
        status="started",
        message=f"Documentation generation started (mode: {mode}). Poll for progress.",
    )


@router.get("/{product_id}/docs-status", response_model=DocsStatusResponse)
async def get_docs_generation_status(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> DocsStatusResponse:
    """Get current documentation generation status.

    Includes stale job detection: if a job has been "generating" for longer than
    DOCS_GENERATION_TIMEOUT_MINUTES, it's automatically marked as failed.
    """
    product = await product_ops.get(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check org membership and product access (at least viewer)
    if not product.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    org_role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
    if not org_role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    access = await product_access_ops.get_effective_access(
        db, product_id, current_user.id, org_role
    )
    if access == "none":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Stale job detection: auto-fail jobs that have been running too long
    if product.docs_generation_status == "generating":
        progress = product.docs_generation_progress or {}
        updated_at_str = progress.get("updated_at")

        if updated_at_str:
            try:
                # Parse ISO format timestamp
                updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                elapsed = datetime.now(UTC) - updated_at
                timeout_delta = timedelta(minutes=DOCS_GENERATION_TIMEOUT_MINUTES)

                if elapsed > timeout_delta:
                    # Job is stale - mark as failed
                    elapsed_minutes = int(elapsed.total_seconds() / 60)
                    stage = progress.get("stage", "unknown")
                    product.docs_generation_status = "failed"
                    product.docs_generation_error = (
                        f"Generation timed out after {elapsed_minutes} minutes "
                        f"(stuck on '{stage}' stage). Please try again."
                    )
                    product.docs_generation_progress = None
                    await db.commit()
                    logger.warning(
                        f"Auto-marked stale docs generation as failed for product {product_id}. "
                        f"Was stuck on '{stage}' for {elapsed_minutes} minutes."
                    )
            except (ValueError, TypeError) as e:
                # Couldn't parse timestamp - log but don't fail the request
                logger.warning(f"Failed to parse docs progress timestamp: {e}")

    return DocsStatusResponse(
        status=product.docs_generation_status or "idle",
        progress=product.docs_generation_progress,
        error=product.docs_generation_error,
        last_generated_at=product.last_docs_generated_at,
    )


async def _mark_generation_failed(
    product_id: str,
    error_message: str,
) -> None:
    """
    Helper to mark documentation generation as failed using a fresh DB session.

    This is used for error recovery when the main session may be in a bad state.
    """
    from app.core.database import async_session_maker

    try:
        async with async_session_maker() as db:
            product_uuid = uuid_pkg.UUID(product_id)
            # Access was already verified when the task was started
            product = await product_ops.get(db, product_uuid)
            if product:
                product.docs_generation_status = "failed"
                product.docs_generation_error = error_message[:500]
                product.docs_generation_progress = None
                await db.commit()
                logger.info(
                    f"Marked product {product_id} docs generation as failed: {error_message}"
                )
    except Exception as db_error:
        # Critical: even error handling failed - log for manual intervention
        logger.critical(
            f"CRITICAL: Failed to mark docs generation as failed. "
            f"Product {product_id} may be stuck in 'generating' state. "
            f"DB error: {db_error}. Original error: {error_message}"
        )


async def maybe_auto_trigger_docs(
    product_id: uuid_pkg.UUID,
    user_id: uuid_pkg.UUID,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
) -> bool:
    """Check user preference and preconditions, then trigger docs generation if appropriate.

    Returns True if generation was triggered, False otherwise.
    """
    # 1. Check user's auto_generate_docs preference
    prefs = await preferences_ops.get_or_create(db, user_id)
    if not prefs.auto_generate_docs:
        return False

    # 2. Check GitHub token exists (required by the orchestrator)
    if not preferences_ops.get_decrypted_token(prefs):
        logger.debug(
            f"Skipping auto-trigger for product {product_id}: no GitHub token configured"
        )
        return False

    # 3. Check product is not already generating
    product = await product_ops.get(db, product_id)
    if not product:
        return False

    if product.docs_generation_status == "generating":
        logger.debug(
            f"Skipping auto-trigger for product {product_id}: generation already in progress"
        )
        return False

    # 4. Trigger generation (additive mode — preserve existing docs when adding repos)
    product.docs_generation_status = "generating"
    product.docs_generation_error = None
    product.docs_generation_progress = None
    db.add(product)
    await db.flush()

    background_tasks.add_task(
        run_document_orchestrator,
        product_id=str(product_id),
        user_id=str(user_id),
        mode="additive",
    )

    logger.info(f"Auto-triggered docs generation for product {product_id}")
    return True


async def run_document_orchestrator(
    product_id: str,
    user_id: str,
    mode: str = "full",
) -> None:
    """Background task to run documentation generation.

    Args:
        product_id: The product UUID
        user_id: The user UUID
        mode: Generation mode - "full" (regenerate all) or "additive" (only add new)
    """
    from app.core.database import async_session_maker
    from app.services.docs import DocumentOrchestrator
    from app.services.github import GitHubService

    async with async_session_maker() as db:
        try:
            product_uuid = uuid_pkg.UUID(product_id)
            user_uuid = uuid_pkg.UUID(user_id)

            # Access was already verified when the task was started
            product = await product_ops.get(db, product_uuid)
            if not product:
                logger.warning(f"Product {product_id} not found for docs generation")
                return

            # Get GitHub token from user preferences (decrypted)
            prefs = await preferences_ops.get_by_user_id(db, user_id=user_uuid)
            github_token = preferences_ops.get_decrypted_token(prefs) if prefs else None
            if not github_token:
                product.docs_generation_status = "failed"
                product.docs_generation_error = "GitHub token not found"
                await db.commit()
                return

            github_service = GitHubService(github_token)

            # Run orchestrator with specified mode
            orchestrator = DocumentOrchestrator(db, product, github_service)
            await orchestrator.run(mode=mode)

            # Update status on success
            product.docs_generation_status = "completed"
            product.last_docs_generated_at = datetime.now(UTC)
            product.docs_generation_error = None
            product.docs_generation_progress = None
            await db.commit()
            logger.info(
                f"Documentation generation completed for product {product_id} (mode: {mode})"
            )

        except Exception as e:
            logger.error(f"Documentation generation failed for product {product_id}: {e}")
            # Use a fresh session for error handling to avoid stale session issues
            await _mark_generation_failed(product_id, str(e))
