"""
Spec 版本管理模块

管理 FAI 规格的版本化存储，支持：
  - 创建新版本并批量写入规格上下限
  - 激活 / 切换当前有效版本
  - 历史版本回溯查询
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from src.db import get_connection, init_spec_tables


# 确保 spec 表已初始化
init_spec_tables()


def create_spec_version(source_file: str, description: str = "") -> str:
    """
    在 spec_versions 表中创建一条新版本记录。

    新创建的版本默认 is_active=False，需要调用 set_active_version()
    显式激活。这样设计可以防止部分写入的数据被意外使用。

    Args:
        source_file: 规格数据的来源文件路径。
        description: 可选的版本描述（如 "2024Q3 基线规格"）。

    Returns:
        str: 新创建的 version_id（UUID 格式字符串）。
    """
    conn = get_connection()
    version_id = str(uuid.uuid4())

    conn.execute(
        """
        INSERT INTO spec_versions (version_id, source_file, imported_at, is_active, description)
        VALUES (?, ?, CURRENT_TIMESTAMP, FALSE, ?)
        """,
        [version_id, source_file, description],
    )

    return version_id


def save_spec_limits(version_id: str, spec_data: list[dict[str, Any]]) -> int:
    """
    将解析后的规格数据批量写入 spec_limits 表。

    使用 executemany 进行批量插入以提升性能。
    每条记录的 id 从 seq_spec_limits_id 序列自动获取。

    Args:
        version_id: 所属的版本 ID。
        spec_data: load_spec_from_excel 返回的规格数据列表。

    Returns:
        int: 成功插入的记录数。
    """
    conn = get_connection()

    # 先删除该版本的旧数据（如果存在，用于覆盖导入场景）
    conn.execute(
        "DELETE FROM spec_limits WHERE version_id = ?",
        [version_id],
    )

    # 构建批量插入数据：使用 nextval 获取自增 ID
    rows: list[tuple[str, str, Optional[float], Optional[float], Optional[float]]] = []
    for item in spec_data:
        fai_name = item["fai_name"]
        lower_limit = item.get("lower_limit")
        upper_limit = item.get("upper_limit")
        nominal = item.get("nominal")

        rows.append((fai_name, version_id, lower_limit, upper_limit, nominal))

    # DuckDB 的 executemany 批量插入（使用序列生成 ID）
    conn.executemany(
        """
        INSERT INTO spec_limits (id, fai_name, version_id, lower_limit, upper_limit, nominal)
        VALUES (nextval('seq_spec_limits_id'), ?, ?, ?, ?, ?)
        """,
        rows,
    )

    return len(rows)


def get_active_spec() -> dict[str, Any]:
    """
    查询当前激活的 Spec 版本及其所有规格上下限。

    Returns:
        dict: 包含以下键:
            - version_id (str | None): 当前激活的版本 ID，无激活版本时为 None。
            - source_file (str | None): 来源文件路径。
            - imported_at (str | None): 导入时间。
            - description (str | None): 版本描述。
            - fai_limits (dict): 以 fai_name 为键的规格字典，
              每个值为 {lower: float|None, upper: float|None, nominal: float|None}。
    """
    conn = get_connection()

    # 查询激活版本
    version_row = conn.execute(
        """
        SELECT version_id, source_file, imported_at, description
        FROM spec_versions
        WHERE is_active = TRUE
        ORDER BY imported_at DESC
        LIMIT 1
        """
    ).fetchone()

    if version_row is None:
        return {
            "version_id": None,
            "source_file": None,
            "imported_at": None,
            "description": None,
            "fai_limits": {},
        }

    version_id = version_row[0]

    # 查询该版本的所有 limits
    limits_rows = conn.execute(
        """
        SELECT fai_name, lower_limit, upper_limit, nominal
        FROM spec_limits
        WHERE version_id = ?
        ORDER BY fai_name
        """,
        [version_id],
    ).fetchall()

    fai_limits: dict[str, dict[str, Optional[float]]] = {}
    for row in limits_rows:
        fai_limits[row[0]] = {
            "lower": row[1],
            "upper": row[2],
            "nominal": row[3],
        }

    return {
        "version_id": version_id,
        "source_file": version_row[1],
        "imported_at": str(version_row[2]) if version_row[2] else None,
        "description": version_row[3],
        "fai_limits": fai_limits,
    }


def set_active_version(version_id: str) -> bool:
    """
    切换当前激活的 Spec 版本。

    先将所有版本的 is_active 设为 FALSE，
    再将指定版本的 is_active 设为 TRUE。

    Args:
        version_id: 要激活的版本 ID。

    Returns:
        bool: 操作是否成功（目标版本存在且已激活）。

    Raises:
        ValueError: 指定的 version_id 不存在时抛出。
    """
    conn = get_connection()

    # 检查目标版本是否存在
    exists = conn.execute(
        "SELECT COUNT(*) FROM spec_versions WHERE version_id = ?",
        [version_id],
    ).fetchone()[0]

    if not exists:
        raise ValueError(f"版本 '{version_id}' 不存在")

    # 全部失活
    conn.execute("UPDATE spec_versions SET is_active = FALSE")

    # 激活目标版本
    conn.execute(
        "UPDATE spec_versions SET is_active = TRUE WHERE version_id = ?",
        [version_id],
    )

    return True


def list_versions() -> list[dict[str, Any]]:
    """
    列出所有 Spec 版本历史，按导入时间倒序排列。

    Returns:
        list[dict]: 每个版本包含:
            - version_id, source_file, imported_at, is_active, description
            - limit_count: 该版本包含的 FAI 规格数量
    """
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            v.version_id,
            v.source_file,
            v.imported_at,
            v.is_active,
            v.description,
            COUNT(l.id) AS limit_count
        FROM spec_versions v
        LEFT JOIN spec_limits l ON v.version_id = l.version_id
        GROUP BY v.version_id, v.source_file, v.imported_at, v.is_active, v.description
        ORDER BY v.imported_at DESC
        """
    ).fetchall()

    versions: list[dict[str, Any]] = []
    for row in rows:
        versions.append({
            "version_id": row[0],
            "source_file": row[1],
            "imported_at": str(row[2]) if row[2] else None,
            "is_active": bool(row[3]),
            "description": row[4],
            "limit_count": row[5],
        })

    return versions


