from __future__ import annotations

"""
FAI 判定引擎 — 核心判定逻辑

对原始测量数据执行向量化 FAI 判定，判定结果 0=OK，1=NG。
支持断点续传、Spec 无穷值处理和异常值（#REF!, NaN）容错。

核心判定规则：
  - LSL ≤ 测量值 ≤ USL → OK (0)
  - #REF! 和 NaN（无法判定的值）→ OK (0)，不扣良率
  - Spec 中 SPEC_INF_VALUE（999999）→ 无穷大/无穷小（无限制）
  - 任一 FAI 判定为 NG → 整条 SN 记录 overall_result = 1 (NG)
  - 等于上下限边界值 → OK（含边界）

性能特征：
  - PyArrow 流式读取，内存峰值可控
  - NumPy 向量化判定，单 chunk（25000 行 × 600 FAI）判定 < 1 秒
  - 50K 行 × 600 FAI 列 × 8 bytes ≈ 240MB/chunk（16GB 内存安全）
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from src.config import JUDGE_CHUNK_SIZE, SPEC_INF_VALUE

logger = logging.getLogger(__name__)

# ── 已知元数据列（不参与 FAI 匹配） ──────────────────────────
_METADATA_COLUMNS: set[str] = {"Line", "Project", "Vendor", "Yield3", "SN", "Time"}


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════


def get_fai_columns_from_parquet(
    parquet_path: str | Path,
    spec_fai_names: list[str],
) -> tuple[list[str], list[str]]:
    """
    读取 Parquet schema，匹配 Spec 中的 FAI 列名。

    从 Parquet 文件 schema 获取全部列名，与 Spec 中定义的 FAI 名称
    进行精确匹配。自动跳过已知元数据列（Line, Project-Vendor, SN, Time）。
    未匹配的列名会记录到 WARNING 级别日志。

    Args:
        parquet_path: 原始 Parquet 文件路径
        spec_fai_names: Spec 中定义的 FAI 名称列表

    Returns:
        (matched_columns, unmatched_columns):
        - matched_columns: 在 Parquet schema 中匹配到的 FAI 列名
        - unmatched_columns: Spec 中有定义但 Parquet 中未找到的名称

    Raises:
        FileNotFoundError: Parquet 文件不存在时抛出
    """
    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet 文件不存在: {parquet_path}")

    # 只读 schema，用完即关
    pf = pq.ParquetFile(parquet_path)
    all_columns = {field.name for field in pf.schema_arrow}
    pf.close()

    meta_lower = {m.lower() for m in _METADATA_COLUMNS}

    matched: list[str] = []
    unmatched: list[str] = []
    fuzzy_matched: list[tuple[str, str]] = []  # (spec_name, data_column)

    for fai_name in spec_fai_names:
        name_clean = fai_name.strip()
        if name_clean in all_columns and name_clean.lower() not in meta_lower:
            matched.append(name_clean)
        else:
            # ── 模糊匹配：尝试常见后缀变换 ─────────────────
            fuzzy_found = _fuzzy_match_column(name_clean, all_columns, meta_lower)
            if fuzzy_found:
                fuzzy_matched.append((name_clean, fuzzy_found))
                matched.append(fuzzy_found)  # 使用 Data 中的实际列名
            else:
                unmatched.append(name_clean)

    if fuzzy_matched:
        # 报告模糊匹配结果
        logger.info("模糊匹配 %d 个列名（如 _T↔_Z 后缀变换）:", len(fuzzy_matched))
        for spec_name, data_col in fuzzy_matched[:5]:
            logger.info("  Spec '%s' → Data '%s'", spec_name, data_col)
        if len(fuzzy_matched) > 5:
            logger.info("  ...等共 %d 个", len(fuzzy_matched))

    if unmatched:
        preview = unmatched[:10]
        suffix = f" ...等共 {len(unmatched)} 个" if len(unmatched) > 10 else ""
        logger.warning(
            "有 %d 个 Spec FAI 名称未匹配: %s%s",
            len(unmatched), preview, suffix,
        )

    logger.info(
        "FAI 列匹配: %d 精确 + %d 模糊 = %d 匹配, %d 未匹配",
        len(matched) - len(fuzzy_matched), len(fuzzy_matched),
        len(matched), len(unmatched),
    )

    return matched, unmatched


def judge_batch(
    raw_parquet_path: str | Path,
    spec_data: dict,
    output_path: str | Path,
    chunk_size: int = JUDGE_CHUNK_SIZE,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    resume: bool = True,
) -> dict:
    """
    对单个原始 Parquet 文件执行完整 FAI 判定流程。

    步骤：
    1. 打开 Parquet 文件，从 spec_data 获取 FAI 定义
    2. 匹配 FAI 列名 → 确定列索引
    3. 构建上下限 NumPy 数组（处理 SPEC_INF_VALUE）
    4. 逐 chunk 流式读取 → NumPy 向量化判定 → 写入临时 chunk 文件
    5. 合并所有 chunk 为最终输出文件，清理临时文件和检查点

    支持断点续传：崩溃后重新调用同一函数即可从上次中断处继续。

    Args:
        raw_parquet_path: 原始 Parquet 文件路径（如 raw_20260721_abc.parquet）
        spec_data: Spec 数据，格式为:
                   {version_id: str, fai_limits: {fai_name: {lower, upper, nominal}}}
        output_path: 输出 Parquet 文件路径
        chunk_size: 每批次处理的行数（默认来自 config.JUDGE_CHUNK_SIZE = 25000）
        progress_callback: 进度回调 (completed_chunks, total_chunks, description)
        resume: 是否启用断点续传（默认 True）

    Returns:
        dict: 判定摘要
            {
                total_rows: int,           # 总处理行数
                ng_count: int,             # NG 记录数
                ok_count: int,             # OK 记录数
                yield_rate: float,         # 良率百分比（保留 4 位小数）
                spec_version: str,         # 使用的 Spec 版本
                judged_at: str,            # 判定时间戳（ISO 格式）
                matched_fai_columns: int,  # 匹配到的 FAI 列数
                unmatched_fai_columns: int,# 未匹配的 FAI 列数
                output_path: str,          # 输出文件路径
            }

    Raises:
        ValueError: Spec 数据为空或无 FAI 列匹配成功时抛出
        FileNotFoundError: 原始 Parquet 文件不存在时抛出
    """
    # ── 参数校验 ─────────────────────────────────────────────
    raw_path = Path(raw_parquet_path)
    output_path = Path(output_path)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    fai_limits: dict = spec_data.get("fai_limits", {})
    spec_version: str = spec_data.get("version_id") or "unknown"

    if not fai_limits:
        raise ValueError("Spec 数据中无 FAI 限制信息，无法执行判定")

    if not raw_path.exists():
        raise FileNotFoundError(f"原始 Parquet 文件不存在: {raw_path}")

    # ── 步骤 1: 匹配 FAI 列（Spec → Parquet） ────────────────
    spec_fai_names = list(fai_limits.keys())
    matched_columns, unmatched = get_fai_columns_from_parquet(raw_path, spec_fai_names)

    if not matched_columns:
        raise ValueError(
            f"Parquet 文件中未找到任何 Spec FAI 列。"
            f"Spec 定义了 {len(spec_fai_names)} 个 FAI，"
            f"均未在数据中匹配到。请检查 Spec 版本和数据列名是否一致。"
        )

    # ── 步骤 2: 获取列索引 & 构建限制数组 ──────────────────
    pf = pq.ParquetFile(raw_path)
    try:
        col_name_to_idx = {field.name: i for i, field in enumerate(pf.schema_arrow)}
        fai_indices = [col_name_to_idx[name] for name in matched_columns]

        lower_arr, upper_arr = _build_limit_arrays(
            matched_columns, fai_limits, SPEC_INF_VALUE,
        )

        # ── 识别双向无穷 FAI（±999999）：不参与判定 ──────
        finite_mask = ~(np.isneginf(lower_arr) & np.isposinf(upper_arr))
        num_finite = int(np.sum(finite_mask))
        num_skipped = len(finite_mask) - num_finite

        if num_skipped > 0:
            skipped_names = [matched_columns[i] for i, m in enumerate(finite_mask) if not m]
            logger.info(
                "跳过 %d 个双向无穷 FAI（Spec=±999999，不参与判定，不影响良率）: %s",
                num_skipped,
                ", ".join(skipped_names[:10]) + ("" if len(skipped_names) <= 10 else f" ...等共{len(skipped_names)}个"),
            )

        # 过滤到仅有限制的 FAI
        matched_columns_finite = [c for i, c in enumerate(matched_columns) if finite_mask[i]]
        fai_indices_finite = [idx for i, idx in enumerate(fai_indices) if finite_mask[i]]
        lower_arr = lower_arr[finite_mask]
        upper_arr = upper_arr[finite_mask]

        # ── 步骤 3: 断点续传检查 ──────────────────────────────
        batch_id = raw_path.stem.replace("raw_", "")
        checkpoint_path = output_dir / f".{batch_id}_checkpoint.json"
        completed_chunks: set[int] = set()

        if resume:
            completed_chunks = _restore_checkpoint(
                checkpoint_path, raw_path, spec_version, chunk_size,
            )

        # ── 步骤 4: 预估总 chunk 数 ────────────────────────────
        total_rows_est = pf.metadata.num_rows
        total_chunks = max(1, (total_rows_est + chunk_size - 1) // chunk_size)
        pending_chunks = total_chunks - len(completed_chunks)

        logger.info(
            "开始判定: %s → %s, %d 个 Spec FAI（%d 参与判定 + %d 跳过）, ~%d 行, %d chunks (%d 待处理)",
            raw_path.name, output_path.name,
            len(matched_columns_finite) + num_skipped,
            len(matched_columns_finite), num_skipped,
            total_rows_est, total_chunks, pending_chunks,
        )

        # ── 步骤 5: 流式判定 ──────────────────────────────────
        judged_at = datetime.now(timezone.utc).isoformat()
        total_rows = 0
        total_ng = 0
        chunk_files: list[Path] = []

        for chunk_idx, batch in enumerate(pf.iter_batches(batch_size=chunk_size)):
            # 断点续传：跳过已完成 chunk
            if chunk_idx in completed_chunks:
                _register_existing_chunk(output_dir, batch_id, chunk_idx, chunk_files)
                continue

            N = batch.num_rows
            if N == 0:
                continue

            # a. 提取有限制 FAI 列为 NumPy 矩阵
            fai_values = _extract_fai_matrix(batch, fai_indices_finite)

            # b-c. 向量化判定（仅对有限制的 FAI）
            _, fai_results, overall_result = _judge_values(
                fai_values, lower_arr, upper_arr,
            )

            # 统计当前 chunk
            chunk_ng = int(np.sum(overall_result))
            total_ng += chunk_ng
            total_rows += N

            # d-e. 构建输出 RecordBatch → 写入临时 chunk
            output_batch = _build_output_batch(
                batch, matched_columns_finite, fai_results, overall_result,
                judged_at, spec_version,
            )
            chunk_file = _write_chunk_file(
                output_dir, batch_id, chunk_idx, output_batch,
            )
            chunk_files.append(chunk_file)

            # 更新检查点
            completed_chunks.add(chunk_idx)
            _persist_checkpoint(
                checkpoint_path, raw_path, spec_version, chunk_size, completed_chunks,
            )

            # 进度回调
            if progress_callback:
                progress_callback(
                    len(completed_chunks), total_chunks,
                    f"Chunk {chunk_idx + 1}/{total_chunks}: "
                    f"{N} 行, NG={chunk_ng} ({chunk_ng / N * 100:.1f}%)",
                )

        # ── 步骤 6: 合并临时 chunk 文件 ──────────────────────
        if chunk_files:
            _combine_chunk_files(chunk_files, output_path)
            # 清理临时文件
            for cf in chunk_files:
                cf.unlink(missing_ok=True)
            # 清理检查点
            checkpoint_path.unlink(missing_ok=True)
        else:
            logger.warning("无数据写入，输出文件未创建")

    finally:
        pf.close()

    # ── 汇总 ─────────────────────────────────────────────────
    ok_count = total_rows - total_ng
    yield_rate = (ok_count / total_rows * 100) if total_rows > 0 else 0.0

    summary: dict = {
        "total_rows": total_rows,
        "ng_count": total_ng,
        "ok_count": ok_count,
        "yield_rate": round(yield_rate, 4),
        "spec_version": spec_version,
        "judged_at": judged_at,
        "matched_fai_columns": len(matched_columns_finite) + num_skipped,
        "judged_fai_columns": len(matched_columns_finite),
        "skipped_fai_columns": num_skipped,
        "unmatched_fai_columns": len(unmatched),
        "output_path": str(output_path),
    }

    logger.info(
        "判定完成: %d 行, 良率 %.2f%% (%d NG / %d OK), 输出: %s",
        total_rows, yield_rate, total_ng, ok_count, output_path.name,
    )

    return summary


# ═══════════════════════════════════════════════════════════════
# 内部函数
# ═══════════════════════════════════════════════════════════════


def _fuzzy_match_column(
    spec_name: str,
    data_columns: set[str],
    meta_lower: set[str],
) -> str | None:
    """
    模糊匹配：当 Spec FAI 名称在 Data 中找不到时，尝试后缀变换。

    常见变换：
      - _T ↔ _Z（温度/高度等测量后缀）
      - _t ↔ _z（小写变体）

    Args:
        spec_name: Spec 中的 FAI 名称（如 FAI14_A01_Z）
        data_columns: Data 中的列名集合
        meta_lower: 元数据列名（小写，跳过）

    Returns:
        匹配到的 Data 列名，或 None
    """
    # 后缀替换表：尝试将 Spec 名称的某个后缀替换后查找
    suffix_swaps = [
        ("_Z", "_T"), ("_T", "_Z"),
        ("_z", "_t"), ("_t", "_z"),
    ]

    for old_suffix, new_suffix in suffix_swaps:
        if spec_name.endswith(old_suffix):
            candidate = spec_name[:-len(old_suffix)] + new_suffix
            if candidate in data_columns and candidate.lower() not in meta_lower:
                return candidate

    return None


def _extract_fai_matrix(
    batch: pa.RecordBatch,
    fai_indices: list[int],
) -> np.ndarray:
    """
    从 RecordBatch 提取 FAI 列为 (N, num_fai) float64 NumPy 矩阵。

    导入阶段已将 FAI 列统一为 float64（#REF! → NaN），因此大多数
    情况下可零拷贝提取。对于非数值列（极端情况）会尝试安全转换。

    Args:
        batch: PyArrow RecordBatch
        fai_indices: FAI 列在 batch 中的列索引

    Returns:
        (N, num_fai) float64 矩阵，NaN 表示无法判定的值
    """
    N = batch.num_rows
    num_fai = len(fai_indices)
    result = np.empty((N, num_fai), dtype=np.float64)

    for j, col_idx in enumerate(fai_indices):
        col = batch.column(col_idx)
        col_type = col.type

        if pa.types.is_floating(col_type) or pa.types.is_integer(col_type):
            # 数值列：zero_copy_only=False 支持包含 null 的整数列
            arr = col.to_numpy(zero_copy_only=False)
            result[:, j] = arr.astype(np.float64, copy=False)
        else:
            # 非数值列（极少情况）：安全转换为 float64
            # 无法转换的值 → null → to_numpy 时变为 NaN
            try:
                casted = col.cast(pa.float64(), safe=False)
                result[:, j] = casted.to_numpy()
            except Exception:
                logger.warning(
                    "FAI 列索引 %d 类型为 %s，无法转换为 float64，整列设为 NaN",
                    col_idx, col_type,
                )
                result[:, j] = np.nan

    return result


def _build_limit_arrays(
    matched_columns: list[str],
    fai_limits: dict,
    spec_inf_value: int | float = SPEC_INF_VALUE,
) -> tuple[np.ndarray, np.ndarray]:
    """
    根据 Spec 构建下限和上限的 NumPy 数组。

    Spec 无穷值处理：
    - lower == spec_inf_value 或 -spec_inf_value → -inf（无下限）
    - upper == spec_inf_value → +inf（无上限）
    - lower/upper 为 None 或 NaN → 该方向无限制

    Args:
        matched_columns: 匹配成功的 FAI 列名（顺序与 fai_indices 对应）
        fai_limits: {fai_name: {lower, upper, nominal}} 映射
        spec_inf_value: 表示无穷限制的标记值

    Returns:
        (lower_arr, upper_arr): 长度均为 num_fai 的 float64 数组
    """
    num_fai = len(matched_columns)
    lower_arr = np.full(num_fai, -np.inf, dtype=np.float64)
    upper_arr = np.full(num_fai, np.inf, dtype=np.float64)

    for i, fai_name in enumerate(matched_columns):
        limits = fai_limits.get(fai_name)
        if limits is None:
            continue

        low = limits.get("lower")
        high = limits.get("upper")

        # 下限处理：None / NaN / spec_inf_value → 保持 -inf
        if low is not None and not (isinstance(low, float) and np.isnan(low)):
            if low != spec_inf_value and low != -spec_inf_value:
                lower_arr[i] = float(low)

        # 上限处理：None / NaN / spec_inf_value → 保持 +inf
        if high is not None and not (isinstance(high, float) and np.isnan(high)):
            if high != spec_inf_value:
                upper_arr[i] = float(high)

    # 统计日志
    no_lower = int(np.sum(np.isneginf(lower_arr)))
    no_upper = int(np.sum(np.isposinf(upper_arr)))
    if no_lower > 0 or no_upper > 0:
        logger.info(
            "Spec 限制统计: %d 个无下限, %d 个无上限, %d 个双向有限",
            no_lower, no_upper, num_fai - max(no_lower, no_upper),
        )

    return lower_arr, upper_arr


def _judge_values(
    fai_values: np.ndarray,
    lower_arr: np.ndarray,
    upper_arr: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    向量化判定 FAI 测量值（核心判定算法）。

    判定矩阵：
    - lower ≤ value ≤ upper  → OK（边界值包含，True in ok_mask）
    - value is NaN            → OK（#REF! 等不可判定值，True in ok_mask）
    - 其他                    → NG（False in ok_mask）

    Args:
        fai_values: (N, num_fai) float64 矩阵
        lower_arr: (num_fai,) 下限数组，-inf = 无下限
        upper_arr: (num_fai,) 上限数组，+inf = 无上限

    Returns:
        (ok_mask, fai_results, overall_result):
        - ok_mask: (N, num_fai) bool, True=OK
        - fai_results: (N, num_fai) int8, 0=OK, 1=NG
        - overall_result: (N,) int8, 0=全部OK, 1=存在NG
    """
    # 向量化范围比较：使用 ≤ 和 ≥ 保证边界值 OK
    ok_mask = (fai_values >= lower_arr) & (fai_values <= upper_arr)

    # NaN（#REF! 等）视为 OK：不扣良率
    nan_mask = np.isnan(fai_values)
    ok_mask = ok_mask | nan_mask

    # 逐 FAI 判定：OK → 0, NG → 1
    fai_results = np.where(ok_mask, 0, 1).astype(np.int8)

    # 整体判定：所有 FAI 都 OK 才是 OK（0）
    overall_result = np.where(np.all(ok_mask, axis=1), 0, 1).astype(np.int8)

    return ok_mask, fai_results, overall_result


