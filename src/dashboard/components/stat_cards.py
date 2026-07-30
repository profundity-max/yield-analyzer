"""
KPI 指标卡组件
"""

import streamlit as st


def render_stat_cards(summary: dict, reg_summary: dict = None):
    """
    渲染一行 KPI 指标卡

    Args:
        summary: get_summary() 返回的字典 {total, ok_count, ng_count, yield_pct}
        reg_summary: get_regression_summary() 返回的字典
    """
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="总体良率",
            value=f"{summary['yield_pct']}%",
            delta=None,
        )
    with col2:
        st.metric(
            label="OK 数量",
            value=f"{summary['ok_count']:,}",
        )
    with col3:
        st.metric(
            label="总记录数",
            value=f"{summary['total']:,}",
        )
    with col4:
        ng_rate = round(summary['ng_count'] / summary['total'] * 100, 2) if summary['total'] > 0 else 0
        st.metric(
            label="NG 数量 / 不良率",
            value=f"{summary['ng_count']:,}",
            delta=f"{ng_rate}% 不良率",
        )

    if reg_summary:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(label="活跃 SN", value=f"{reg_summary['total_sn']:,}")
        with col2:
            st.metric(label="重复投产 SN", value=f"{reg_summary['duplicate_sn']:,}")
        with col3:
            st.metric(label="重复率", value=f"{reg_summary['duplicate_rate_pct']}%")
        with col4:
            st.metric(label="最多投产次数", value=f"{reg_summary['max_productions']}次")
