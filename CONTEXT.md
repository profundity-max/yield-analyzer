# yield-analyzer 领域词汇表

> 由 grill-with-docs 流程维护。术语、ADR 与代码同步。

## 核心概念

| 术语 | 含义 | 备注 |
|------|------|------|
| **SN** | Serial Number，序列号 | 数据主键之一 |
| **Time** | 测量时间 | 数据主键之一 |
| **FAI** | First Article Inspection，首件检测项 | 数据核心列 |
| **NG** | No Good，不良 | FAI 单项或整条 SN 判定为不良 |
| **CFG** (旧) → **Line** (新) | 产线代号 | 当前数据全部为 `L1` |
| **Yield1** (旧) → **Project** (新) | 项目代号 | 旧数据全空，填充默认值 `967E1` |
| **Yield2** (旧) → **Vendor** (新) | 供应商代号 | 旧数据全空，填充默认值 `LY` |
| **回归 (regression)** | 同一 SN 多次投产时取最新一次 | 去重规则 |
| **整形 (rectification)** | NG 物理修复挽回 | 详见 ADR-0001 |

## 旧 → 新 字段映射（待评审）

| 旧名 | 新名 | 缺值填充 | 备注 |
|------|------|----------|------|
| Yield1 | Project | `967E1` | NULL → 967E1 |
| Yield2 | Vendor | `LY` | NULL → LY |
| CFG | Line | 不变 | `L1` 保持 |

## 架构组件

| 模块 | 职责 |
|------|------|
| `importer` | Excel/CSV → Parquet，含列名标准化 |
| `judge` | FAI 测量 → 判定 OK/NG |
| `aggregator` | DuckDB SQL 聚合：日/周良率、TOP 不良、回归 |
| `dashboard` | Streamlit 5 页可视化 + 下载 |
| `spec_manager` | Spec 版本管理 (DuckDB 表) |
| `monitor` | 任务进度跟踪 |
| `scheduler` | 定时任务 (预留) |

## 数据流

```
Excel/CSV → importer (raw parquet)
         → judge → judged parquet
         → DuckDB SQL 聚合
         → dashboard / exporter
```

## 整形白名单 (ADR-0001)

- FAI312, FAI313, FAI314, FAI315, FAI316, FAI317, FAI318, FAI319
- FAI320, FAI321, FAI322, FAI323, FAI324, FAI325, FAI326, FAI327
- FAI344, FAI346, FAI347, FAI348

匹配规则: 列名需与白名单相同（基础名），允许带 `_T`/`_Z` 等后缀变体。