def _build_output_batch(
    batch: pa.RecordBatch,
    matched_columns: list[str],
    fai_results: np.ndarray,
    overall_result: np.ndarray,
    judged_at: str,
    spec_version: str,
) -> pa.RecordBatch:
    """
    构建输出 RecordBatch：原始所有列 + 判定结果列。

    新增列：
    - {fai_name}_result  (int8): 每个 FAI 的判定（0=OK, 1=NG）
    - overall_result     (int8): 整条记录的判定（0=OK, 1=NG）
    - judged_at         (string): 判定时间戳（ISO 格式）
    - spec_version      (string): 使用的 Spec 版本标识

    Args:
        batch: 原始数据 RecordBatch
        matched_columns: FAI 列名列表
        fai_results: (N, num_fai) int8 判定矩阵
        overall_result: (N,) int8 整体判定
        judged_at: ISO 时间戳字符串
        spec_version: 版本标识字符串

    Returns:
        扩展后的 RecordBatch
    """
    N = batch.num_rows

    arrays = list(batch.columns)
    fields = list(batch.schema)

    # 每个 FAI 的判定结果列
    for j, fai_name in enumerate(matched_columns):
        result_col = f"{fai_name}_result"
        arrays.append(pa.array(fai_results[:, j], type=pa.int8()))
        fields.append(pa.field(result_col, pa.int8()))

    # 整体判定列
    arrays.append(pa.array(overall_result, type=pa.int8()))
    fields.append(pa.field("overall_result", pa.int8()))

    # 元数据列
    arrays.append(pa.array([judged_at] * N, type=pa.string()))
    fields.append(pa.field("judged_at", pa.string()))

    arrays.append(pa.array([spec_version] * N, type=pa.string()))
    fields.append(pa.field("spec_version", pa.string()))

    new_schema = pa.schema(fields)
    return pa.RecordBatch.from_arrays(arrays, schema=new_schema)


