from fastapi import APIRouter

from app.api.v1 import (
    app_info,
    documents,
    github,
    preferences,
    products,
    repositories,
    users,
    work_items,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(products.router)
api_router.include_router(repositories.router)
api_router.include_router(work_items.router)
api_router.include_router(documents.router)
api_router.include_router(app_info.router)
api_router.include_router(users.router)
api_router.include_router(preferences.router)
api_router.include_router(github.router)
