"""
汇总看板 — 蓝调克制版 (Apple 风格)
布局：12 列卡片网格
"""

from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from src.config import RAW_DIR
from src.dashboard.components.cards import (
    render_kpi, render_hero, render_vendor_row, render_defect_row,
)
from src.dashboard.components.data_upload import render as render_upload


# ════════════════════════════════════════════════════════════
# 数据加载
# ════════════════════════════════════════════════════════════


@st.cache_data(ttl=300)
def load_data():
    from src.aggregator.yield_calc import (
        get_summary, get_daily_yield, get_cfg_yield, get_vendor_yield,
    )
    from src.aggregator.top_defects import get_top_defects
    from src.aggregator.regression import (
        get_regression_summary, get_regression_daily, get_rectification_stats,
    )

    return {
        "summary": get_summary(),
        "daily": get_daily_yield(),
        "daily_regression": get_regression_daily(),
        "cfg": get_cfg_yield(),
        "vendor": get_vendor_yield(),
        "top10": get_top_defects(top_n=10),
        "regression": get_regression_summary(),
        "rectification": get_rectification_stats(),
    }


# ════════════════════════════════════════════════════════════
# HTML helpers
# ════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# 页面主体
# ════════════════════════════════════════════════════════════


def show():
    # ── 数据上传 ─────────────────────────────
    render_upload()
    st.title("📊 汇总看板")
    st.markdown('<div class="subtitle">2026 年 7 月 30 日 · 实时数据</div>', unsafe_allow_html=True)

    # ── 数据加载 ─────────────────────────────
    try:
        with st.spinner("加载数据中..."):
            data = load_data()
    except Exception as e:
        st.error(f"数据加载失败: {e}")
        st.info("💡 请先上传数据文件")
        return

    if data["summary"]["total"] == 0:
        st.info("📤 **暂无数据** — 请上传 Excel 数据文件开始分析")
        return

    # ── 显示模式 Toggle ───────────────────
    display_mode = st.radio(
        "显示模式",
        ["📊 回归后", "📋 回归前", "🔄 两者对比"],
        index=0, horizontal=True,
        key="summary_display_mode",
        help="回归后 = 同一SN取首次Time+末次结果",
        label_visibility="collapsed",
    )

    # ── KPI 数据源 ──────────────────────────
    if display_mode == "📊 回归后":
        reg_daily = data["daily_regression"]
        total = sum(d["total"] for d in reg_daily)
        ok = sum(d["ok_count"] for d in reg_daily)
        ng = total - ok
        yield_pct = round(ok / total * 100, 2) if total > 0 else 0
    else:
        s = data["summary"]
        total, ok, ng = s["total"], s["ok_count"], s["total"] - s["ok_count"]
        yield_pct = s["yield_pct"]

    rect = data["rectification"]
    delta_pp = rect.get("yield_pct_post", 0) - rect.get("yield_pct_pre", 0)

    st.markdown("---")

    # ── 顶部 KPI 卡片（用 container 包裹）───
    with st.container(border=True):
        col_hero, col_s1, col_s2, col_s3, col_s4 = st.columns([4, 2, 2, 2, 2])
        with col_hero:
            st.markdown(render_hero(
                f"{yield_pct:.1f}%",
                f"+{delta_pp:.1f} pp 预计整形",
                f"整形前 {rect.get('yield_pct_pre', 0):.2f}% · 整形后 {rect.get('yield_pct_post', 0):.2f}%"
            ), unsafe_allow_html=True)
        with col_s1:
            st.markdown(render_kpi("总产量", f"{total:,}", "SN 总数"), unsafe_allow_html=True)
        with col_s2:
            st.markdown(render_kpi("合格数", f"{ok:,}", "OK 判定", accent="success"), unsafe_allow_html=True)
        with col_s3:
            st.markdown(render_kpi("不良数", f"{ng:,}", "NG 判定"), unsafe_allow_html=True)
        with col_s4:
            st.markdown(render_kpi("可整形", f"{rect.get('rectifiable_count', 0):,}",
                              f"预计挽回 {rect.get('saved_count', 0):,}", accent="blue"),
                        unsafe_allow_html=True)

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── 第二行：趋势 + Vendor ─────────────
    col_trend, col_vendor = st.columns([8, 4])
    with col_trend:
        with st.container(border=True):
            st.markdown('<div class="ya-card-title">日良率趋势</div>', unsafe_allow_html=True)
            from src.dashboard.components.yield_chart import render_daily_yield_chart
            if display_mode == "📊 回归后":
                render_daily_yield_chart(data["daily_regression"], "")
            elif display_mode == "📋 回归前":
                render_daily_yield_chart(data["daily"], "")
            else:
                import plotly.graph_objects as go
                fig = go.Figure()
                d_pre = [d["production_day"][:10] for d in data["daily"]]
                y_pre = [d["yield_pct"] for d in data["daily"]]
                fig.add_trace(go.Scatter(x=d_pre, y=y_pre, mode='lines+markers',
                    name='回归前', line=dict(color='#94a3b8', width=2, dash='dash')))
                d_post = [d["production_day"][:10] for d in data["daily_regression"]]
                y_post = [d["yield_pct"] for d in data["daily_regression"]]
                fig.add_trace(go.Scatter(x=d_post, y=y_post, mode='lines+markers',
                    name='回归后', line=dict(color='#2563eb', width=3),
                    marker=dict(size=8, color='white', line=dict(color='#2563eb', width=2))))
                fig.add_hline(y=95, line_dash="dot", line_color="#dc2626",
                              annotation_text="目标 95%", annotation_position="bottom right")
                fig.update_layout(
                    title="", height=280, margin=dict(l=20, r=20, t=20, b=20),
                    plot_bgcolor='white', paper_bgcolor='white',
                    xaxis=dict(showgrid=False, color='#64748b'),
                    yaxis=dict(gridcolor='#f1f5f9', color='#64748b', title="良率 (%)"),
                    hovermode='x unified', showlegend=True,
                    legend=dict(orientation='h', yanchor='bottom', y=1.02)
                )
                st.plotly_chart(fig, use_container_width=True)

    with col_vendor:
        with st.container(border=True):
            st.markdown('<div class="ya-card-title">按 Vendor 良率</div>', unsafe_allow_html=True)
            if data["vendor"]:
                for v in data["vendor"]:
                    css_class = "ly" if v["vendor"] == "LY" else "lk"
                    st.markdown(render_vendor_row(v["vendor"], v["yield_pct"], css_class),
                                unsafe_allow_html=True)
                st.markdown(f'<div class="ya-stat-extra" style="margin-top:8px">共 {len(data["vendor"])} 个 Vendor</div>',
                            unsafe_allow_html=True)
            else:
                st.info("无 Vendor 数据")

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── 第三行：TOP 不良 + 整形预估 ───────
    col_defect, col_rect = st.columns([5, 7])
    with col_defect:
        with st.container(border=True):
            st.markdown('<div class="ya-card-title">TOP 5 不良 FAI</div>', unsafe_allow_html=True)
            if data["top10"]:
                for i, d in enumerate(data["top10"][:5], 1):
                    st.markdown(render_defect_row(i, d["fai_name"], d["ng_count"], float(d["ng_rate_pct"])),
                                unsafe_allow_html=True)

    with col_rect:
        with st.container(border=True):
            st.markdown('<div class="ya-card-title">预计整形后良率</div>', unsafe_allow_html=True)
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                st.markdown(render_kpi("原始良率", f"{rect.get('yield_pct_pre', 0):.2f}%"),
                            unsafe_allow_html=True)
            with rc2:
                st.markdown(render_kpi("预计提升", f"+{delta_pp:.2f} pp", accent="blue"),
                            unsafe_allow_html=True)
            with rc3:
                st.markdown(render_kpi("预计良率", f"{rect.get('yield_pct_post', 0):.2f}%", accent="success"),
                            unsafe_allow_html=True)
            st.markdown(f'<div class="ya-stat-extra" style="margin-top:12px">可整形 SN {rect.get("rectifiable_count", 0):,} 条 · 86% 预计挽回</div>',
                        unsafe_allow_html=True)

    st.markdown("---")

    # ── 报表下载区 ────────────────────────
    with st.container(border=True):
        st.markdown('<div class="ya-card-title">📥 报表下载</div>', unsafe_allow_html=True)

        from src.aggregator.exporter import get_report_bytes_pre, get_report_bytes_post
        from src.aggregator.regression import get_daily_rectification_yield
        from src.aggregator.top_defects import get_top_defects_regression

        @st.cache_data(ttl=300, show_spinner="生成回归前日报...")
        def _cached_pre() -> bytes:
            return get_report_bytes_pre(top_n=10)

        @st.cache_data(ttl=300, show_spinner="生成回归后日报...")
        def _cached_post() -> bytes:
            return get_report_bytes_post(top_n=10)

        @st.cache_data(ttl=300, show_spinner="生成每日不良率...")
        def _cached_daily_csv() -> bytes:
            rows = get_daily_rectification_yield()
            if not rows:
                return b""
            return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")

        @st.cache_data(ttl=300, show_spinner="生成 TOP 不良...")
        def _cached_top_csv() -> bytes:
            rows = get_top_defects_regression(top_n=20)
            if not rows:
                return b""
            return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")

        dl1, dl2 = st.columns(2)
        with dl1:
            st.markdown('<div class="ya-stat-extra" style="margin-bottom:8px;font-weight:500;color:var(--c-navy)">每日良率日报</div>', unsafe_allow_html=True)
            sc1, sc2 = st.columns(2)
            with sc1:
                try:
                    st.download_button("📥 回归前日报", _cached_pre(),
                                       file_name=f"daily_pre_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       use_container_width=True)
                except Exception as e:
                    st.error(f"生成失败: {e}")
            with sc2:
                try:
                    st.download_button("📥 回归后日报 (含整形)", _cached_post(),
                                       file_name=f"daily_post_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       use_container_width=True)
                except Exception as e:
                    st.error(f"生成失败: {e}")
        with dl2:
            st.markdown('<div class="ya-stat-extra" style="margin-bottom:8px;font-weight:500;color:var(--c-navy)">不良率数据 (CSV)</div>', unsafe_allow_html=True)
            sc3, sc4 = st.columns(2)
            with sc3:
                try:
                    csv1 = _cached_daily_csv()
                    if csv1:
                        st.download_button("📥 每日回归后不良率", csv1,
                                           file_name=f"daily_defect_{datetime.now().strftime('%Y%m%d')}.csv",
                                           mime="text/csv", use_container_width=True)
                    else:
                        st.info("无数据")
                except Exception as e:
                    st.error(f"生成失败: {e}")
            with sc4:
                try:
                    csv2 = _cached_top_csv()
                    if csv2:
                        st.download_button("📥 TOP 不良 FAI", csv2,
                                           file_name=f"top_defects_{datetime.now().strftime('%Y%m%d')}.csv",
                                           mime="text/csv", use_container_width=True)
                    else:
                        st.info("无数据")
                except Exception as e:
                    st.error(f"生成失败: {e}")

    if st.button("🔄 刷新数据", help="清除缓存并重新加载", type="secondary"):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"Last updated {datetime.now().strftime('%Y/%m/%d %H:%M')} · DuckDB")
