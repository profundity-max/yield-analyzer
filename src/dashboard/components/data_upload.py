"""
数据上传组件

在 Dashboard 中提供 Excel 文件上传功能，集成导入 + 判定全流程。
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st

from src.config import RAW_DIR, UPLOADS_DIR
from src.importer.excel_reader import (
    detect_fai_columns,
    read_data_sheet,
    read_spec_sheet,
)
from src.importer.parquet_writer import generate_batch_id, write_to_parquet


def render() -> None:
    """渲染数据上传区域。应在汇总看板顶部调用。"""

    with st.expander("📤 上传数据", expanded=False):
        st.markdown(
            '<span style="color:var(--c-navy);font-size:0.85rem">'
            '支持 .xlsx / .xls 格式，请确保包含 <b>Data</b> 和 <b>Spec</b> 两个 Sheet</span>',
            unsafe_allow_html=True,
        )

        uploaded_file = st.file_uploader(
            "选择 Excel 文件",
            type=["xlsx", "xls"],
            key="data_upload",
            label_visibility="collapsed",
        )

        if uploaded_file is not None:
            col_btn, col_info = st.columns([1, 3])
            with col_btn:
                do_import = st.button(
                    "🚀 开始导入",
                    type="primary",
                    use_container_width=True,
                    key="btn_do_import",
                )
            with col_info:
                st.caption(
                    f"已选择: **{uploaded_file.name}** "
                    f"({uploaded_file.size / 1024 / 1024:.1f} MB)"
                )

            if do_import:
                _run_import_pipeline(uploaded_file)


def _get_sheet_names(filepath: str) -> list[str]:
    """获取 Excel 文件的所有 Sheet 名称"""
    import openpyxl
    wb = openpyxl.load_workbook(filepath, read_only=True)
    names = wb.sheetnames
    wb.close()
    return names


def _detect_data_sheet(filepath: str) -> str:
    """自动检测 Data Sheet 名称。

    优先级:
    1. "Data" — 如果存在，直接使用
    2. "Rawdata" — 常见别名
    3. 第一个非 Spec 的 Sheet
    4. 唯一的 Sheet（如果只有一个）

    Raises:
        ValueError: 无法确定 Data Sheet 时抛出，列出所有可用 Sheet。
    """
    sheets = _get_sheet_names(filepath)

    if "Data" in sheets:
        return "Data"
    if "Rawdata" in sheets:
        return "Rawdata"

    # 排除明显是 Spec 的 Sheet
    non_spec = [s for s in sheets if s.lower() != "spec"]

    if len(non_spec) == 1:
        return non_spec[0]

    if len(sheets) == 1:
        return sheets[0]

    raise ValueError(
        f"❌ 无法确定哪个 Sheet 是数据表。当前 Sheet: {', '.join(sheets)}。"
        f"\n请将数据 Sheet 命名为 'Data' 或 'Rawdata'，或确保文件中只有一个非 Spec 的 Sheet。"
    )


def _validate_required_columns(columns: list[str], row_gen):
    """验证 Vendor / Project / Line 三个必填列存在。

    返回 (vendor_ok, project_ok, line_ok, vendor_default, project_default, line_default)
    如果某列有非空数据 → ok=True, default=None
    如果某列全空 → ok=False, default=推断的默认值（从 Line 或文件名推断）

    Raises:
        ValueError: 缺少必填列时抛出。
    """
    required = {"Vendor", "Project", "Line"}
    col_set = set(columns)

    # 1. 列存在性检查
    missing = required - col_set
    if missing:
        raise ValueError(
            f"❌ Data Sheet 缺少必填列: {', '.join(sorted(missing))}。"
            f"\n请确保 Excel 的 Data Sheet 表头包含: Vendor, Project, Line 三个字段。"
            f"\n当前表头(前10列): {', '.join(columns[:10])}..."
        )

    vendor_idx = columns.index("Vendor")
    project_idx = columns.index("Project")
    line_idx = columns.index("Line")

    vendor_ok = project_ok = line_ok = False
    line_value = None

    for row_num, row in enumerate(row_gen, 1):
        if not vendor_ok and row[vendor_idx] is not None and str(row[vendor_idx]).strip() not in ("", "None"):
            vendor_ok = True
        if not project_ok and row[project_idx] is not None and str(row[project_idx]).strip() not in ("", "None"):
            project_ok = True
        if not line_ok and row[line_idx] is not None and str(row[line_idx]).strip() not in ("", "None"):
            line_ok = True
            line_value = str(row[line_idx]).strip()

        if vendor_ok and project_ok and line_ok:
            break
        if row_num >= 5000:
            break

    return vendor_ok, project_ok, line_ok, line_value


def _remove_null_rows(parquet_path: str) -> tuple[int, int]:
    """移除 SN 和 Time 同时为 NULL 的完全空行。

    Returns:
        (清理前行数, 移除行数)
    """
    import duckdb
    conn = duckdb.connect(":memory:")
    try:
        before = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')").fetchone()[0]
        tmp = parquet_path + ".null_clean"
        conn.execute(f"""
            COPY (
                SELECT * FROM read_parquet('{parquet_path}')
                WHERE "SN" IS NOT NULL OR "Time" IS NOT NULL
            ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION SNAPPY)
        """)
        after = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{tmp}')").fetchone()[0]
        os.replace(tmp, parquet_path)
        return before, before - after
    finally:
        conn.close()


def _dedup_raw_parquet(parquet_path: str) -> tuple[int, int]:
    """对 raw parquet 按 SN+Time 去重，保留每组第一条（按原始顺序）。

    Args:
        parquet_path: raw parquet 文件路径

    Returns:
        (去重前行数, 移除行数)
    """
    import duckdb

    conn = duckdb.connect(":memory:")
    try:
        before = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')").fetchone()[0]

        # 用 ROW_NUMBER 按 SN+Time 分区，保留第一条
        temp_path = parquet_path + ".dedup_tmp"
        conn.execute(f"""
            COPY (
                SELECT * EXCLUDE(rn) FROM (
                    SELECT *,
                        ROW_NUMBER() OVER (PARTITION BY "SN", "Time" ORDER BY "SN") AS rn
                    FROM read_parquet('{parquet_path}')
                ) sub
                WHERE rn = 1
            ) TO '{temp_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)
        """)

        after = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{temp_path}')").fetchone()[0]

        os.replace(temp_path, parquet_path)
        return before, before - after
    finally:
        conn.close()


def _run_import_pipeline(uploaded_file) -> None:
    """执行完整的导入 + 判定流程，带进度条。"""

    # ── Step 0: 保存上传文件到临时目录 ──────────────
    progress_bar = st.progress(0, "准备中...")
    status_text = st.empty()

    tmp_path = UPLOADS_DIR / f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    tmp_path.write_bytes(uploaded_file.getvalue())

    batch_id = generate_batch_id()
    output_path = RAW_DIR / f"raw_{batch_id}.parquet"

    try:
        # ── Step 1.5: 探测 Sheet 名称 ──────────────────
        progress_bar.progress(15, "检测 Sheet...")
        status_text.info("📖 正在检测 Sheet 结构...")
        sheet_names = _get_sheet_names(str(tmp_path))
        data_sheet = _detect_data_sheet(str(tmp_path))
        has_spec_sheet = "Spec" in sheet_names

        # ── Step 2: 读取 Spec ─────────────────────────
        progress_bar.progress(20, "读取规格定义...")
        if has_spec_sheet:
            status_text.info("📖 正在读取 Spec Sheet...")
            spec_sheet = "Spec"
            specs = read_spec_sheet(str(tmp_path), sheet_name=spec_sheet)
        else:
            status_text.info("📋 使用系统已激活的规格版本...")
            from src.spec_manager.versioning import get_active_spec
            active = get_active_spec()
            if not active or not active.get("fai_limits"):
                raise ValueError(
                    "❌ 文件中没有 Spec Sheet，且系统中没有已激活的规格版本。"
                    "\n请先上传含 Spec Sheet 的文件，或在「规格管理」页面激活一个版本。"
                )
            # 从数据库 Spec 构造 specs 列表
            specs = [
                {"fai_name": fn, "usl": v["upper"], "nominal": v.get("nominal"), "lsl": v["lower"]}
                for fn, v in active["fai_limits"].items()
                if v.get("upper") is not None and v.get("lower") is not None
            ]
            spec_sheet = "(系统已激活版本)"

        spec_fai_names = [s["fai_name"] for s in specs]
        st.caption(f"✓ 读取到 {len(specs)} 条规格定义（来源: {spec_sheet}）")

        # ── Step 3: 读取 Data 表头 ────────────────────
        progress_bar.progress(30, "读取数据表头...")
        status_text.info("📖 正在读取 Data Sheet 表头...")
        columns, row_gen, total_cols = read_data_sheet(str(tmp_path), sheet_name=data_sheet)
        st.caption(f"✓ 共 {len(columns)} 列（原始 {total_cols} 列）")

        # ── 必填字段验证 ──────────────────────────
        progress_bar.progress(25, "验证必填字段...")
        status_text.info("🔍 正在验证 Vendor / Project / Line 完整性...")
        vend_ok, proj_ok, line_ok, line_val = _validate_required_columns(columns, row_gen)

        fill_vendor = None; fill_project = None
        need_fill = False
        if not vend_ok or not proj_ok:
            need_fill = True
            st.warning("⚠️ 数据中 Vendor 或 Project 字段为空，请补填以下信息：")
            fc1, fc2 = st.columns(2)
            with fc1:
                if not vend_ok:
                    fill_vendor = st.text_input("Vendor（必填）", value="LY",
                                                help="所有行的 Vendor 将设为此值")
                else:
                    st.caption("✓ Vendor 已从数据读取")
            with fc2:
                if not proj_ok:
                    # 尝试从 Line 值推断 Project
                    default_proj = "967E1" if line_val and "L1" in str(line_val).upper() else ""
                    fill_project = st.text_input("Project（必填）", value=default_proj,
                                                 help="所有行的 Project 将设为此值")
                else:
                    st.caption("✓ Project 已从数据读取")

            if not st.button("✅ 确认并继续", type="primary"):
                st.stop()  # 等待用户填写

        st.caption("✓ Vendor / Project / Line 字段验证通过")

        # ── Step 4: 检测 FAI 列 ───────────────────────
        progress_bar.progress(45, "匹配 FAI 列...")
        status_text.info("🔍 正在匹配 FAI 测量列...")
        # 重新读取（row_gen 已被 consume，需要重新获取）
        _, row_gen, _ = read_data_sheet(str(tmp_path), sheet_name=data_sheet)
        matched_fai, unmatched = detect_fai_columns(columns, spec_fai_names)
        st.caption(f"✓ 匹配 {len(matched_fai)} 个 FAI 测量列")

        if len(matched_fai) == 0:
            st.warning("⚠️ 未匹配到任何 FAI 列，请检查 Spec 与 Data 列名是否一致")
            if unmatched:
                st.text(f"未匹配列（前20个）: {unmatched[:20]}")

        # ── Step 4: 写入 Parquet ──────────────────────
        # 收集所有行（生成器转列表以便计数）
        status_text.info("💾 正在写入 Parquet 文件...")
        progress_bar.progress(40, "写入数据...")

        row_count = [0]
        vendor_idx = columns.index("Vendor") if "Vendor" in columns else -1
        project_idx = columns.index("Project") if "Project" in columns else -1

        def progress_cb(rows_written: int, _total: int):
            row_count[0] = rows_written
            pct = min(40 + int(50 * rows_written / max(rows_written, 50000)), 90)
            progress_bar.progress(pct, f"写入 {rows_written:,} 行...")

        # 包装生成器：统计行数 + 填充缺失的 Vendor/Project
        def counting_gen():
            count = 0
            for row in row_gen:
                row_list = list(row)  # 可能需要修改
                if fill_vendor and vendor_idx >= 0 and (row_list[vendor_idx] is None or str(row_list[vendor_idx]).strip() in ("", "None")):
                    row_list[vendor_idx] = fill_vendor
                if fill_project and project_idx >= 0 and (row_list[project_idx] is None or str(row_list[project_idx]).strip() in ("", "None")):
                    row_list[project_idx] = fill_project
                count += 1
                yield row_list
            row_count[0] = count

        _, total_rows = write_to_parquet(
            rows_generator=counting_gen(),
            columns=columns,
            output_path=str(output_path),
            progress_callback=progress_cb,
        )

        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        status_text.success(
            f"✅ Parquet 写入完成: {total_rows:,} 行, {len(columns)} 列, {file_size_mb:.1f} MB"
        )

        # ── Step 4.5: 清理空行 + 去重 ──────────────────
        progress_bar.progress(80, "清理无效数据...")
        status_text.info("🧹 正在清理空行...")
        null_before, null_removed = _remove_null_rows(str(output_path))
        if null_removed > 0:
            st.caption(f"✓ 移除 {null_removed:,} 行完全空数据")
        progress_bar.progress(85, "检测重复数据...")
        status_text.info("🔍 正在检测 SN+Time 重复记录...")
        progress_bar.progress(85, "检测重复数据...")
        status_text.info("🔍 正在检测 SN+Time 重复记录...")
        dup_before, dup_removed = _dedup_raw_parquet(str(output_path))
        if dup_removed > 0:
            status_text.info(f"🗑️ 移除 {dup_removed:,} 条 SN+Time 重复记录（保留首次出现），剩余 {dup_before - dup_removed:,} 行")
            st.caption(f"✓ 重复检测: 发现 {dup_removed:,} 条重复，已自动去除")
        else:
            status_text.info(f"✅ 无重复记录")
            st.caption("✓ 重复检测: 无重复记录")

        # ── Step 5: 自动触发判定 ──────────────────────
        progress_bar.progress(92, "执行 FAI 判定...")
        status_text.info("⚖️ 正在执行 FAI 判定...")
        _run_judge(batch_id, progress_bar, status_text, row_count[0])

        # ── 完成 ──────────────────────────────────────
        progress_bar.progress(100, "完成!")
        status_text.success(
            f"🎉 导入完成！批次: `{batch_id}` | "
            f"{total_rows:,} 行 | {len(matched_fai)} FAI 列 | {file_size_mb:.1f} MB"
        )

        # ── 清除缓存让新数据可见 ──────────────────────
        st.cache_data.clear()
        st.balloons()
        st.rerun()

    except Exception as e:
        progress_bar.progress(100, "失败")
        status_text.error(f"❌ 导入失败: {e}")
        st.exception(e)

    finally:
        # 清理临时文件
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _run_judge(batch_id: str, progress_bar, status_text, total_rows: int) -> None:
    """调用判定引擎对刚导入的批次执行判定。"""
    from src.config import JUDGED_DIR
    from src.judge.engine import judge_batch
    from src.spec_manager.versioning import get_active_spec

    raw_path = RAW_DIR / f"raw_{batch_id}.parquet"
    judged_path = JUDGED_DIR / f"judged_{batch_id}.parquet"

    # 获取激活的 Spec
    spec_data = get_active_spec()
    if spec_data["version_id"] is None:
        status_text.warning("⚠️ 无激活 Spec，跳过判定。请在规格管理页导入并激活 Spec。")
        return

    # 执行判定
    def _judge_progress(completed: int, total: int, step_desc: str):
        pct = 92 + int(8 * completed / max(total, 1))
        progress_bar.progress(min(pct, 99), f"判定: {step_desc}")

    result = judge_batch(
        raw_parquet_path=str(raw_path),
        spec_data=spec_data,
        output_path=str(judged_path),
        progress_callback=_judge_progress,
        resume=False,
    )

    status_text.info(f"✅ 判定完成: {result.get('total_rows', 0):,} 行")


def render_upload_section() -> None:
    """（别名）渲染数据上传区域。"""
    render()
