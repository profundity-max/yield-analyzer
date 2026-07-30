"""
不良分析图组件 (Plotly)
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def render_top_defects_chart(defects: list[dict], top_n: int = 20):
    """
    渲染 TOP N 不良水平柱状图

    Args:
        defects: get_top_defects() 返回的数据
        top_n: 显示前N个
    """
    if not defects:
        st.info("暂无不良数据")
        return

    data = defects[:top_n]
    # 反转顺序让最大的在顶部
    data = list(reversed(data))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=[d['fai_name'] for d in data],
        x=[d['ng_count'] for d in data],
        orientation='h',
        marker_color='#d62728',
        text=[f"{d['ng_count']:,} ({d['ng_rate_pct']}%)" for d in data],
        textposition='auto',
        hovertemplate='FAI: %{y}<br>NG数: %{x:,}<br>不良率: %{customdata}%<extra></extra>',
        customdata=[d['ng_rate_pct'] for d in data],
    ))

    fig.update_layout(
        title=f"TOP {top_n} 不良 FAI",
        xaxis_title="NG 数量",
        yaxis_title="",
        height=500,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    st.plotly_chart(fig, width="stretch")


def render_defect_distribution(defects: list[dict]):
    """
    渲染不良率分布饼图

    Args:
        defects: get_top_defects() 返回的数据
    """
    if not defects:
        return

    # 取 TOP 8 + Others
    top8 = defects[:8]
    others_ng = sum(d['ng_count'] for d in defects[8:])

    labels = [d['fai_name'] for d in top8]
    values = [d['ng_count'] for d in top8]
    if others_ng > 0:
        labels.append("其他")
        values.append(others_ng)

    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=labels, values=values,
        hole=0.4,
        textinfo='label+percent',
        hovertemplate='%{label}<br>NG: %{value:,}<extra></extra>',
    ))

    fig.update_layout(
        title="不良分布（TOP 8 + 其他）",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    st.plotly_chart(fig, width="stretch")
