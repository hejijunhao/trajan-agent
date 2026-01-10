"""
Analysis background task for AI-powered product analysis.

This module provides the background task entry point for product analysis.
The actual analysis workflow is coordinated by AnalysisOrchestrator.

Part of the Analysis Agent refactoring (Phase 5).
"""

import logging
import uuid as uuid_pkg

from app.core.database import async_session_maker
from app.domain.preferences_operations import preferences_ops
from app.models.product import Product
from app.services.analysis_orchestrator import AnalysisOrchestrator

logger = logging.getLogger(__name__)


async def run_analysis_task(
    product_id: str,
    user_id: str,
) -> None:
    """
    Background task that runs the analysis and updates the product.

    This function creates its own database session since FastAPI's
    request session is closed by the time background tasks run.

    Security: GitHub token is fetched inside this task rather than passed
    as a parameter to avoid token exposure in logs or error dumps.

    Workflow:
    1. Fetch product and GitHub token
    2. Create AnalysisOrchestrator
    3. Run orchestrated analysis (stats + architecture in parallel, then content)
    4. Store results and update status

    Args:
        product_id: UUID of the product to analyze
        user_id: UUID of the user (for data isolation)
    """
    logger.info(f"Background analysis task started for product {product_id}")

    async with async_session_maker() as session:
        product = None
        try:
            # Get the product
            product = await session.get(Product, uuid_pkg.UUID(product_id))
            if not product:
                logger.error(f"Product not found: {product_id}")
                return

            # Fetch GitHub token from user preferences (security: not passed as param)
            user_uuid = uuid_pkg.UUID(user_id)
            prefs = await preferences_ops.get_by_user_id(session, user_id=user_uuid)
            if not prefs or not prefs.github_token:
                logger.error(f"No GitHub token found for user {user_id}")
                product.analysis_status = "failed"
                product.analysis_error = "GitHub token not found. Configure it in Settings."
                product.analysis_progress = None
                session.add(product)
                await session.commit()
                return

            # Run orchestrated analysis
            orchestrator = AnalysisOrchestrator(session, prefs.github_token, product)
            overview = await orchestrator.analyze_product(user_uuid)

            # Update product with results and clear progress
            product.product_overview = overview.model_dump(mode="json")
            product.analysis_status = "completed"
            product.analysis_error = None
            product.analysis_progress = None  # Clear ephemeral progress data
            session.add(product)
            await session.commit()

            logger.info(f"Analysis completed successfully for product {product_id}")

        except Exception as e:
            logger.exception(f"Analysis failed for product {product_id}: {e}")

            # Mark as failed with error message and clear progress
            try:
                if product is None:
                    product = await session.get(Product, uuid_pkg.UUID(product_id))
                if product:
                    product.analysis_status = "failed"
                    # Store truncated error message (max 500 chars)
                    error_msg = str(e)
                    product.analysis_error = error_msg[:500] if len(error_msg) > 500 else error_msg
                    product.analysis_progress = None  # Clear ephemeral progress data
                    session.add(product)
                    await session.commit()
            except Exception as rollback_error:
                logger.error(f"Failed to mark product as failed: {rollback_error}")

            raise
