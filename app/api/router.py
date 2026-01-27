from fastapi import APIRouter

from app.api.v1 import (
    admin,
    announcements,
    app_info,
    billing,
    documents,
    feedback,
    github,
    organizations,
    preferences,
    products,
    progress,
    quick_access,
    referrals,
    repositories,
    timeline,
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
api_router.include_router(organizations.router)
api_router.include_router(admin.router)
api_router.include_router(feedback.router)
api_router.include_router(timeline.router)
api_router.include_router(progress.router)
api_router.include_router(quick_access.router)
api_router.include_router(billing.router)
api_router.include_router(referrals.router)
api_router.include_router(announcements.router)
