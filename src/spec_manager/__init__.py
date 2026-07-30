"""
Spec 规格管理模块

提供 FAI 规格数据的加载、版本管理、查询功能。

主要入口:
    - loader:     Excel 规格数据加载与校验
    - versioning: 规格版本管理与持久化
    - cli:        命令行工具（Click）
"""

from src.spec_manager.loader import load_spec_from_excel, validate_spec, get_fai_name_list
from src.spec_manager.versioning import (
    create_spec_version,
    save_spec_limits,
    get_active_spec,
    set_active_version,
    list_versions,
    get_spec_at_time,
)

__all__ = [
    # loader
    "load_spec_from_excel",
    "validate_spec",
    "get_fai_name_list",
    # versioning
    "create_spec_version",
    "save_spec_limits",
    "get_active_spec",
    "set_active_version",
    "list_versions",
    "get_spec_at_time",
]
