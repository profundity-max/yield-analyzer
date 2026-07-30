"""
良率趋势图组件 (蓝调版本)
"""

import plotly.graph_objects as go
import streamlit as st

# Color palette
COLOR_PRIMARY = "#2563eb"
COLOR_PRIMARY_DARK = "#1e3a8a"
COLOR_TEXT = "#0a2540"
COLOR_TEXT_2 = "#64748b"
COLOR_TEXT_3 = "#94a3b8"
COLOR_BORDER = "#e2e8f0"
COLOR_GRID = "#f1f5f9"
COLOR_DANGER = "#dc2626"


def render_daily_yield_chart(daily_data: list[dict], title: str = "日良率趋势"):
    """日良率折线图 (蓝色主题)"""
    if not daily_data:
        st.info("暂无数据")
        return

    dates = [d['production_day'][:10] for d in daily_data]
    yields = [d['yield_pct'] for d in daily_data]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=yields,
        mode='lines+markers',
        name='日良率',
        line=dict(color=COLOR_PRIMARY, width=3),
        marker=dict(size=8, color='white', line=dict(color=COLOR_PRIMARY, width=2)),
        hovertemplate='日期: %{x}<br>良率: %{y}%<extra></extra>',
    ))

    # 7 日移动平均
    if len(yields) >= 7:
        import numpy as np
        ma = np.convolve(yields, np.ones(7)/7, mode='valid')
        fig.add_trace(go.Scatter(
            x=dates[6:], y=ma,
            mode='lines',
            name='7日移动平均',
            line=dict(color=COLOR_TEXT_3, width=2, dash='dash'),
        ))

    fig.add_hline(y=95, line_dash="dot", line_color=COLOR_DANGER,
                  annotation_text="目标 95%", annotation_position="bottom right")

    fig.update_layout(
        title="",
        xaxis_title="",
        yaxis_title="良率 (%)",
        hovermode='x unified',
        height=280,
        margin=dict(l=20, r=20, t=20, b=20),
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis=dict(showgrid=False, color=COLOR_TEXT_2),
        yaxis=dict(gridcolor=COLOR_GRID, color=COLOR_TEXT_2),
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_cfg_comparison_chart(cfg_data: list[dict]):
    """按 Line 良率对比柱状图"""
    if not cfg_data:
        return
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[d['cfg'] for d in cfg_data],
        y=[d['yield_pct'] for d in cfg_data],
        text=[f"{d['yield_pct']}%" for d in cfg_data],
        textposition='outside',
        marker=dict(color=COLOR_PRIMARY),
        hovertemplate='Line: %{x}<br>良率: %{y}%<extra></extra>',
    ))
    fig.add_hline(y=95, line_dash="dot", line_color=COLOR_DANGER)
    fig.update_layout(
        title="按 Line 良率对比",
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis=dict(color=COLOR_TEXT_2), yaxis=dict(color=COLOR_TEXT_2, gridcolor=COLOR_GRID),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_vendor_comparison_chart(vendor_data: list[dict]):
    """按 Vendor 良率对比柱状图"""
    if not vendor_data:
        st.warning("Vendor 良率数据为空")
        return

    # Debug caption
    st.caption(f"📊 Vendor 良率数据: {vendor_data}")

    fig = go.Figure()
    colors = ['#2563eb' if d['vendor'] == 'LY' else '#f59e0b' for d in vendor_data]
    fig.add_trace(go.Bar(
        x=[d['vendor'] for d in vendor_data],
        y=[float(d['yield_pct']) for d in vendor_data],
        text=[f"{d['vendor']}: {d['yield_pct']}%" for d in vendor_data],
        textposition='outside',
        textfont=dict(size=14, color=COLOR_TEXT),
        marker=dict(color=colors, line=dict(color='white', width=2)),
        hovertemplate='<b>Vendor: %{x}</b><br>良率: %{y:.2f}%<extra></extra>',
    ))

    fig.add_hline(y=95, line_dash="dot", line_color=COLOR_DANGER,
                  annotation_text="目标 95%")

    yields = [float(d['yield_pct']) for d in vendor_data]
    y_min = max(min(min(yields) - 5, 60), 0)
    y_max = max(max(yields) + 8, 100)

    fig.update_layout(
        title="",
        xaxis=dict(title="Vendor", type='category', color=COLOR_TEXT_2),
        yaxis=dict(title="良率 (%)", range=[y_min, y_max], gridcolor=COLOR_GRID, color=COLOR_TEXT_2),
        height=400,
        margin=dict(l=40, r=40, t=20, b=40),
        plot_bgcolor='white',
        paper_bgcolor='white',
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
