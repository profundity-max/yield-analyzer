"""
任务监控页面 — 实时进度 + 历史任务 + 手动触发
"""

import json
import streamlit as st

from src.config import PROGRESS_DIR
from src.monitor.tracker import get_tracker


def show():
    st.title("⚙️ 任务监控")

    tracker = get_tracker()

    # ── 运行中任务 ──────────────────────────────────
    st.subheader("🔄 运行中任务")
    running = tracker.list_running_tasks()

    if running:
        for task in running:
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{task.task_type.value}**: `{task.task_id}`")
                    st.progress(task.percentage / 100)
                    st.caption(task.current_step)
                with col2:
                    st.metric("进度", f"{task.percentage}%")
                    if task.estimated_remaining_seconds:
                        mins = task.estimated_remaining_seconds // 60
                        secs = task.estimated_remaining_seconds % 60
                        st.caption(f"预计剩余: {mins}分{secs}秒")
                st.markdown("---")
    else:
        st.info("当前无运行中的任务")

    # ── 刷新按钮 ────────────────────────────────────
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🔄 刷新状态"):
            st.rerun()

    # ── 任务历史 ────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 任务历史")
    all_tasks = tracker.list_tasks()

    if all_tasks:
        task_data = []
        for t in reversed(all_tasks):  # 最新在前
            status_icon = {
                "completed": "✅", "failed": "❌",
                "running": "🔄", "queued": "⏳"
            }.get(t.status.value if hasattr(t.status, 'value') else str(t.status), "❓")

            task_data.append({
                "任务ID": t.task_id[:20] + "...",
                "类型": t.task_type.value if hasattr(t.task_type, 'value') else str(t.task_type),
                "状态": f"{status_icon} {t.status.value if hasattr(t.status, 'value') else t.status}",
                "开始时间": t.started_at.strftime("%m-%d %H:%M") if t.started_at else "N/A",
                "进度": f"{t.percentage:.0f}%",
                "错误": "; ".join(t.errors[:2]) if t.errors else "",
            })

        st.dataframe(task_data, width="stretch", hide_index=True)
    else:
        st.info("暂无任务记录")

    # ── 进度文件 ────────────────────────────────────
    st.markdown("---")
    with st.expander("📁 查看原始进度文件"):
        progress_files = sorted(PROGRESS_DIR.glob("*.json"), reverse=True)
        if progress_files:
            for pf in progress_files[:10]:
                st.caption(f"**{pf.name}**")
                try:
                    with open(pf, "r") as f:
                        content = json.load(f)
                    st.json(content)
                except Exception:
                    st.caption("读取失败")
        else:
            st.caption("暂无进度文件")
