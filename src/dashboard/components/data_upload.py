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
        # ── Step 1: 读取 Spec ─────────────────────────
        progress_bar.progress(10, "读取规格定义...")
        status_text.info("📖 正在读取 Spec Sheet...")
        specs = read_spec_sheet(str(tmp_path), sheet_name="Spec")
        spec_fai_names = [s["fai_name"] for s in specs]
        st.caption(f"✓ 读取到 {len(specs)} 条规格定义")

        # ── Step 2: 读取 Data 表头 ────────────────────
        progress_bar.progress(25, "读取数据表头...")
        status_text.info("📖 正在读取 Data Sheet 表头...")
        columns, row_gen, total_cols = read_data_sheet(str(tmp_path), sheet_name="Data")
        st.caption(f"✓ 共 {len(columns)} 列（原始 {total_cols} 列）")

        # ── Step 3: 检测 FAI 列 ───────────────────────
        progress_bar.progress(35, "匹配 FAI 列...")
        status_text.info("🔍 正在匹配 FAI 测量列...")
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

        def progress_cb(rows_written: int, _total: int):
            row_count[0] = rows_written
            pct = min(40 + int(50 * rows_written / max(rows_written, 50000)), 90)
            progress_bar.progress(pct, f"写入 {rows_written:,} 行...")

        # 包装生成器以统计行数
        def counting_gen():
            count = 0
            for row in row_gen:
                count += 1
                yield row
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
