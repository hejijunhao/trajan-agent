"""Products API router - composed from sub-routers."""

from fastapi import APIRouter

from .analysis import router as analysis_router
from .collaborators import router as collaborators_router
from .crud import router as crud_router
from .docs_generation import router as docs_router

router = APIRouter(prefix="/products", tags=["products"])

# Include all sub-routers
# Order matters: more specific routes should come first to avoid conflicts
router.include_router(analysis_router)
router.include_router(docs_router)
router.include_router(collaborators_router)
router.include_router(crud_router)
