from fastapi import APIRouter

from app.api import admin, analyses, auth, batches, configurations_api, master

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(batches.router)
api_router.include_router(analyses.router)
api_router.include_router(admin.router)
api_router.include_router(configurations_api.router)
api_router.include_router(master.router)
