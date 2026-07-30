"""
卡片渲染组件 (蓝调版)

所有 ya-* 类的 HTML 渲染都集中在这里。
页面文件只调用这些函数，不直接构造 HTML。
"""

# ════════════════════════════════════════════════════════════
# KPI 卡片
# ════════════════════════════════════════════════════════════


def render_kpi(label: str, value: str, sub: str = "", accent: str = "") -> str:
    """
    渲染单个 KPI 卡片

    Args:
        label: 标签 (如 "总产量")
        value: 数值 (如 "311,833")
        sub: 副标题 (如 "SN 总数")
        accent: 强调色 - "" / "blue" / "success"
    """
    val_class = "ya-stat-value"
    if accent == "blue":
        val_class += " ya-stat-accent"
    if accent == "success":
        val_class += " ya-stat-success"
    sub_html = f'<div class="ya-stat-extra">{sub}</div>' if sub else ""
    return (
        f'<div class="ya-card">'
        f'<div class="ya-card-label">{label}</div>'
        f'<div class="{val_class}">{value}</div>'
        f"{sub_html}"
        f"</div>"
    )


# ════════════════════════════════════════════════════════════
# Hero 卡片 (深蓝渐变)
# ════════════════════════════════════════════════════════════


def render_hero(value: str, delta: str, sub: str) -> str:
    """渲染深蓝渐变 Hero 卡片"""
    return f"""<div class="ya-card ya-hero">
  <div class="ya-card-label">综合良率</div>
  <div class="ya-hero-value">{value}</div>
  <span class="ya-hero-delta">↑ {delta}</span>
  <div class="ya-hero-sub">{sub}</div>
</div>"""


# ════════════════════════════════════════════════════════════
# Vendor 对比行
# ════════════════════════════════════════════════════════════


def render_vendor_row(name: str, yield_pct: float, css_class: str = "ly") -> str:
    """渲染单条 Vendor 对比行"""
    return f"""<div class="ya-vendor-row">
  <div class="ya-vendor-name">{name}</div>
  <div class="ya-vendor-bar"><div class="ya-vendor-fill {css_class}" style="width:{yield_pct}%"></div></div>
  <div class="ya-vendor-yield">{yield_pct:.2f}%</div>
</div>"""


# ════════════════════════════════════════════════════════════
# 不良 FAI 行
# ════════════════════════════════════════════════════════════


def render_defect_row(rank: int, name: str, count: int, rate: float) -> str:
    """渲染单条 TOP 不良 FAI 行 (含进度条)"""
    bar_width = min(rate * 20, 100)
    return f"""<div class="ya-defect-row">
  <div class="ya-defect-rank">{rank}</div>
  <div class="ya-defect-name">{name}</div>
  <div class="ya-defect-bar"><div class="ya-defect-fill" style="width:{bar_width}%"></div></div>
  <div class="ya-defect-count">{count:,}</div>
  <div class="ya-defect-rate">{rate:.2f}%</div>
</div>"""
