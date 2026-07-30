# ADR-0002: 良率折线图按 Project 区分

## 状态
已确认 (grilling session, 2026-07-30)

## 决策

**图表布局**:
- 顶部 Tab 切换 (Tabs)
- 每个 Tab 对应一个 Project
- Tab 标题: Project 名 (如 `967E1`)
- 同一 Tab 内多条 Line 用不同颜色区分 (蓝/橙/绿/紫/...)
- Y 轴: 良率 (%), X 轴: 日期
- 7 日移动平均线 (沿用现有)

**预缓存**:
- 切换 Tab 时直接读缓存，零延迟
- 缓存 key: `(project_name, line, granularity, start_date, end_date)`
- 失效时机: 上传新数据时自动清空 (`st.cache_data.clear()`)

## 缓存内容
- 各 project × 各 line × 各粒度 (按日 / 按周) 的良率序列
- 最近一次缓存更新时间