def get_spec_at_time(timestamp: datetime) -> dict[str, Any]:
    """
    获取指定时间点的有效 Spec（用于历史回溯）。

    在给定时间戳之前最近导入的版本视为当时的有效版本。

    Args:
        timestamp: 查询的时间点。

    Returns:
        dict: 与 get_active_spec() 格式相同的规格数据。
             如果没有符合时间条件的版本，返回空结果。
    """
    conn = get_connection()

    # 查找在 timestamp 之前导入的最近版本
    version_row = conn.execute(
        """
        SELECT version_id, source_file, imported_at, description
        FROM spec_versions
        WHERE imported_at <= ?
        ORDER BY imported_at DESC
        LIMIT 1
        """,
        [timestamp],
    ).fetchone()

    if version_row is None:
        return {
            "version_id": None,
            "source_file": None,
            "imported_at": None,
            "description": None,
            "fai_limits": {},
        }

    version_id = version_row[0]

    limits_rows = conn.execute(
        """
        SELECT fai_name, lower_limit, upper_limit, nominal
        FROM spec_limits
        WHERE version_id = ?
        ORDER BY fai_name
        """,
        [version_id],
    ).fetchall()

    fai_limits: dict[str, dict[str, Optional[float]]] = {}
    for row in limits_rows:
        fai_limits[row[0]] = {
            "lower": row[1],
            "upper": row[2],
            "nominal": row[3],
        }

    return {
        "version_id": version_id,
        "source_file": version_row[1],
        "imported_at": str(version_row[2]) if version_row[2] else None,
        "description": version_row[3],
        "fai_limits": fai_limits,
    }
