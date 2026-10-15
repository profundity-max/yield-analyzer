from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

from app.api.router import api_router
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password
from app.services.configurations import ensure_default_spec, seed_categories
from app.services.master import ensure_master
from app.services.storage import init_analytics_db

settings = get_settings()


def bootstrap_admin() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
        if existing is None:
            db.add(
                User(
                    username=settings.bootstrap_admin_username,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    role="admin",
                    must_change_password=settings.force_password_change,
                )
            )
            db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    init_analytics_db()
    bootstrap_admin()
    with SessionLocal() as db:
        seed_categories(db)
        admin = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
        ensure_default_spec(db, created_by=admin.id if admin else None)
        ensure_master(db, created_by=admin.id if admin else None)
    yield


app = FastAPI(title=settings.app_name, version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.exception_handler(Exception)
async def unhandled_exception(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "type": "about:blank",
            "title": "服务器内部错误",
            "status": 500,
            "detail": str(exc) if settings.environment != "production" else "请求处理失败",
        },
    )


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "version": "3.0.0"}


@app.get("/{path:path}")
def serve_react(path: str):
    static_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if static_dir.exists():
        candidate = (static_dir / path).resolve()
        if static_dir.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        index = static_dir / "index.html"
        if index.exists():
            return FileResponse(index)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})
