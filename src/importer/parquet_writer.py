"""
Parquet 写入模块

使用 PyArrow 将数据流分块写入 Parquet 文件。
支持流式写入，每 chunk 生成一个 row group，适合大数据量场景。
"""

import calendar
import uuid
from datetime import timedelta,  date, datetime
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

from src.config import EXCEL_CHUNK_SIZE

# ── 列类型分类 ────────────────────────────────────────────
# 字符串列：存储序列号等标识符
STRING_COLUMNS: set = {"Line", "SN", "Project", "Vendor"}
# 时间戳列：Time 列存储 datetime 值
TIMESTAMP_COLUMNS: set = {"Time"}


def generate_batch_id() -> str:
    """
    生成批次 ID。

    格式: YYYYMMDD_UUID前8位，例如 20260721_a1b2c3d4

    Returns:
        批次 ID 字符串
    """
    today = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{today}_{short_uuid}"


def _infer_schema(columns: List[str]) -> pa.Schema:
    """
    根据列名推断 PyArrow Schema。

    类型推断规则：
    - Line, SN, Project, Vendor → pa.string()（字符串类型）
    - Time → pa.timestamp('ms')（毫秒精度时间戳）
    - 其他所有列 → pa.float64()（双精度浮点）

    Args:
        columns: 列名列表

    Returns:
        PyArrow Schema 对象
    """
    fields: List[pa.Field] = []
    for col in columns:
        if col in STRING_COLUMNS:
            fields.append(pa.field(col, pa.string()))
        elif col in TIMESTAMP_COLUMNS:
            fields.append(pa.field(col, pa.timestamp("ms")))
        else:
            fields.append(pa.field(col, pa.float64()))
    return pa.schema(fields)


def _safe_float(value: Any) -> Optional[float]:
    """
    安全转换为浮点数。

    处理规则：
    - None → None（后续在 PyArrow float64 列中转为 NaN）
    - '#REF!' → None
    - 数值字符串 → float
    - 其他不可转换值 → None

    Args:
        value: 待转换的值

    Returns:
        float 值或 None
    """
    if value is None:
        return None
    if isinstance(value, str):
        if "#REF!" in value:
            return None
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_timestamp(value: Any) -> Optional[int]:
    """
    安全转换为毫秒级时间戳（保留原始显示时间）。

    处理逻辑：
    - 使用 calendar.timegm() 将 datetime 的显示时间直接转为 epoch 毫秒，
      避免 Python datetime.timestamp() 引入的本地时区偏移
    - 这样 Parquet 读回时 wall clock 时间保持不变
    - 例如：datetime(2026,6,28,15,53) → 写入 → 读回 → datetime(2026,6,28,15,53)

    支持类型:
    - datetime / date (原生)
    - str: 解析常见格式 ("2026-07-28 06:59:35", "2026-07-28", "2026/07/28 06:59:35" 等)
    - Excel serial number (浮点数, 自 1900-01-01 起的天数, 整数部分为日期)

    Args:
        value: 待转换的值

    Returns:
        int64 毫秒时间戳，或 None
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        # 将 datetime 的显示值直接转为 epoch，保留 wall clock 时间
        total_seconds = calendar.timegm(value.timetuple())
        return int(total_seconds * 1000) + (value.microsecond // 1000)

    if isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
        total_seconds = calendar.timegm(dt.timetuple())
        return int(total_seconds * 1000)

    # 字符串: 解析多种常见格式
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() in ("none", "null", "nan", "n/a", "-"):
            return None
        # 多种格式尝试
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                total_seconds = calendar.timegm(dt.timetuple())
                return int(total_seconds * 1000) + (dt.microsecond // 1000)
            except ValueError:
                continue
        return None

    # Excel serial date number: 浮点数, 整数部分=天数自 1900-01-00 起
    if isinstance(value, (int, float)):
        try:
            # Excel epoch: 1899-12-30 (处理 1900 闰年 bug)
            base = datetime(1899, 12, 30)
            dt = base + timedelta(days=float(value))
            total_seconds = calendar.timegm(dt.timetuple())
            return int(total_seconds * 1000)
        except (ValueError, OverflowError):
            return None

    return None


def _convert_row(row: List[Any], columns: List[str]) -> Dict[str, Any]:
    """
    将一行原始数据转换为类型正确的字典。

    根据列名确定目标类型，进行相应的类型转换。

    Args:
        row: 原始行数据（列表）
        columns: 列名列表（与 row 顺序对应）

    Returns:
        {列名: 转换后的值} 字典
    """
    result: Dict[str, Any] = {}
    for i, col in enumerate(columns):
        value = row[i] if i < len(row) else None

        if col in STRING_COLUMNS:
            # 字符串列：None 保持 None，其他转字符串
            if value is None:
                result[col] = None
            elif isinstance(value, str) and "#REF!" in value:
                result[col] = None
            else:
                result[col] = str(value)
        elif col in TIMESTAMP_COLUMNS:
            result[col] = _safe_timestamp(value)
        else:
            result[col] = _safe_float(value)

    return result


def _build_record_batch(
    chunk: List[Dict[str, Any]],
    columns: List[str],
    schema: pa.Schema,
) -> pa.RecordBatch:
    """
    将数据字典列表构建为 PyArrow RecordBatch。

    逐列构建数组，确保类型与 schema 一致。

    Args:
        chunk: 转换后的数据行列表
        columns: 列名列表
        schema: PyArrow Schema

    Returns:
        PyArrow RecordBatch
    """
    col_arrays: List[pa.Array] = []
    for col in columns:
        field_type = schema.field(col).type
        values = [row.get(col) for row in chunk]
        col_arrays.append(pa.array(values, type=field_type))

    return pa.RecordBatch.from_arrays(col_arrays, schema=schema)


def write_to_parquet(
    rows_generator: Generator[List[Any], None, None],
    columns: List[str],
    output_path: str,
    chunk_size: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Tuple[str, int]:
    """
    将数据流分块写入 Parquet 文件。

    每 chunk_size 行创建一个 row group，使用 ParquetWriter 流式写入。
    None 值在 float64 列中自动转换为 NaN。

    Args:
        rows_generator: 数据行生成器，每次 yield 一行数据（列表格式）
        columns: 列名列表
        output_path: 输出 Parquet 文件路径
        chunk_size: 每个 row group 的行数，默认使用 EXCEL_CHUNK_SIZE（50000）
        progress_callback: 进度回调函数，签名 (rows_written, total_estimate)

    Returns:
        (output_path, total_rows_written)
    """
    if chunk_size is None:
        chunk_size = EXCEL_CHUNK_SIZE

    # ── 构建 Schema ─────────────────────────────────────
    schema = _infer_schema(columns)

    # ── 创建 ParquetWriter ──────────────────────────────
    writer = pq.ParquetWriter(
        output_path,
        schema,
        compression="snappy",
        use_dictionary=True,
    )

    total_rows = 0
    chunk: List[Dict[str, Any]] = []

    try:
        for row in rows_generator:
            converted = _convert_row(row, columns)
            chunk.append(converted)

            if len(chunk) >= chunk_size:
                batch = _build_record_batch(chunk, columns, schema)
                writer.write_batch(batch)
                total_rows += len(chunk)
                if progress_callback:
                    progress_callback(total_rows, 0)
                chunk = []

        # ── 写入最后一个不完整的 chunk ──────────────────
        if chunk:
            batch = _build_record_batch(chunk, columns, schema)
            writer.write_batch(batch)
            total_rows += len(chunk)
            if progress_callback:
                progress_callback(total_rows, 0)

    finally:
        writer.close()

    return output_path, total_rows
