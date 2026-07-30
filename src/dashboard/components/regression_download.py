"""
📥 回归后唯一 SN Rawdata 下载面板

独立的 Streamlit 组件，提供：
- 日期范围 + Line 筛选
- 按需查询（避免每次 widget 变化触发全列重查）
- CSV / Excel 双格式下载
- 轻量 / 全列模式切换

调用方只需 `from src.dashboard.components.regression_download import render`。
所有交互状态都封装在自己的 `st.session_state` key 前缀 (`dl_`) 下。
"""

from datetime import date as _date
from io import BytesIO, StringIO
from typing import Optional

import streamlit as st


def render() -> None:
    """
    渲染完整的下载面板。应在主页面 `show()` 函数中调用。
    不依赖任何父函数局部状态，只用 `st.session_state` 持有自己的状态。
    """
    st.subheader("📥 数据下载 — 回归后唯一 SN Rawdata")
    st.caption(
        "按 SN 回归规则（同 SN 取最新记录）去重后的唯一 SN 数据。"
        "**轻量模式**仅输出关键列（SN/Line/Time/Yield/判定），速度 0.1s；"
        "勾选「全部 FAI 列」后输出 1364 列完整测量值。"
    )

    # ── 1. 筛选控件 ──────────────────────────────────
    from src.aggregator.regression import get_regression_unique_sn_fast
    from src.aggregator.top_defects import get_available_date_range

    try:
        min_d, max_d = get_available_date_range()
        min_d = _date.fromisoformat(min_d)
        max_d = _date.fromisoformat(max_d)
    except Exception:
        min_d, max_d = _date(2026, 1, 1), _date.today()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        start_d = st.date_input(
            "起始日期", value=min_d, min_value=min_d, max_value=max_d,
            help="按 Time 字段筛选", key="dl_start",
        )
    with col2:
        end_d = st.date_input(
            "结束日期", value=max_d, min_value=min_d, max_value=max_d,
            help="按 Time 字段筛选（含当天）", key="dl_end",
        )
    with col3:
        cfg_filter = st.text_input(
            "Line（可选）", value="", placeholder="例如: LineA",
            help="留空 = 全部 Line", key="dl_cfg",
        ).strip() or None
    with col4:
        full_cols = st.checkbox(
            "全部 FAI 列", value=False, key="dl_full",
            help="勾选后输出全部 1364 列（含所有 FAI 测量值 + 判定结果），查询变慢约 40 倍",
        )

    # ── 2. 查询按钮（仅在点击时执行） ────────────────
    if st.button(
        "🔍 查询", type="primary", width="stretch",
        help="点击执行查询，不会每次改日期/CFG 都自动查询",
    ):
        with st.spinner("查询中..."):
            df_raw = get_regression_unique_sn_fast(
                cfg=cfg_filter,
                start_date=start_d.isoformat(),
                end_date=end_d.isoformat(),
                full_columns=full_cols,
            )
            st.session_state.dl_df_raw = df_raw
            st.session_state.dl_queried = True

    # ── 3. 结果展示（仅当已查询过） ──────────────────
    if st.session_state.get("dl_queried"):
        df_raw = st.session_state.get("dl_df_raw")
        if df_raw is None or df_raw.empty:
            st.warning("⚠️ 当前筛选条件下无数据，请调整日期或 Line 筛选后重新点击「🔍 查询」")
        else:
            c1, c2, c3 = st.columns([1, 2, 2])
            with c1:
                st.metric(
                    "命中唯一 SN", f"{len(df_raw):,}",
                    help=f"{len(df_raw.columns)} 列",
                )
            with c2:
                st.caption(f"预览（前 5 / {len(df_raw):,} 行）：")
            with c3:
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                parts = ["unique_sn_rawdata", f"{start_d.isoformat()}_to_{end_d.isoformat()}"]
                if cfg_filter:
                    parts.append(f"cfg_{cfg_filter}")
                if full_cols:
                    parts.append("full")
                parts.append(ts)
                fname = "_".join(parts)

                fmt = st.radio(
                    "导出格式", ["CSV", "Excel"], horizontal=True,
                    key="dl_fmt", label_visibility="collapsed",
                )
            st.dataframe(df_raw.head(5), width="stretch", hide_index=True)

            if fmt == "CSV":
                _render_csv_download(df_raw, fname)
            else:
                _render_excel_download(df_raw, fname)


# ────────────────────────────────────────────────────────
# 私有 helpers（仅本组件使用）
# ────────────────────────────────────────────────────────


def _render_csv_download(df, fname: str) -> None:
    """生成 CSV 并提供下载按钮。"""
    buf = StringIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    st.download_button(
        label=f"📥 下载 CSV（{len(df):,} 行 × {len(df.columns)} 列）",
        data=buf.getvalue(),
        file_name=f"{fname}.csv",
        mime="text/csv",
        type="primary",
        width="stretch",
    )


def _render_excel_download(df, fname: str) -> None:
    """生成 Excel 并提供下载按钮。"""
    import pandas as pd

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="UniqueSNDedup")
    st.download_button(
        label=f"📥 下载 Excel（{len(df):,} 行 × {len(df.columns)} 列）",
        data=buf.getvalue(),
        file_name=f"{fname}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
