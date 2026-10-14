from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    sessions: Mapped[list[UserSession]] = relationship(back_populates="user")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SpecVersion(Base):
    __tablename__ = "spec_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    enabled_points_json: Mapped[str] = mapped_column(Text)
    rules_json: Mapped[str] = mapped_column(Text)
    source_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MappingVersion(Base):
    __tablename__ = "mapping_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    rules_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(Text)
    parquet_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_format: Mapped[str] = mapped_column(String(20))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="uploaded", index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("file_sha256", name="uq_batch_file_sha256"),)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(80), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    filters_json: Mapped[str] = mapped_column(Text)
    spec_version_id: Mapped[str] = mapped_column(ForeignKey("spec_versions.id"))
    mapping_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("mapping_versions.id"), nullable=True
    )
    data_watermark: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventSource(Base):
    __tablename__ = "event_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_hash: Mapped[str] = mapped_column(String(64), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    source_row: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("event_hash", "batch_id", "source_row", name="uq_event_source"),
    )
