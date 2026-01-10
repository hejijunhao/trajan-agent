import uuid as uuid_pkg
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SubscriptionContext, get_current_user, require_agent_enabled
from app.core.database import get_db
from app.domain import product_ops
from app.domain.preferences_operations import preferences_ops
from app.models.product import ProductCreate, ProductUpdate
from app.models.user import User
from app.schemas.docs import DocsStatusResponse, GenerateDocsResponse
from app.schemas.product_overview import AnalyzeProductResponse
from app.services.analysis import run_analysis_task

router = APIRouter(prefix="/products", tags=["products"])


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
    """List all products for the current user."""
    products = await product_ops.get_multi_by_user(
        db, user_id=current_user.id, skip=skip, limit=limit
    )
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
        for p in products
    ]


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
    """Update a product."""
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
    """Delete a product and all related entities."""
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

    Requires:
    - Agent to be enabled for the organization (free tier must be within repo limit)
    - Analysis frequency must be respected (weekly for Observer, daily for Foundations)

    Analysis runs in the background. Poll GET /products/{id} for status updates.
    The `analysis_status` field will be:
    - "analyzing" while in progress
    - "completed" when done (product_overview will contain results)
    - "failed" if an error occurred
    """
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
            hours_since_last = (datetime.utcnow() - last_analysis_time).total_seconds() / 3600
            if hours_since_last < frequency_limit_hours:
                hours_remaining = int(frequency_limit_hours - hours_since_last)
                frequency_display = (
                    "once per week" if sub_ctx.plan.analysis_frequency == "weekly" else "once per day"
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenerateDocsResponse:
    """
    Trigger DocumentOrchestrator to analyze and generate documentation.

    Runs as a background task with progress updates. Poll GET /products/{id}/docs-status
    for real-time progress.
    """
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
    )

    return GenerateDocsResponse(
        status="started",
        message="Documentation generation started. Poll for progress.",
    )


@router.get("/{product_id}/docs-status", response_model=DocsStatusResponse)
async def get_docs_generation_status(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocsStatusResponse:
    """Get current documentation generation status."""
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return DocsStatusResponse(
        status=product.docs_generation_status or "idle",
        progress=product.docs_generation_progress,
        error=product.docs_generation_error,
        last_generated_at=product.last_docs_generated_at,
    )


async def run_document_orchestrator(
    product_id: str,
    user_id: str,
) -> None:
    """Background task to run documentation generation."""
    from app.core.database import async_session_maker
    from app.services.docs import DocumentOrchestrator
    from app.services.github import GitHubService

    async with async_session_maker() as db:
        try:
            product_uuid = uuid_pkg.UUID(product_id)
            user_uuid = uuid_pkg.UUID(user_id)

            product = await product_ops.get_by_user(db, user_id=user_uuid, id=product_uuid)
            if not product:
                return

            # Get GitHub token from user preferences
            prefs = await preferences_ops.get_by_user_id(db, user_id=user_uuid)
            if not prefs or not prefs.github_token:
                product.docs_generation_status = "failed"
                product.docs_generation_error = "GitHub token not found"
                await db.commit()
                return

            github_service = GitHubService(prefs.github_token)

            # Run orchestrator
            orchestrator = DocumentOrchestrator(db, product, github_service)
            await orchestrator.run()

            # Update status
            product.docs_generation_status = "completed"
            product.last_docs_generated_at = datetime.utcnow()
            product.docs_generation_error = None
            product.docs_generation_progress = None
            await db.commit()

        except Exception as e:
            # Update status on failure
            product = await product_ops.get_by_user(db, user_id=user_uuid, id=product_uuid)
            if product:
                product.docs_generation_status = "failed"
                product.docs_generation_error = str(e)[:500]
                product.docs_generation_progress = None
                await db.commit()
            raise
