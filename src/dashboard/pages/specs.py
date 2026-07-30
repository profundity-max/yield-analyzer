"""
规格管理页面 — 查看/上传/切换 Spec 版本
"""

import os
import tempfile
import streamlit as st

from src.spec_manager.versioning import (
    list_versions, get_active_spec, set_active_version,
    create_spec_version, save_spec_limits,
)
from src.spec_manager.loader import load_spec_from_excel, validate_spec


@st.cache_data(ttl=60)
def load_versions():
    return list_versions()


def show():
    st.title("📋 规格管理 (Spec)")

    # ── 当前激活版本 ────────────────────────────────
    active = get_active_spec()
    if active['version_id']:
        st.success(f"✅ 当前激活版本: `{active['version_id'][:12]}...`")
        st.caption(f"来源: {active.get('source_file', 'N/A')}")
        st.caption(f"FAI 数量: {len(active['fai_limits'])}")

        # 显示部分规格
        with st.expander("查看规格详情（前20条）"):
            items = list(active['fai_limits'].items())[:20]
            spec_data = [
                {"FAI": k, "LSL": v['lower'], "USL": v['upper'], "NOM": v['nominal']}
                for k, v in items
            ]
            st.dataframe(spec_data, width="stretch", hide_index=True)
    else:
        st.warning("⚠️ 无激活的规格版本，请先上传 Spec 文件")

    st.markdown("---")

    # ── 版本历史 ────────────────────────────────────
    st.subheader("版本历史")
    versions = load_versions()
    if versions:
        df_data = [
            {
                "版本ID": v['version_id'][:12] + "...",
                "来源文件": os.path.basename(v['source_file'] or "N/A"),
                "导入时间": v['imported_at'],
                "状态": "✅ 激活" if v['is_active'] else "⏸ 未激活",
                "FAI数": v['limit_count'],
                "备注": v['description'] or "",
            }
            for v in versions
        ]
        st.dataframe(df_data, width="stretch", hide_index=True)

        # 切换版本
        inactive_versions = [v for v in versions if not v['is_active']]
        if inactive_versions:
            selected = st.selectbox(
                "选择要激活的历史版本",
                [v['version_id'] for v in inactive_versions],
                format_func=lambda vid: f"{vid[:12]}... ({next(v['imported_at'] for v in inactive_versions if v['version_id'] == vid)})"
            )
            if st.button("🔄 激活此版本"):
                set_active_version(selected)
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("暂无版本记录")

    st.markdown("---")

    # ── 上传新 Spec ─────────────────────────────────
    st.subheader("上传新 Spec 文件")
    uploaded_file = st.file_uploader(
        "选择 Spec Excel 文件 (.xlsx)",
        type=["xlsx"],
        help="文件需包含 Spec Sheet，其中有 FAI、USL、Nomial、LSL 四列",
    )

    if uploaded_file:
        if st.button("📤 导入并激活"):
            with st.spinner("正在解析 Spec..."):
                # 保存临时文件
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name

                try:
                    spec_data = load_spec_from_excel(tmp_path)
                    errors = validate_spec(spec_data)

                    if errors:
                        st.error(f"规格校验失败: {errors}")
                    else:
                        vid = create_spec_version(uploaded_file.name, "用户上传")
                        save_spec_limits(vid, spec_data)
                        set_active_version(vid)
                        st.cache_data.clear()
                        st.success(f"✅ 导入成功！新版本: `{vid[:12]}...` — {len(spec_data)} 条规格")
                        st.rerun()
                finally:
                    os.unlink(tmp_path)