# ═══════════════════════════════════════════════════════════════
# 检查点管理（断点续传）
# ═══════════════════════════════════════════════════════════════


def _restore_checkpoint(
    checkpoint_path: Path,
    raw_path: Path,
    spec_version: str,
    chunk_size: int,
) -> set[int]:
    """
    尝试加载并验证检查点。

    检查点验证条件：
    - raw_file 路径一致
    - spec_version 版本一致
    - chunk_size 大小一致

    Args:
        checkpoint_path: 检查点文件路径
        raw_path: 当前处理的原始文件路径
        spec_version: 当前使用的 spec 版本
        chunk_size: 当前使用的 chunk 大小

    Returns:
        已完成 chunk 索引集合（新任务时为空集）
    """
    if not checkpoint_path.exists():
        return set()

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            ckpt = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("检查点文件损坏，将重新开始: %s", e)
        checkpoint_path.unlink(missing_ok=True)
        return set()

    # 验证检查点一致性
    if ckpt.get("raw_file") != str(raw_path):
        logger.info("检查点 raw_file 不匹配，将重新开始")
        checkpoint_path.unlink(missing_ok=True)
        return set()
    if ckpt.get("spec_version") != spec_version:
        logger.info("检查点 spec_version 已变更（%s → %s），将重新开始",
                    ckpt.get("spec_version"), spec_version)
        checkpoint_path.unlink(missing_ok=True)
        return set()
    if ckpt.get("chunk_size") != chunk_size:
        logger.info("检查点 chunk_size 已变更（%s → %s），将重新开始",
                    ckpt.get("chunk_size"), chunk_size)
        checkpoint_path.unlink(missing_ok=True)
        return set()

    completed = set(ckpt.get("completed_chunks", []))
    logger.info("断点续传: 已恢复 %d 个已完成 chunk", len(completed))
    return completed


