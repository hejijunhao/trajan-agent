import logging
import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SubscriptionContext,
    check_product_admin_access,
    check_product_editor_access,
    get_current_user,
    require_agent_enabled,
)
from app.core.database import get_db
from app.domain import product_ops
from app.domain.organization_operations import organization_ops
from app.domain.preferences_operations import preferences_ops
from app.domain.product_access_operations import product_access_ops
from app.models.product import ProductCreate, ProductUpdate
from app.models.user import User
from app.schemas.docs import DocsStatusResponse, GenerateDocsRequest, GenerateDocsResponse
from app.schemas.product_overview import AnalyzeProductResponse
from app.services.analysis import run_analysis_task

router = APIRouter(prefix="/products", tags=["products"])
logger = logging.getLogger(__name__)

# Stale job detection: mark as failed if generating for longer than this
DOCS_GENERATION_TIMEOUT_MINUTES = 15

# Analysis frequency limits in hours
ANALYSIS_FREQUENCY_LIMITS = {
    "weekly": 7 * 24,  # 168 hours
    "daily": 24,  # 24 hours
    "realtime": 0,  # No limit
}


@router.get("", response_model=list[dict])
async def list_products(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all products the current user has access to.

    Returns products from all organizations the user is a member of,
    filtered by their access level:
    - Org owners/admins: see all products in their orgs
    - Org members/viewers: only see products they have explicit access to
    """
    # Get all organizations user is a member of
    user_orgs = await organization_ops.get_for_user(db, current_user.id)

    accessible_products = []
    for org in user_orgs:
        # Get user's role in this org
        org_role = await organization_ops.get_member_role(db, org.id, current_user.id)
        if not org_role:
            continue

        # Get all products in this org
        org_products = await product_ops.get_multi_by_user(
            db, user_id=current_user.id, skip=0, limit=1000
        )

        # Filter to products in this org
        org_products = [p for p in org_products if p.organization_id == org.id]

        for product in org_products:
            # Check if user can access this product
            access = await product_access_ops.get_effective_access(
                db, product.id, current_user.id, org_role
            )
            if access != "none":
                accessible_products.append(product)

    # Apply pagination
    paginated = accessible_products[skip : skip + limit]

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "icon": p.icon,
            "color": p.color,
            "analysis_status": p.analysis_status,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in paginated
    ]


@router.get("/{product_id}/access")
async def get_my_product_access(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current user's access level for a product.

    Returns the effective access level considering both org role and explicit access.
    """
    # Get product to find its organization
    product = await product_ops.get(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Get user's org role
    if not product.organization_id:
        return {"access_level": "none"}
    org_role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
    if not org_role:
        return {"access_level": "none"}

    # Get effective access level
    access_level = await product_access_ops.get_effective_access(
        db, product_id, current_user.id, org_role
    )

    return {"access_level": access_level}


@router.get("/{product_id}")
async def get_product(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single product with all related entities."""
    product = await product_ops.get_with_relations(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "icon": product.icon,
        "color": product.color,
        "analysis_status": product.analysis_status,
        "analysis_error": product.analysis_error,
        "analysis_progress": product.analysis_progress,
        "product_overview": product.product_overview,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
        "repositories_count": len(product.repositories),
        "work_items_count": len(product.work_items),
        "documents_count": len(product.documents),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new product."""
    # Check for duplicate name
    existing = await product_ops.get_by_name(db, user_id=current_user.id, name=data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this name already exists",
        )

    product = await product_ops.create(
        db,
        obj_in=data.model_dump(),
        user_id=current_user.id,
    )
    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "icon": product.icon,
        "color": product.color,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


@router.patch("/{product_id}")
async def update_product(
    product_id: uuid_pkg.UUID,
    data: ProductUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a product. Requires Editor or Admin access."""
    # Check product access first
    await check_product_editor_access(db, product_id, current_user.id)

    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    updated = await product_ops.update(
        db, db_obj=product, obj_in=data.model_dump(exclude_unset=True)
    )
    return {
        "id": str(updated.id),
        "name": updated.name,
        "description": updated.description,
        "icon": updated.icon,
        "color": updated.color,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat(),
    }


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a product and all related entities. Requires Admin access."""
    # Check admin access first
    await check_product_admin_access(db, product_id, current_user.id)

    deleted = await product_ops.delete(db, id=product_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )


@router.post("/{product_id}/analyze", response_model=AnalyzeProductResponse)
async def analyze_product(
    product_id: uuid_pkg.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    sub_ctx: SubscriptionContext = Depends(require_agent_enabled),
    db: AsyncSession = Depends(get_db),
) -> AnalyzeProductResponse:
    """
    Trigger AI analysis of the product's repositories.

    Requires Editor or Admin access to the product.

    Additional requirements:
    - Agent to be enabled for the organization (free tier must be within repo limit)
    - Analysis frequency must be respected (weekly for Observer, daily for Foundations)

    Analysis runs in the background. Poll GET /products/{id} for status updates.
    The `analysis_status` field will be:
    - "analyzing" while in progress
    - "completed" when done (product_overview will contain results)
    - "failed" if an error occurred
    """
    # Check product access first
    await check_product_editor_access(db, product_id, current_user.id)

    # Get product
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check if already analyzing
    if product.analysis_status == "analyzing":
        return AnalyzeProductResponse(
            status="already_analyzing",
            message="Analysis already in progress. Poll GET /products/{id} for status.",
        )

    # Check analysis frequency limit
    frequency_limit_hours = ANALYSIS_FREQUENCY_LIMITS.get(sub_ctx.plan.analysis_frequency, 0)
    if frequency_limit_hours > 0 and product.analysis_status == "completed":
        # Use updated_at as a proxy for when analysis was completed
        # (set when status changes to "completed")
        last_analysis_time = product.updated_at
        if last_analysis_time:
            hours_since_last = (datetime.now(UTC) - last_analysis_time).total_seconds() / 3600
            if hours_since_last < frequency_limit_hours:
                hours_remaining = int(frequency_limit_hours - hours_since_last)
                frequency_display = (
                    "once per week"
                    if sub_ctx.plan.analysis_frequency == "weekly"
                    else "once per day"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Analysis limited to {frequency_display} on {sub_ctx.plan.display_name} plan. "
                    f"Next analysis available in {hours_remaining} hours.",
                )

    # Get user's GitHub token from preferences
    prefs = await preferences_ops.get_by_user_id(db, user_id=current_user.id)
    if not prefs or not prefs.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token required for analysis. Configure it in Settings → General.",
        )

    # Update status to analyzing
    product.analysis_status = "analyzing"
    db.add(product)
    await db.commit()

    # Dispatch background task
    # Note: run_analysis_task creates its own database session since
    # FastAPI's request session is closed by the time background tasks run.
    # Security: GitHub token is fetched inside the task, not passed as param.
    background_tasks.add_task(
        run_analysis_task,
        product_id=str(product.id),
        user_id=str(current_user.id),
    )

    return AnalyzeProductResponse(
        status="analyzing",
        message="Analysis started. Poll GET /products/{id} for status updates.",
    )


@router.post("/{product_id}/generate-docs", response_model=GenerateDocsResponse)
async def generate_documentation(
    product_id: uuid_pkg.UUID,
    background_tasks: BackgroundTasks,
    request: GenerateDocsRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
    # Check product access first
    await check_product_editor_access(db, product_id, current_user.id)

    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
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

    # Get user's GitHub token from preferences
    prefs = await preferences_ops.get_by_user_id(db, user_id=current_user.id)
    if not prefs or not prefs.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token required for documentation generation. Configure it in Settings → General.",
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
    db: AsyncSession = Depends(get_db),
) -> DocsStatusResponse:
    """Get current documentation generation status.

    Includes stale job detection: if a job has been "generating" for longer than
    DOCS_GENERATION_TIMEOUT_MINUTES, it's automatically marked as failed.
    """
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
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
    user_id: str,
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
            user_uuid = uuid_pkg.UUID(user_id)
            product = await product_ops.get_by_user(db, user_id=user_uuid, id=product_uuid)
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

            product = await product_ops.get_by_user(db, user_id=user_uuid, id=product_uuid)
            if not product:
                logger.warning(f"Product {product_id} not found for docs generation")
                return

            # Get GitHub token from user preferences
            prefs = await preferences_ops.get_by_user_id(db, user_id=user_uuid)
            if not prefs or not prefs.github_token:
                product.docs_generation_status = "failed"
                product.docs_generation_error = "GitHub token not found"
                await db.commit()
                return

            github_service = GitHubService(prefs.github_token)

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
            await _mark_generation_failed(product_id, user_id, str(e))
