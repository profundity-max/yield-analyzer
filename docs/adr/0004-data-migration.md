# ADR-0004: 已有数据列名迁移

## 状态
已确认 (grilling session, 2026-07-30)

## 决策

**一次性脚本** (新增 `scripts/migrate_columns.py`):
- 遍历 `data/judged/*.parquet` 和 `data/raw/*.parquet`
- 字段重命名:
  - `Yield1` → `Project`
  - `Yield2` → `Vendor`
  - `CFG` → `Line`
- NULL 填充:
  - `Project` NULL → `967E1`
  - `Vendor` NULL → `LY`
  - `Line` 不动
- 写回原文件，**原始版本备份到 archive**
- 处理顺序: raw → judged（先迁移原始数据，再让 SQL 读出与之一致）
- 幂等性: 重复运行不破坏（如果列名已经是新名则跳过）

## 新上传兼容
- `COLUMN_ALIASES` 加入新别名:
  - `Project` ← ["Project", "Yield1", "项目", "项目代号"]
  - `Vendor`  ← ["Vendor", "Yield2", "供应商"]
  - `Line`    ← ["Line", "CFG", "线体", "产线"]
