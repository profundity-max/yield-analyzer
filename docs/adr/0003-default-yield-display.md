# ADR-0003: 默认良率显示模式

## 状态
已确认 (grilling session, 2026-07-30)

## 决策

**Dashboard 顶部加 toggle (3 选 1)**:
- `📊 回归后` (默认)
- `📋 普通`
- `🔄 两者对比`

**影响范围** (所有显示良率的地方都遵守此 toggle):
- 顶部 KPI 卡片 (核心指标)
- 良率趋势图 (yield_trend.py)
- TOP 不良分析 (defect_analysis.py)
- 按 Line / Project 分组

**两者对比的具体呈现**:
- 推荐: **同一张图** 上画两条线 (回归=实线, 普通=虚线), Y 轴 0-100% 共享
- 让用户**一眼看出**回归去重前后差异

**数据库层**:
- `get_summary()` / `get_daily_yield()` → 普通
- `get_regression_summary()` / `get_regression_yield()` → 回归
- dashboard 按 toggle 调对应函数

## 两者对比模式 (Q6 补充)

**实现**: 同一张图叠加两条线
- 回归后良率: 实线 (粗, 主色)
- 普通良率: 虚线 (细, 灰色)
- 共享 Y 轴 0-100%
- 图例标注清楚
