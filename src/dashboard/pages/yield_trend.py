"""
良率趋势页面 — 按 Project Tabs + 显示模式 Toggle (回归/普通/对比)

ADR-0002: 折线图按 project 区分, 同 project 不同 line 不同颜色
ADR-0003: 顶部 toggle 切换显示模式, 默认回归
"""

from io import BytesIO, StringIO
from datetime import datetime, date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.aggregator.yield_calc import (
    get_daily_yield, get_weekly_yield, get_regression_yield,
    get_daily_yield_by_project_line,
    list_projects, list_lines_for_project,
)
from src.aggregator.regression import get_regression_unique_sn_count
from src.aggregator.top_defects import get_available_date_range
from src.config import DAY_CUTOFF_HOUR


# ────────────────────────────────────────────────────────
# 预缓存 (ADR-0002)
# ────────────────────────────────────────────────────────


@st.cache_data(ttl=600, show_spinner=False)
def _cached_daily_yield_by_project_line(
    project: str, line: str, regression: bool, cutoff_hour: int,
) -> list[dict]:
    return get_daily_yield_by_project_line(
        project=project, line=line, regression=regression, cutoff_hour=cutoff_hour,
    )


@st.cache_data(ttl=600, show_spinner=False)
def _cached_projects() -> list[str]:
    return list_projects()


@st.cache_data(ttl=600, show_spinner=False)
def _cached_lines_for_project(project: str) -> list[str]:
    return list_lines_for_project(project)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_available_date_range() -> tuple[str, str]:
    return get_available_date_range()


# ────────────────────────────────────────────────────────
# 主页面
# ────────────────────────────────────────────────────────


# 颜色调色板 (Plotly 默认色 + 扩展)
LINE_COLORS = [
    "#1f77b4",  # 蓝
    "#ff7f0e",  # 橙
    "#2ca02c",  # 绿
    "#d62728",  # 红
    "#9467bd",  # 紫
    "#8c564b",  # 棕
    "#e377c2",  # 粉
    "#7f7f7f",  # 灰
]


def show():
    st.title("📈 良率趋势分析")

    # ── 顶部控制条 (ADR-0003: 显示模式 toggle) ──────
    ctrl_row = st.columns([1, 1, 1, 1, 1, 1])
    with ctrl_row[0]:
        display_mode = st.radio(
            "显示模式",
            ["📊 回归后", "📋 普通", "🔄 两者对比"],
            index=0,
            horizontal=True,
            key="yt_display_mode",
            help="默认显示回归后良率 (剔除重复投产影响)",
        )
    with ctrl_row[1]:
        granularity = st.selectbox("时间粒度", ["按日", "按周"], key="yt_granularity")
    with ctrl_row[2]:
        cutoff = st.slider(
            "日切点 (时)", 0, 23, DAY_CUTOFF_HOUR, key="yt_cutoff",
            help="数据归属到哪天的时间切点",
        )
    with ctrl_row[3]:
        vendor_filter = st.selectbox("Vendor", ['全部', 'LK', 'LY'], key="yt_vendor")
    with ctrl_row[4]:
        st.write("")  # spacer
        st.write("")
        @st.cache_data(ttl=600, show_spinner="生成下载数据...")
        def _cached_rawdata_csv():
            from src.aggregator.regression import get_regression_unique_sn_rawdata
            df = get_regression_unique_sn_rawdata()
            return df.to_csv(index=False).encode("utf-8-sig"), len(df)
        csv_data, n_rows = _cached_rawdata_csv()
        st.download_button(
            f"📥 下载回归后Rawdata ({n_rows:,} 行)",
            csv_data,
            file_name="regression_rawdata.csv",
            mime="text/csv",
            key="yt_quick_dl",
            help="下载全量回归后唯一SN原始数据")

    st.markdown("---")

    # ── Project Tabs (ADR-0002) ──────────────────────
    try:
        projects = _cached_projects()
    except Exception as e:
        st.error(f"获取 Project 列表失败: {e}")
        return

    if not projects:
        st.info("暂无数据, 请先上传")
        return

    if len(projects) == 1:
        # 只有一个 project, 不显示 tab 直接展示
        selected_project = projects[0]
        _render_project_chart(
            project=selected_project,
            display_mode=display_mode,
            granularity=granularity,
            cutoff=cutoff,
        )
    else:
        # 多个 project 用 tabs
        tabs = st.tabs([f"📦 {p}" for p in projects])
        for tab, project in zip(tabs, projects):
            with tab:
                _render_project_chart(
                    project=project,
                    display_mode=display_mode,
                    granularity=granularity,
                    cutoff=cutoff,
                )

    # ── 回归后 Rawdata 下载面板 ──────────────
    _render_regression_download_panel()


