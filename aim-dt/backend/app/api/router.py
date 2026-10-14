from fastapi import APIRouter

from app.api import admin, analyses, auth, batches

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(batches.router)
api_router.include_router(analyses.router)
api_router.include_router(admin.router)
