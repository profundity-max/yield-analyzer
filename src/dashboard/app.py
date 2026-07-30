"""
良率分析 Dashboard — Streamlit 主入口

启动: streamlit run src/dashboard/app.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

# Load global stylesheet
_css_path = Path(__file__).parent / "assets" / "styles.css"
if _css_path.exists():
    st.markdown(f"<style>{_css_path.read_text()}</style>", unsafe_allow_html=True)

st.set_page_config(
    page_title="良率分析系统",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 侧边栏导航 ────────────────────────────────────────────

st.sidebar.title("🏭 良率分析系统")

page = st.sidebar.radio(
    "导航",
    ["📊 汇总看板", "📈 良率趋势", "🔴 不良分析", "📋 规格管理", "⚙️ 任务监控"],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
st.sidebar.caption(f"项目: {PROJECT_ROOT.name}")
st.sidebar.caption("数据引擎: DuckDB + NumPy")

# ── 页面路由 ──────────────────────────────────────────────

if page == "📊 汇总看板":
    from src.dashboard.pages.summary import show
elif page == "📈 良率趋势":
    from src.dashboard.pages.yield_trend import show
elif page == "🔴 不良分析":
    from src.dashboard.pages.defect_analysis import show
elif page == "📋 规格管理":
    from src.dashboard.pages.specs import show
elif page == "⚙️ 任务监控":
    from src.dashboard.pages.tasks import show

show()
