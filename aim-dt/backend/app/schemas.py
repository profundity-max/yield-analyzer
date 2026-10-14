from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["admin", "analyst", "viewer"]
BatchStatus = Literal["uploaded", "validating", "importing", "ready", "deleting", "failed"]
AnalysisStatus = Literal[
    "queued", "running", "completed", "completed_with_warnings", "failed", "cancelled"
]
RuleStatus = Literal["draft", "active", "retired"]
Outcome = Literal["PASS", "FAIL", "ERROR"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=200)
    role: Role = "viewer"


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    role: Role
    is_active: bool
    must_change_password: bool
    created_at: datetime


class SessionView(BaseModel):
    user: UserView
    csrf_token: str


class SpecLimits(BaseModel):
    lsl: float | None = None
    usl: float | None = None


class SpecRules(BaseModel):
    default: dict[str, SpecLimits] = Field(default_factory=dict)
    by_config: dict[str, dict[str, SpecLimits]] = Field(default_factory=dict)


class SpecCreate(BaseModel):
    name: str
    enabled_points: list[str]
    rules: SpecRules
    source_batch_id: str | None = None


class SpecView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    fingerprint: str
    status: RuleStatus
    enabled_points_json: str
    rules_json: str
    source_batch_id: str | None
    created_at: datetime
    confirmed_at: datetime | None


class MappingRule(BaseModel):
    equipment_id: str | None = None
    site_name: str | None = None
    config: str | None = None
    slot: str | None = None
    cell: str
    tester: str
    qpl: str


class MappingCreate(BaseModel):
    name: str
    rules: list[MappingRule]


class MappingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    fingerprint: str
    status: RuleStatus
    rules_json: str
    created_at: datetime
    confirmed_at: datetime | None


class BatchView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_name: str
    file_format: str
    file_size: int
    file_sha256: str
    status: BatchStatus
    row_count: int
    event_count: int
    duplicate_count: int
    error_count: int
    error_message: str | None
    created_at: datetime
    ready_at: datetime | None


class AnalysisCreate(BaseModel):
    name: str = "AIM D-T 分析"
    batch_ids: list[str] = Field(default_factory=list)
    spec_version_id: str
    mapping_version_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    configs: list[str] = Field(default_factory=list)
    cells: list[str] = Field(default_factory=list)
    testers: list[str] = Field(default_factory=list)


class AnalysisView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: AnalysisStatus
    phase: str
    progress: float
    filters_json: str
    spec_version_id: str
    mapping_version_id: str | None
    warnings_json: str
    error_message: str | None
    summary_json: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
