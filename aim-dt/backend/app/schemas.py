from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["admin", "analyst", "viewer"]
BatchStatus = Literal[
    "uploaded",
    "replacement_pending",
    "validating",
    "importing",
    "ready",
    "deleting",
    "failed",
]
AnalysisStatus = Literal[
    "queued",
    "running",
    "completed",
    "completed_with_warnings",
    "needs_configuration",
    "failed",
    "cancelled",
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
    data_module_id: str | None = None
    revision: int = 1
    is_active: bool = False
    file_deleted: bool = False


class DataModuleView(BaseModel):
    id: str
    name: str
    active_batch_id: str | None
    active_filename: str | None
    active_revision: int
    row_count: int
    event_count: int
    status: str
    uploaded_at: datetime
    previous_batch_id: str | None = None
    previous_filename: str | None = None
    previous_revision: int | None = None
    previous_available: bool = False


class RefreshLogView(BaseModel):
    id: str
    module_id: str | None
    module_name: str | None
    trigger: str
    status: str
    analysis_run_id: str | None
    from_filename: str | None
    to_filename: str | None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None


class MasterWorkbench(BaseModel):
    master_id: str
    name: str
    current_analysis_id: str | None
    last_success_analysis_id: str | None
    analysis_status: AnalysisStatus | None = None
    stage: str = "idle"
    progress: float = 0
    module_count: int = 0
    total_rows: int = 0
    total_events: int = 0
    unmatched_count: int = 0
    modules: list[DataModuleView] = Field(default_factory=list)
    logs: list[RefreshLogView] = Field(default_factory=list)
    error_message: str | None = None


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


class PointConfig(BaseModel):
    code: str
    source_column: str | None = None
    enabled: bool = True
    lsl: float | None = 0
    usl: float | None = 2
    detected: bool = False


class SpecEditorPayload(BaseModel):
    name: str
    points: list[PointConfig]
    source_batch_id: str | None = None


class SpecEditorView(BaseModel):
    id: str
    name: str
    status: RuleStatus
    points: list[PointConfig]
    created_at: datetime
    confirmed_at: datetime | None = None


class CategoryCreate(BaseModel):
    kind: Literal["cell", "tester", "qpl"]
    code: str
    label: str
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    label: str | None = None
    active: bool | None = None
    sort_order: int | None = None


class CategoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: Literal["cell", "tester", "qpl"]
    code: str
    label: str
    active: bool
    sort_order: int


class MappingEditorSource(BaseModel):
    site_name: str | None = None
    equipment_id: str | None = None
    config: str | None = None
    slot: str | None = None


class MappingEditorTarget(BaseModel):
    cell: str = "Unassigned"
    tester: str = "Unassigned"
    qpl: str = "Unassigned"


class MappingEditorRow(BaseModel):
    source: MappingEditorSource
    target: MappingEditorTarget
    match_count: int = 0
    status: Literal["mapped", "unmapped", "disabled"] = "unmapped"


class MappingEditorPayload(BaseModel):
    name: str
    batch_id: str | None = None
    rows: list[MappingEditorRow]


class MappingEditorView(BaseModel):
    mapping_version_id: str | None = None
    mapping_name: str | None = None
    rules: list[MappingEditorRow]
    unmapped: list[MappingEditorRow]
    categories: dict[str, list[CategoryView]]


class WorkbenchState(BaseModel):
    batch_id: str
    batch_status: BatchStatus
    analysis_id: str | None = None
    analysis_status: AnalysisStatus | None = None
    stage: str
    progress: float = 0.0
    unmatched_count: int = 0
    needs_configuration: bool = False
    error_message: str | None = None


class RerunWithRequest(BaseModel):
    spec_version_id: str
    mapping_version_id: str | None = None


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
