"""
不良分析页面 — TOP N 不良 + 逐日趋势 + NG 明细钻取 + 下载
支持: 回归前/回归后 Toggle, Project/Vendor/Line 筛选
"""

from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.aggregator.top_defects import (
    get_top_defects, get_top_defects_by_date, get_top_defects_regression,
    get_fai_defect_detail, get_daily_top_trend, get_available_date_range,
    get_all_ng_sns_regression,
)
from src.aggregator.yield_calc import list_projects
from src.config import DAY_CUTOFF_HOUR


@st.cache_data(ttl=300)
def load_date_range():
    return get_available_date_range()


@st.cache_data(ttl=300)
def load_overall_defects(top_n: int = 50, regression: bool = False):
    if regression:
        return get_top_defects_regression(top_n=top_n)
    return get_top_defects(top_n=top_n)


@st.cache_data(ttl=300)
def load_date_defects(start: str, end: str, top_n: int, regression: bool = False):
    return get_top_defects_by_date(start, end, top_n=top_n)


@st.cache_data(ttl=300)
def load_daily_trend(fai_names: list[str], start: str, end: str):
    return get_daily_top_trend(fai_names, start, end)


def show():
    st.title("🔴 不良分析")

    # ── 筛选器行 ────────────────────────────────────
    date_range = load_date_range()
    min_date = datetime.strptime(date_range[0], "%Y-%m-%d") if date_range[0] else datetime(2026, 6, 28)
    max_date = datetime.strptime(date_range[1], "%Y-%m-%d") if date_range[1] else datetime.today()

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        start_date = st.date_input("开始日期", value=max_date - timedelta(days=7),
                                    min_value=min_date, max_value=max_date)
    with filter_col2:
        end_date = st.date_input("结束日期", value=max_date,
                                  min_value=min_date, max_value=max_date)
    with filter_col3:
        regression_mode = st.toggle("回归后", value=True, help="基于回归后唯一 SN 计算不良 TOP")

    # Project/Vendor/Line 筛选器
    proj_col, vendor_col, line_col = st.columns(3)
    with proj_col:
        projects = ["全部"] + list_projects()
        selected_project = st.selectbox("Project", projects)
    with vendor_col:
        vendors_list = ['全部', 'LK', 'LY']
        selected_vendor = st.selectbox("Vendor", vendors_list)
    with line_col:
        lines_list = ['全部', 'L1']
        selected_line = st.selectbox("Line", lines_list)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # ── 加载数据 ────────────────────────────────────
    with st.spinner("分析不良数据中..."):
        all_defects = load_overall_defects(top_n=50, regression=regression_mode)
        date_defects = load_date_defects(start_str, end_str, top_n=50, regression=regression_mode)

    if not date_defects:
        st.info("所选日期范围内未检测到不良数据")
        return

    mode_label = "回归后" if regression_mode else "回归前"
    st.caption(f"显示模式: **{mode_label}** | Project: {selected_project} | Vendor: {selected_vendor} | Line: {selected_line}")

    st.markdown("---")

    # ── KPI 摘要行 ──────────────────────────────────
    total_date = date_defects[0]['total'] if date_defects else 0
    top1_date = date_defects[0] if date_defects else None
    top1_all = all_defects[0] if all_defects else None

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("筛选范围记录数", f"{total_date:,}")
    with c2:
        st.metric("TOP1 不良 (筛选)", f"{top1_date['fai_name']}" if top1_date else "N/A",
                  delta=f"{top1_date['ng_rate_pct']}%" if top1_date else None)
    with c3:
        st.metric("TOP1 不良 (全量)", f"{top1_all['fai_name']}" if top1_all else "N/A",
                  delta=f"{top1_all['ng_rate_pct']}%" if top1_all else None)

    st.markdown("---")

    # ── 图表区 ──────────────────────────────────────
    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader(f"📅 {start_str} ~ {end_str} TOP 20")
        _render_hbar(date_defects[:20], f"日期筛选 TOP 20 ({mode_label})")
    with col_right:
        st.subheader("📊 全量 TOP 20 (对比)")
        _render_hbar(all_defects[:20], f"全量 TOP 20 ({mode_label})", color="#1f77b4")

    st.markdown("---")

    # ── 逐日趋势 ────────────────────────────────────
    st.subheader("📈 TOP 不良逐日趋势")
    top5_names = [d['fai_name'] for d in date_defects[:5]]
    trend_data = load_daily_trend(top5_names, start_str, end_str)

    if trend_data:
        fig = go.Figure()
        colors = ['#d62728', '#ff7f0e', '#2ca02c', '#9467bd', '#8c564b']
        for i, name in enumerate(top5_names):
            col_key = f"{name}_ng"
            days = [d['production_day'] for d in trend_data]
            values = [d.get(col_key, 0) for d in trend_data]
            fig.add_trace(go.Bar(
                x=days, y=values, name=name,
                marker_color=colors[i % 5],
                hovertemplate=f'{name}<br>%{{x}}: %{{y}} NG<extra></extra>',
            ))
        fig.update_layout(
            title=f"TOP 5 不良逐日 NG 数量 ({start_str} ~ {end_str})",
            xaxis_title="日期", yaxis_title="NG 数量",
            barmode='group', height=400, hovermode='x unified',
            legend=dict(orientation='h', yanchor='bottom', y=1.02),
        )
        st.plotly_chart(fig, width="stretch")

    st.markdown("---")

    # ── FAI 钻取 — 支持查看 NG SN 明细 ──────────────
    st.subheader("🔍 FAI 不良钻取")
    fai_names = [d['fai_name'] for d in date_defects]
    selected_fai = st.selectbox("选择 FAI 查看不良明细", fai_names)

    if selected_fai:
        show_date_filter = st.checkbox("明细也按日期筛选", value=True)
        details = get_fai_defect_detail(
            fai_name=selected_fai, top_n=200,
            start_date=start_str if show_date_filter else None,
            end_date=end_str if show_date_filter else None,
        )
        if details:
            st.caption(f"{selected_fai} — {len(details)} 条不良记录")
            detail_data = [{
                "SN": d['SN'][:35] if d['SN'] else "",
                "测量值": d['measured_value'],
                "时间": d['Time'][:19] if d['Time'] else "",
                "Line": d['Line'] or "",
            } for d in details[:50]]
            st.dataframe(detail_data, width="stretch", hide_index=True)

    st.markdown("---")

    # ── NG 数据下载 ─────────────────────────────────
    st.subheader("📥 不良 SN 数据下载")
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        if st.button("下载全部 NG SN (回归后)", type="primary"):
            with st.spinner("导出中..."):
                df = get_all_ng_sns_regression(start_str, end_str)
                if len(df) > 0:
                    csv_data = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label=f"📥 下载 {len(df):,} 条 NG 记录 (CSV)",
                        data=csv_data,
                        file_name=f"NG_SN_{start_str}_{end_str}.csv",
                        mime="text/csv",
                    )
                else:
                    st.info("无 NG 记录")
    with dl_col2:
        if st.button("下载全部 NG SN (原始数据)"):
            with st.spinner("导出中..."):
                df_raw = get_all_ng_sns_regression(start_str, end_str)
                if len(df_raw) > 0:
                    xlsx_buf = BytesIO()
                    with pd.ExcelWriter(xlsx_buf, engine='openpyxl') as writer:
                        df_raw.to_excel(writer, index=False, sheet_name='NG_SN')
                    st.download_button(
                        label=f"📥 下载 {len(df_raw):,} 条 NG 记录 (XLSX)",
                        data=xlsx_buf.getvalue(),
                        file_name=f"NG_SN_{start_str}_{end_str}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    st.info("无 NG 记录")


def _render_hbar(defects: list[dict], title: str, color: str = "#d62728"):
    if not defects:
        return
    data = list(reversed(defects))
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=[d['fai_name'] for d in data],
        x=[d['ng_count'] for d in data],
        orientation='h', marker_color=color,
        text=[f"{d['ng_count']:,} ({d['ng_rate_pct']}%)" for d in data],
        textposition='auto',
        hovertemplate='%{y}<br>NG: %{x:,}<br>不良率: %{customdata}%<extra></extra>',
        customdata=[d['ng_rate_pct'] for d in data],
    ))
    fig.update_layout(
        title=title, height=max(350, len(defects) * 22),
        margin=dict(l=20, r=20, t=30, b=20),
    )
    st.plotly_chart(fig, width="stretch")