def _render_project_chart(
    project: str,
    display_mode: str,
    granularity: str,
    cutoff: int,
):
    """渲染单个 Project 的良率折线图 (含 Line 多线对比)"""
    try:
        lines = _cached_lines_for_project(project)
    except Exception as e:
        st.error(f"获取 Line 列表失败: {e}")
        return

    if not lines:
        st.info(f"Project `{project}` 暂无数据")
        return

    # 决定要画哪些数据
    is_regression = display_mode in ["📊 回归后", "🔄 两者对比"]
    is_normal = display_mode in ["📋 普通", "🔄 两者对比"]
    is_compare = display_mode == "🔄 两者对比"

    # 拉取数据 (按 line × 模式)
    series_map = {}  # (line, is_regression) -> list[{production_day, yield_pct}]

    for line in lines:
        if is_regression:
            data_reg = _cached_daily_yield_by_project_line(
                project=project, line=line, regression=True, cutoff_hour=cutoff,
            )
            # 回归后无数据的日期用普通数据补齐 (ADR-0003 修订)
            if is_normal:
                data_norm = _cached_daily_yield_by_project_line(
                    project=project, line=line, regression=False, cutoff_hour=cutoff,
                )
                norm_by_day = {d["production_day"]: d for d in data_norm}
                for d in data_reg:
                    if d["total"] == 0:
                        # No data for this date in regression → use normal
                        nd = norm_by_day.get(d["production_day"])
                        if nd:
                            d["yield_pct"] = nd["yield_pct"]
                            d["total"] = nd["total"]
                            d["ok_count"] = nd["ok_count"]
                data_reg = [d for d in data_reg if d["total"] > 0]
            series_map[(line, "回归")] = data_reg
        if is_normal:
            data_norm = _cached_daily_yield_by_project_line(
                project=project, line=line, regression=False, cutoff_hour=cutoff,
            )
            series_map[(line, "普通")] = data_norm

    # 渲染图表
    fig = go.Figure()

    color_idx = 0
    for line in lines:
        if not is_compare:
            # 单模式: 每条 Line 一根线
            label = "回归后" if is_regression else "普通"
            data = series_map.get((line, label), [])
            if not data:
                continue
            color = LINE_COLORS[color_idx % len(LINE_COLORS)]
            color_idx += 1
            dates = [d["production_day"][:10] for d in data]
            yields = [d["yield_pct"] for d in data]
            fig.add_trace(go.Scatter(
                x=dates, y=yields,
                mode='lines+markers',
                name=f'Line {line}',
                line=dict(color=color, width=2.5),
                marker=dict(size=6),
                hovertemplate=f'<b>Line {line}</b><br>%{{x}}<br>良率: %{{y:.2f}}%<extra></extra>',
            ))
        else:
            # 对比模式: 每条 Line 画两根线 (实线=回归, 虚线=普通)
            color = LINE_COLORS[color_idx % len(LINE_COLORS)]
            color_idx += 1
            for kind, dash in [("回归", "solid"), ("普通", "dash")]:
                data = series_map.get((line, kind), [])
                if not data:
                    continue
                dates = [d["production_day"][:10] for d in data]
                yields = [d["yield_pct"] for d in data]
                fig.add_trace(go.Scatter(
                    x=dates, y=yields,
                    mode='lines+markers',
                    name=f'Line {line} ({kind})',
                    line=dict(color=color, width=2, dash=dash),
                    marker=dict(size=5),
                    hovertemplate=f'<b>Line {line} ({kind})</b><br>%{{x}}<br>良率: %{{y:.2f}}%<extra></extra>',
                ))

    # 目标线
    fig.add_hline(
        y=95, line_dash="dot", line_color="red",
        annotation_text="目标 95%",
    )

    # 标题
    mode_label = {
        "📊 回归后": "SN 回归后",
        "📋 普通": "原始 (含重复投产)",
        "🔄 两者对比": "回归 vs 普通 对比",
    }[display_mode]
    fig.update_layout(
        title=f"Project `{project}` 良率趋势 ({mode_label})",
        xaxis_title="日期",
        yaxis_title="良率 (%)",
        yaxis=dict(range=[0, 105]),
        height=450,
        hovermode='x unified',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, width="stretch")

    # ── 明细数据 (按 Line 列表) ─────────────────────
    with st.expander("📋 明细数据", expanded=False):
        tabs_detail = st.tabs([f"Line {l}" for l in lines])
        for tab_d, line in zip(tabs_detail, lines):
            with tab_d:
                if is_regression:
                    data = series_map.get((line, "回归"), [])
                    label = "回归后"
                elif is_normal:
                    data = series_map.get((line, "普通"), [])
                    label = "普通"
                else:
                    # 对比模式显示两者
                    d_reg = series_map.get((line, "回归"), [])
                    d_norm = series_map.get((line, "普通"), [])
                    if d_reg:
                        st.caption(f"**回归后** ({len(d_reg)} 天)")
                        st.dataframe(d_reg, width="stretch", hide_index=True)
                    if d_norm:
                        st.caption(f"**普通** ({len(d_norm)} 天)")
                        st.dataframe(d_norm, width="stretch", hide_index=True)
                    continue
                if data:
                    st.caption(f"**{label}** ({len(data)} 天)")
                    st.dataframe(data, width="stretch", hide_index=True)
                else:
                    st.info(f"Line `{line}` 暂无数据")

    # ── CSV 导出 (按当前 project × line) ─────────────
    st.download_button(
        label=f"📥 导出 {project} 趋势 CSV",
        data=_to_csv(series_map),
        file_name=f"yield_trend_{project}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


def _to_csv(series_map: dict) -> bytes:
    """把 series_map 转成 CSV bytes"""
    import csv, io
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["line", "mode", "production_day", "total", "ok_count", "ng_count", "yield_pct"])
    for (line, mode), data in series_map.items():
        for d in data:
            writer.writerow([line, mode, d["production_day"], d["total"], d["ok_count"], d["ng_count"], d["yield_pct"]])
    return buf.getvalue().encode("utf-8-sig")