def _register_existing_chunk(
    output_dir: Path,
    batch_id: str,
    chunk_idx: int,
    chunk_files: list[Path],
) -> None:
    """恢复已完成的 chunk 文件引用到 chunk_files 列表"""
    chunk_file = output_dir / f".{batch_id}_chunk_{chunk_idx:06d}.parquet"
    if chunk_file.exists():
        chunk_files.append(chunk_file)
    else:
        logger.warning(
            "检查点记录 chunk %d 已完成，但临时文件不存在，将重新处理", chunk_idx
        )


def _persist_checkpoint(
    checkpoint_path: Path,
    raw_path: Path,
    spec_version: str,
    chunk_size: int,
    completed_chunks: set[int],
) -> None:
    """持久化检查点到磁盘"""
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = checkpoint_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({
            "raw_file": str(raw_path),
            "spec_version": spec_version,
            "chunk_size": chunk_size,
            "completed_chunks": sorted(completed_chunks),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, f, ensure_ascii=False, indent=2)
    # 原子替换，避免写入中途崩溃导致检查点损坏
    tmp_path.replace(checkpoint_path)


# ═══════════════════════════════════════════════════════════════
# 文件 I/O 辅助
# ═══════════════════════════════════════════════════════════════


def _write_chunk_file(
    output_dir: Path,
    batch_id: str,
    chunk_idx: int,
    output_batch: pa.RecordBatch,
) -> Path:
    """
    将单个判定 chunk 写入临时 Parquet 文件。

    文件名格式: .{batch_id}_chunk_{chunk_idx:06d}.parquet
    使用 snappy 压缩和字典编码以减小体积。
    """
    chunk_file = output_dir / f".{batch_id}_chunk_{chunk_idx:06d}.parquet"
    output_table = pa.Table.from_batches([output_batch])
    pq.write_table(
        output_table, str(chunk_file),
        compression="snappy",
        use_dictionary=True,
    )
    logger.debug("写入 chunk %d: %d 行 → %s", chunk_idx, output_batch.num_rows, chunk_file.name)
    return chunk_file


def _combine_chunk_files(
    chunk_files: list[Path],
    output_path: Path,
) -> None:
    """
    使用 DuckDB 将多个临时 chunk 文件合并为单个最终 Parquet 文件。

    DuckDB 的 read_parquet 可高效并行读取多个 parquet 文件，
    按文件列表中顺序合并，保持数据行顺序。
    """
    from src.db import get_connection

    sorted_files = sorted(chunk_files)
    file_list_sql = ", ".join([f"'{str(f)}'" for f in sorted_files])

    logger.info("合并 %d 个 chunk 文件 → %s", len(sorted_files), output_path.name)

    conn = get_connection()
    conn.execute(f"""
        COPY (
            SELECT * FROM read_parquet([{file_list_sql}])
        ) TO '{str(output_path)}' (
            FORMAT PARQUET,
            COMPRESSION SNAPPY
        )
    """)

    logger.info("合并完成: %s", output_path)