# ────────────────────────────────────────────────────────
# 回归后唯一 SN Rawdata 下载面板 (保持原样)
# ────────────────────────────────────────────────────────


def _render_regression_download_panel():
    from src.aggregator.regression import get_regression_unique_sn

    st.markdown("---")
    st.subheader("📥 回归后的唯一 SN Rawdata 下载")
    st.caption(
        "按 **SN 回归规则**（同一 SN 取最新投产记录）去重后的原始测量数据。"
        "默认仅导出 **最近一天**, 仅包含 **元数据 + 测量值** (不包含 _result 判定列与 overall_result), "
        "大幅减少后端计算量与下载体积。展开下方筛选条件可自定义日期/Line/Vendor。"
    )

    try:
        stats = get_regression_unique_sn_count()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("总行数", f"{stats['total_rows']:,}")
        c2.metric("唯一 SN", f"{stats['unique_sn']:,}",
                  delta=f"-{stats['duplicate_rows']:,}", delta_color="off")
        c3.metric("被去重行数", f"{stats['duplicate_rows']:,}")
        c4.metric("去重比例", f"{stats['dedup_ratio_pct']}%")
    except Exception as e:
        st.warning(f"统计信息加载失败: {e}")

    with st.expander("🔧 筛选条件（默认只导最近一天）", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            use_date_range = st.checkbox("按日期筛选", value=True,
                                         help="按 Time 字段过滤数据范围 (默认最近一天)")
        with col2:
            use_line_filter = st.checkbox("按 Line 筛选", value=False)
        with col3:
            use_vendor_filter = st.checkbox("按 Vendor 筛选", value=False,
                                            help="按 Vendor (LY/LK) 过滤")
        with col4:
            export_format = st.radio(
                "导出格式", ["CSV", "Excel (.xlsx)"],
                horizontal=True, key="reg_export_format"
            )

        start_date = end_date = line_value = vendor_value = None

        if use_date_range:
            try:
                min_d, max_d = _cached_available_date_range()
                min_d = date.fromisoformat(min_d)
                max_d = date.fromisoformat(max_d)
            except Exception:
                min_d = date(2026, 1, 1)
                max_d = date.today()

            # 默认最近一天 (start = end = max)
            dc1, dc2 = st.columns(2)
            with dc1:
                start_date = st.date_input("起始日期", value=max_d,
                                           min_value=min_d, max_value=max_d,
                                           key="reg_start")
            with dc2:
                end_date = st.date_input("结束日期", value=max_d,
                                         min_value=min_d, max_value=max_d,
                                         key="reg_end")

        if use_line_filter:
            line_value = st.text_input(
                "Line 值", value="",
                help="输入精确的 Line 名称, 留空表示不过滤"
            ).strip() or None

        if use_vendor_filter:
            vendor_value = st.selectbox(
                "Vendor", options=["LY", "LK"],
                help="选择要筛选的 Vendor"
            )

    st.markdown("##### 预览（前 20 行）")
    try:
        df_preview = get_regression_unique_sn(
            cfg=line_value,
            vendor=vendor_value,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat() if end_date else None,
            columns="minimal",
        )
    except Exception as e:
        st.error(f"查询失败: {e}")
        return

    if df_preview.empty:
        st.warning("当前筛选条件下无数据")
        return

    st.caption(f"命中行数: **{len(df_preview):,}** 行, **{len(df_preview.columns)}** 列")
    st.dataframe(df_preview.head(20), width="stretch", hide_index=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = ["regression_unique_sn"]
    if start_date:
        parts.append(f"from{start_date.isoformat()}")
    if end_date:
        parts.append(f"to{end_date.isoformat()}")
    if vendor_value:
        parts.append(f"Vendor_{vendor_value}")
    if line_value:
        parts.append(f"Line_{line_value}")
    parts.append(ts)
    base_name = "_".join(parts)

    if export_format == "CSV":
        csv_buf = StringIO()
        df_preview.to_csv(csv_buf, index=False, encoding="utf-8-sig")
        st.download_button(
            label=f"📥 下载 CSV ({len(df_preview):,} 行)",
            data=csv_buf.getvalue(),
            file_name=f"{base_name}.csv",
            mime="text/csv",
            type="primary",
            width="stretch",
        )
    else:
        xlsx_buf = BytesIO()
        with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
            df_preview.to_excel(writer, index=False, sheet_name="RegressionRawdata")
        st.download_button(
            label=f"📥 下载 Excel ({len(df_preview):,} 行)",
            data=xlsx_buf.getvalue(),
            file_name=f"{base_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            width="stretch",
        )

    with st.expander("ℹ️ 字段说明"):
        st.markdown(
            """
            - **SN**: 序列号
            - **Project**: 项目代号
            - **Vendor**: 供应商
            - **Line**: 产线/线体
            - **Time**: 测量时间
            - **Yield1/2/3**: 直通率分段 (旧字段, 已统一)
            - **`<FAI>`**: 测量列原始值
            - **`<FAI>_result`**: 该 FAI 判定结果 (0=OK, 1=NG)
            - **overall_result**: 该 SN 整条记录最终判定

            **回归规则**: 同一 SN 多次投产时, 仅保留 Time 最新的一条记录。
            """
        )
