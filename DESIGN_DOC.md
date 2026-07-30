# 良率分析系统 (yield-analyzer) — 完整代码设计逻辑说明

---

## 一、设计逻辑总览（PPT 架构图）

### 1.1 数据流向

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐
│ Excel/CSV │───→│ importer │───→│  judge   │───→│aggregator│───→│ dashboard │
│  数据文件  │    │ 导入模块  │    │ 判定引擎  │    │ 聚合分析  │    │ 可视化面板 │
└──────────┘    └─────┬────┘    └────┬─────┘    └────┬─────┘    └───────────┘
                      │              │               │
                 raw_*.parquet  judged_*.parquet  DuckDB SQL查询
                 (原始数据)      (带判定结果)       (统计分析)

                     ┌──────────┐
                     │spec_manager│  ← 规格版本管理（独立模块，被judge引用）
                     └──────────┘

┌──────────┐    ┌──────────┐
│ monitor  │    │scheduler │  ← 辅助模块：进度跟踪 + 定时任务
└──────────┘    └──────────┘
```

### 1.2 模块依赖关系图

```
                        run.py (一站式入口)
                       /    |     |    \    \
                      /     |     |     \    \
              importer  spec_mgr  judge  aggr  dashboard
                 │        │       │      │       │
                 └────────┴───────┴──────┴───────┘
                           │             │
                         db.py      config.py
                      (DuckDB单例)  (全局配置)

                 monitor ← tracker  (进度跟踪，被 judge 和 importer 引用)
                 scheduler           (定时任务，可选，dashboard 启动时可选加载)
```

### 1.3 核心设计理念

| 设计原则 | 说明 |
|---------|------|
| **存算分离** | 原始数据存 Parquet，Spec 规格存 DuckDB 表，判定结果回写 Parquet |
| **流式处理** | 全链路使用 PyArrow 流式读写 + 生成器模式，内存峰值可控（~240MB/chunk） |
| **向量化判定** | 使用 NumPy 矩阵运算对 N×M 个测量值一次性判定，速度比逐行循环快 100× |
| **断点续传** | 基于 JSON 检查点 + 原子写入，崩溃后自动恢复，不重复计算 |
| **版本化规格** | Spec 有 UUID 版本号，支持历史回溯和版本切换 |
| **单例连接** | DuckDB 全局单例，避免重复初始化和连接开销 |

---

## 二、逐行代码目的总结

> 规则：重复出现的代码模式只说明一次，相同结构归纳合并。

### 2.1 run.py — 启动入口（191行）

| 行号 | 代码 | 目的 |
|------|------|------|
| 1 | `#!/usr/bin/env python3` | 声明脚本解释器，支持直接 `./run.py` 执行 |
| 2-12 | 文档字符串 | 描述 6 种运行模式（dashboard/import/judge/report/spec/all） |
| 14-22 | `import sys, shutil, ...` | 导入标准库：进程管理、文件查找、信号处理、HTTP请求 |
| 24 | `PROJECT_ROOT = Path(__file__).parent` | 确定项目根目录（相对于 run.py 所在路径） |
| 27-40 | `_STREAMLIT_BIN` 查找逻辑 | 自动发现 streamlit 可执行文件路径，兼容 3.9-3.12 多版本 Python |
| 42-46 | `_STREAMLIT_ARGS` | 配置 streamlit 启动参数：目标app、无头模式、端口 8501 |
| 48-60 | `_NGROK_BIN` 查找逻辑 | 自动发现 ngrok 可执行文件路径，用于公网穿透 |
| 61 | `_ngrok_process = None` | 全局变量，持有 ngrok 子进程引用，用于退出时清理 |
| 64-75 | `_get_public_url()` | 调用 ngrok 本地 API (127.0.0.1:4040) 获取公网 HTTPS 地址 |
| 78-105 | `_start_ngrok(port)` | 后台启动 ngrok tunnel，轮询等待公网 URL 就绪（最多30秒） |
| 108-114 | `_stop_ngrok()` | 终止 ngrok 子进程，优雅关闭（terminate + 5 秒超时 wait） |
| 117-137 | `_run_dashboard(with_public)` | 启动 Streamlit Dashboard，可选自动开启 ngrok 公网访问，还会打印局域网 IP |
| 140-190 | `main()` 函数 | 命令行参数解析路由：无参→dashboard, import→导入, judge→判定, report→报告, all→一键全流程 |

### 2.2 src/config.py — 全局配置（53行）

| 行号 | 代码 | 目的 |
|------|------|------|
| 11 | `PROJECT_ROOT = ...` | 从 `src/config.py` 向上两级定位项目根目录 |
| 14-22 | 数据目录定义 | 声明 8 个目录路径（raw/judged/uploads/progress/exports/archive/logs） |
| 24-25 | `_dir.mkdir(...)` 循环 | 启动时自动创建所有缺失的数据目录 |
| 28-30 | DuckDB 配置 | 内存限制 4GB、8 线程、临时目录，均支持环境变量覆盖 |
| 33 | `JUDGE_CHUNK_SIZE = 25000` | 每次判定处理 25000 行（平衡内存和 IO） |
| 36 | `EXCEL_CHUNK_SIZE = 50000` | 每次 Parquet 写入 50000 行一个 row group |
| 39 | `DAY_CUTOFF_HOUR = 7` | 日切点为早 7:00（夜班数据归属当天） |
| 42 | `SPEC_INF_VALUE = 999999` | Sentinel 值，Spec 中等于此值表示该方向无限制 |
| 45-52 | `get_raw_parquet_files()` / `get_judged_parquet_files()` | 便捷函数，获取所有原始/已判定 Parquet 文件列表 |

### 2.3 src/db.py — DuckDB 连接管理（109行）

| 行号 | 代码 | 目的 |
|------|------|------|
| 16 | `DB_PATH = ...` | DuckDB 持久化文件路径（data/yield_analyzer.duckdb），保证数据不丢失 |
| 19-40 | `get_connection(read_only)` | 单例连接获取：首次调用创建连接并设置性能参数（内存/线程/临时目录/插入顺序） |
| 31-38 | `SET memory_limit/threads/temp_directory/preserve_insertion_order` | 4 条性能配置：内存上限、并行度、临时目录、关闭保序以提速 |
| 43-48 | `close_connection()` | 显式关闭连接和重置全局变量（用于重置状态） |
| 51-95 | `init_spec_tables()` | 创建 3 张持久化表（spec_versions/spec_limits/config）+ 1 个自增序列 |
| 94-108 | `query_parquet(sql, params)` | 便捷函数，封装 DuckDB 执行 SQL 和参数绑定 |

### 2.4 importer 模块 — 数据导入（4个文件）

#### csv_reader.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 16-28 | `detect_csv_encoding()` | 采样前 100KB，依次尝试 utf-8/gbk/latin-1 等编码，找到可解码的 |
| 31-43 | `detect_delimiter()` | 用 csv.Sniffer 自动识别分隔符（逗号/制表符/分号/竖线） |
| 46-67 | `read_csv_columns()` | 用 PyArrow 快速读取 CSV 表头和行数（不逐行遍历） |
| 70-113 | `read_csv_stream()` | 流式读取 CSV → 生成器模式逐行 yield，支持大数据量 |
| 116-158 | `csv_to_parquet_fast()` | 用 DuckDB 的 `read_csv` + `COPY TO parquet` 直接转格式，利用 DuckDB 的智能类型推断 |

#### excel_reader.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 14 | `METADATA_COLUMNS = {...}` | 定义 6 个不参与 FAI 匹配的元数据列 |
| 18-60 | `read_data_sheet()` | 用 openpyxl read_only 模式流式读取 Excel Data Sheet，逐行 yield，自动处理 #REF! 错误和重复列名 |
| 63-101 | `read_spec_sheet()` | 读取 Spec Sheet 中 4 列（FAI/USL/Nomial/LSL），跳过空行 |
| 104-132 | `detect_fai_columns()` | 将 Data 列名与 Spec FAI 名称做精确匹配，跳过元数据列 |

#### parquet_writer.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 37-64 | `_infer_schema()` | 列名 → PyArrow 类型推断：CFG/SN → string, Time → timestamp(ms), 其他 → float64 |
| 67-91 | `_safe_float()` | 安全浮点转换：#REF! → None/NaN，字符串→float，不可转→None |
| 94-122 | `_safe_timestamp()` | 用 `calendar.timegm` 保留 wall clock 时间，避免时区偏移问题 |
| 125-145 | `_convert_row()` | 逐行类型转换，生成 {列名: 转换值} 字典 |
| 148-167 | `_build_record_batch()` | 将字典列表构建为 PyArrow RecordBatch，列数组类型与 schema 严格一致 |
| 170-223 | `write_to_parquet()` | 主写入函数：生成器→分批构建 RecordBatch→ParquetWriter 流式写入 snappy 压缩 |

### 2.5 spec_manager 模块 — 规格管理（3个文件）

#### loader.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 15-75 | `load_spec_from_excel()` | openpyxl 读取 Spec Sheet 的 FAI/USL/Nom/LSL 四列，Sentinel 值 999999→None |
| 78-86 | `get_fai_name_list()` | 从规格列表提取纯 FAI 名称列表 |
| 89-129 | `validate_spec()` | 4 项校验：空名称、重复名、上下限矛盾、标准值越界 |

#### versioning.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 20-38 | `create_spec_version()` | INSERT 新 UUID 版本记录，默认 is_active=False（需显式激活） |
| 41-75 | `save_spec_limits()` | 先删旧数据再批量 INSERT，使用 DuckDB `executemany` + `nextval(seq)` 自增 ID |
| 78-121 | `get_active_spec()` | 查询 is_active=TRUE 的版本及其全部 limits，返回 {version_id, fai_limits} 结构 |
| 124-152 | `set_active_version()` | 原子切换：先全失活再激活目标版本 |
| 155-181 | `list_versions()` | LEFT JOIN 统计每个版本的 FAI 数量，按时间倒序 |
| 184-229 | `get_spec_at_time(timestamp)` | 时间旅行查询：找到指定时刻之前最近导入的版本 |

#### cli.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 25-28 | `spec_cli` group | Click 命令组，入口函数 |
| 31-84 | `load_command` | 命令：加载→校验→创建版本→保存→激活（5 步流水线） |
| 87-121 | `list_versions_command` | Rich 表格展示所有版本历史 |
| 124-152 | `activate_command` | 激活指定版本并显示摘要信息 |
| 155-200 | `show_command` | 显示激活版本摘要或查询特定 FAI 规格 |

### 2.6 judge 模块 — FAI 判定引擎（3个核心文件）

#### engine.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 23 | `_METADATA_COLUMNS` | 定义不参与 FAI 匹配的元数据列集合 |
| 27-92 | `get_fai_columns_from_parquet()` | 匹配 Spec FAI 名 → Parquet 列名（精确 + 模糊匹配 _T↔_Z 后缀） |
| 95-229 | `judge_batch()` | **核心判定流程**：列匹配→建限制数组→断点检查→逐 chunk 向量化判定→合并输出 |
| 232-258 | `_fuzzy_match_column()` | Spec 列名后缀变换匹配（_Z↔_T） |
| 261-290 | `_extract_fai_matrix()` | 从 RecordBatch 提取 FAI 列为 (N, num_fai) float64 矩阵 |
| 293-336 | `_build_limit_arrays()` | 将 Spec 上下限转为 NumPy 数组，处理 SPEC_INF_VALUE→±inf |
| 339-364 | `_judge_values()` | **判定核心**：`ok_mask = (values>=lower) & (values<=upper) \| isnan(values)` |
| 367-405 | `_build_output_batch()` | 扩展 RecordBatch，追加每个 FAI 的 _result 列 + overall_result + 元数据列 |
| 411-450 | `_restore_checkpoint()` | 加载检查点 JSON 并验证一致性（raw_file/spec_version/chunk_size 三项校验） |
| 454-462 | `_register_existing_chunk()` | 恢复断点已完成的 chunk 文件引用 |
| 466-483 | `_persist_checkpoint()` | 写检查点先写 .tmp 再原子 replace，防崩溃损坏 |
| 489-504 | `_write_chunk_file()` | 单 chunk RecordBatch→Table→snappy parquet 写入 |
| 508-528 | `_combine_chunk_files()` | DuckDB `COPY (SELECT * FROM read_parquet([...]))` 合并所有 chunk |

#### chunker.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 30-104 | `process_with_progress()` | 包装 judge_batch，集成 TaskTracker，进度百分比 + ETA 估算 |
| 107-118 | `_estimate_total_chunks()` | 从 Parquet 元数据读总行数→估算 chunk 总数 |

#### dedup.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 26-137 | `apply_regression_rules()` | DuckDB 窗口函数 ROW_NUMBER + MIN 实现 SN 去重 |
| 140-186 | `get_regression_summary()` | 统计去重后唯一 SN、回归数、回归率、最大出现次数 |

### 2.7 aggregator 模块 — 聚合分析（5个文件）

#### queries.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 9-17 | `SUMMARY_QUERY` | 总体良率 SQL：COUNT + CASE WHEN overall_result=0 |
| 21-38 | `DAILY_YIELD_QUERY` | 按日良率 SQL，带日切点偏移（Time - INTERVAL '7 hours'） |
| 42-58 | `WEEKLY_YIELD_QUERY` | 按周良率 SQL，DATE_TRUNC('week', ...) |
| 62-73 | `CFG_YIELD_QUERY` | 按产品型号良率 SQL |
| 77-103 | `TOP_DEFECTS_DATE_QUERY` | UNPIVOT 后统计各 FAI 的 NG 数，带日期筛选 |
| 107-129 | `DAILY_TOP_DEFECT_TREND` | TOP 不良的逐日趋势 SQL |
| 131-152 | `TOP_DEFECTS_QUERY_TEMPLATE` | 全量 TOP N（无日期筛选版） |
| 157-174 | `SN_REGRESSION_QUERY` | SN 回归良率：ROW_NUMBER 取最新+MIN 得首次时间 |
| 178-193 | `SN_MULTI_PRODUCTION_QUERY` | 找出多次投产的 SN |
| 198-217 | `SINGLE_FAI_ANALYSIS` | 单 FAI 不良明细查询 |

#### yield_calc.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 19-21 | `_render_sql()` | Jinja2 模板渲染 SQL |
| 24-26 | `_parquet_glob()` | 构建 judged parquet 文件 glob 路径 |
| 29-42 | `get_summary(cfg)` | 调用 SUMMARY_QUERY，返回总体良率字典 |
| 45-65 | `get_daily_yield()` | 调用 DAILY_YIELD_QUERY，按日统计 |
| 68-88 | `get_weekly_yield()` | 调用 WEEKLY_YIELD_QUERY，按周统计 |
| 91-98 | `get_cfg_yield()` | 调用 CFG_YIELD_QUERY，按产品分组 |
| 101-119 | `get_regression_yield()` | 调用 SN_REGRESSION_QUERY，回归后良率 |
| 122-140 | `get_multi_production_sns()` | 多次投产 SN 列表 |

#### top_defects.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 22-34 | `_get_result_columns()` | 读取 Parquet schema，提取所有 `*_result` 列 |
| 38-65 | `get_top_defects()` | 全量 TOP N 不良排名 |
| 68-104 | `get_top_defects_by_date()` | 按日期范围筛选的 TOP N |
| 107-146 | `get_daily_top_trend()` | 指定 TOP FAI 的逐日 NG 趋势 |
| 149-160 | `get_available_date_range()` | 查询数据中 MIN/MAX 日期 |
| 163-196 | `get_fai_defect_detail()` | 单 FAI 不良明细钻取 |

#### regression.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 22-46 | `get_regression_daily()` | SN 回归后按日良率 |
| 49-61 | `get_duplicate_sn_count()` | 查询有重复投产的 SN 总数 |
| 64-95 | `get_regression_summary()` | 回归摘要：总SN、重复SN、最多投产次数、重复率 |

### 2.8 dashboard 模块 — 可视化面板（7个页面文件+3个组件文件）

#### app.py — Streamlit 主入口

| 行号 | 代码 | 目的 |
|------|------|------|
| 10-12 | `sys.path.insert(0, ...)` | 将项目根目录加入 Python Path，确保 src 模块可导入 |
| 15-20 | `st.set_page_config()` | 设置页面标题"良率分析系统"、宽布局、侧边栏默认展开 |
| 27-31 | `st.sidebar.radio()` | 5 个导航标签页：汇总看板/良率趋势/不良分析/规格管理/任务监控 |
| 37-46 | 页面路由 `if/elif` | 按用户选择动态 import 对应页面模块并调用 show() |

#### 组件 (components/)

| 文件 | 函数 | 目的 |
|------|------|------|
| stat_cards.py | `render_stat_cards()` | 渲染 8 个 KPI 指标卡：良率/OK数/总数/NG率 + SN回归统计 |
| yield_chart.py | `render_daily_yield_chart()` | Plotly 折线图：日良率 + 7日移动平均 + 95%目标线 |
| yield_chart.py | `render_cfg_comparison_chart()` | Plotly 柱状图：按产品型号良率对比 |
| defect_chart.py | `render_top_defects_chart()` | Plotly 水平柱状图：TOP N 不良 FAI |
| defect_chart.py | `render_defect_distribution()` | Plotly 环形图：不良分布 TOP8+Others |

#### 页面 (pages/)

| 文件 | 核心功能 |
|------|---------|
| summary.py | 文件上传处理入口（Excel/CSV 2GB上限）→ 导入 → 判定 → KPI卡片 → 趋势图 |
| yield_trend.py | 多维度趋势：按日/按周切换、SN回归模式、7日移动平均 |
| defect_analysis.py | 日期筛选 TOP N 不良、逐日趋势堆叠柱状图、FAI 钻取明细 |
| specs.py | 规格版本查看/切换/上传，校验后激活 |
| tasks.py | 任务进度实时监控、历史任务列表、原始进度文件查看 |

### 2.9 monitor 模块 — 进度追踪（2个文件）

#### models.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 12-16 | `TaskStatus` Enum | 4 种状态：queued/running/completed/failed |
| 19-25 | `TaskType` Enum | 6 种任务类型：import/spec_load/judge/rejudge/aggregate/export |
| 28-74 | `TaskInfo` 类 | 任务状态数据类，含进度/步骤/ETA/错误列表，支持 `to_dict()`/`from_dict()` 序列化 |

#### tracker.py

| 行号 | 代码 | 目的 |
|------|------|------|
| 17-104 | `TaskTracker` 类 | 基于 JSON 文件的任务进度跟踪器，进程独立 |
| 25-28 | `start_task()` | 创建任务并写入 running 状态 JSON 文件 |
| 30-50 | `update_progress()` | 更新已完成步骤数→计算百分比→估计剩余时间 |
| 52-65 | `complete_task()` | 标记完成，记录结果 |
| 67-76 | `fail_task()` | 标记失败，记录错误原因 |
| 106-112 | `get_tracker()` | 全局单例工厂函数 |

### 2.10 scheduler 模块 — 定时任务（2个文件）

| 文件 | 核心功能 |
|------|---------|
| jobs.py | APScheduler 封装：启动/停止调度器、添加每日导入任务和每周校验任务 |
| runner.py | 在 Dashboard 启动时调用 `init_default_jobs()` 初始化默认定时任务 |

### 2.11 .streamlit/config.toml — Streamlit 配置

| 行号 | 配置项 | 目的 |
|------|--------|------|
| 3 | `maxUploadSize = 2048` | 上传限制 2GB（默认 200MB 不够用） |
| 6 | `maxMessageSize = 2048` | WebSocket 消息体 2GB |
| 9 | `headless = true` | 无头模式不自动弹浏览器 |
| 13 | `gatherUsageStats = false` | 关闭遥测 |
| 16-18 | `[theme]` | 主题色 #1f77b4 蓝、白底、浅灰背景 |

### 2.12 requirements.txt — 依赖声明

| 依赖 | 版本要求 | 目的 |
|------|---------|------|
| `duckdb` | >=1.1.0 | 嵌入式 OLAP 数据库，替代 SQLite/Pandas 做聚合分析 |
| `pyarrow` | >=14.0.0 | 列式存储读写 Parquet，流式处理 |
| `numpy` | >=1.24.0 | 向量化判定运算 |
| `openpyxl` | >=3.1.0 | Excel 流式读取 |
| `streamlit` | >=1.28.0 | Web Dashboard 框架 |
| `plotly` | >=5.17.0 | 交互式图表 |
| `apscheduler` | >=3.10.0 | 定时任务调度 |
| `click` | >=8.1.0 | CLI 命令行框架 |
| `rich` | >=13.0.0 | 终端美化输出 |
| `pydantic` | >=2.0.0 | 数据校验（预留） |
| `jinja2` | >=3.1.0 | SQL 模板渲染 |

---

## 三、使用说明

### 3.1 环境安装

```bash
# 1. 确保 Python 3.10+
python3 --version

# 2. 安装依赖
cd yield-analyzer
pip install -r requirements.txt

# 3. (可选) 安装 ngrok 用于公网访问
brew install ngrok
ngrok config add-authtoken <你的token>
```

### 3.2 三种使用模式

#### 模式 A：一站式启动（推荐）

```bash
# 本地 Dashboard
python run.py

# 公网 Dashboard（自动 ngrok 穿透）
python run.py --public
```

#### 模式 B：命令行分步执行

```bash
# 1. 导入 Spec 规格
python run.py spec      # 交互式导入

# 2. 导入 Excel/CSV 数据
python run.py import    # 交互式导入

# 3. 执行 FAI 判定
python run.py judge

# 4. 生成报告
python run.py report

# 5. 启动 Dashboard 查看
python run.py
```

#### 模式 C：一键全流程

```bash
python run.py all       # 导入 → 判定 → 报告 → Dashboard
```

### 3.3 Web Dashboard 使用流程

1. 打开 `http://localhost:8501`
2. 首次使用：进入「📋 规格管理」→ 上传 Spec Excel（需含 FAI/USL/Nomial/LSL 四列）
3. 进入「📊 汇总看板」→ 上传 Data Excel（需含 Data sheet）或 CSV
4. 系统自动完成导入、判定、分析
5. 在「📈 良率趋势」「🔴 不良分析」页面查看详细分析
6. 「⚙️ 任务监控」查看处理进度

### 3.4 支持的数据格式

| 格式 | 要求 | 适用场景 |
|------|------|---------|
| Excel .xlsx | 需含 `Data` sheet（测量数据），可选 `Spec` sheet | 常规数据（<500MB） |
| CSV .csv | 自动检测编码和分隔符 | 大数据（>500MB），DuckDB 直接转 Parquet |

---

## 四、运行环境要求与原因分析

### 4.1 核心环境需求

| 环境 | 最低版本 | 为什么需要 |
|------|---------|-----------|
| **Python** | 3.10+ | `from __future__ import annotations` 和 `str \| None` 类型语法需 3.10+ |
| **macOS/Linux** | — | ngrok 和 subprocess 信号处理依赖 POSIX；Windows 需替代方案 |
| **内存** | 建议 8GB+ | 大数据判定时单个 chunk 峰值 ~240MB（5万行×600列×8字节），加上 DuckDB 内存池 |
| **磁盘** | 建议 10GB+ | Parquet 文件 + DuckDB 持久化文件 + 临时目录 |

### 4.2 每个依赖的选型理由

| 依赖 | 为什么选它而非替代品 |
|------|---------------------|
| **DuckDB** | vs SQLite: 原生支持 Parquet 直接查询、列式存储、窗口函数更强；vs Pandas: 无需全量加载到内存 |
| **PyArrow** | vs Pandas: 流式读写，不强制全量加载；Parquet row group 级别精细控制 |
| **NumPy** | vs 纯 Python 循环: 向量化判定速度提升 100 倍以上，一次处理 25000×600 矩阵 |
| **Streamlit** | vs Flask/FastAPI: 纯 Python 无前端代码，内置图表和数据表格，适合数据分析场景 |
| **Plotly** | vs Matplotlib: 交互式（hover/缩放/点击），与 Streamlit 深度集成 |
| **openpyxl** | vs xlrd: 支持 .xlsx 流式读取（read_only 模式），内存开销小 |
| **APScheduler** | vs Celery: 轻量级，无需 Redis/RabbitMQ 中间件 |
| **Click** | vs argparse: 装饰器风格代码更简洁，支持嵌套命令组 |
| **Rich** | vs 原生 print: 表格、颜色、进度条，终端 CLI 体验更好 |

### 4.3 为什么需要 ngrok（可选）

- Streamlit 默认只在 localhost 监听，外部设备无法访问
- ngrok 创建临时公网隧道，支持在其他设备/网络下访问 Dashboard
- 适用于：在服务器上运行、给团队演示、移动端查看

---

## 五、配置目的与设计理由

### 5.1 .streamlit/config.toml

| 配置项 | 值 | 设计理由 |
|--------|-----|---------|
| `maxUploadSize = 2048` | 2GB | 产线 Excel 数据可达 500MB-1GB，默认 200MB 远远不够 |
| `maxMessageSize = 2048` | 2GB | Streamlit WebSocket 传输大文件时需匹配上传限制 |
| `headless = true` | 无头模式 | 服务器上运行时不自动打开浏览器（也不需要 DISPLAY） |
| `gatherUsageStats = false` | 关闭遥测 | 企业内网环境，隐私考虑 |
| `primaryColor = "#1f77b4"` | 蓝色主题 | 专业工业数据分析的视觉风格 |

### 5.2 src/config.py 核心配置

| 配置项 | 默认值 | 设计理由 |
|--------|--------|---------|
| `DUCKDB_MEMORY_LIMIT` | 4GB | 平衡：太小影响查询性能，太大挤占 OS 和其他进程内存 |
| `DUCKDB_THREADS` | 8 | 充分利用多核 CPU 做并行查询 |
| `JUDGE_CHUNK_SIZE` | 25000 | 经验值：600 列×25000 行×8 字节 ≈ 120MB，两倍安全余量 |
| `EXCEL_CHUNK_SIZE` | 50000 | Parquet row group 大小：过大影响随机读取，过小增加文件数 |
| `DAY_CUTOFF_HOUR` | 7 | 早 7:00 切日：夜班 0:00-7:00 数据归属前一天 |
| `SPEC_INF_VALUE` | 999999 | Sentinel 值，远大于正常测量范围，表示无限制 |

### 5.3 为什么所有配置都支持环境变量覆盖

- 同一套代码部署到不同环境（开发机/服务器/CI）时，无需修改代码
- 通过 `os.environ.get("KEY", "default")` 模式实现 12-factor app 风格配置
- Docker/K8s 部署时只需设置环境变量即可调整参数

---

## 六、设计模块详解

### 6.1 模块总览

| 模块 | 解决的问题 | 实现代码 | 核心注意事项 |
|------|-----------|---------|-------------|
| **importer** | 将 Excel/CSV 转为高性能 Parquet 格式 | excel_reader.py, csv_reader.py, parquet_writer.py | openpyxl read_only 必须 true；时间戳用 calendar.timegm 避免时区偏移 |
| **spec_manager** | 规格版本化管理（支持切换和回溯） | loader.py, versioning.py | version_id 用 UUID；is_active 只允许一个 TRUE；新版本默认 FALSE 防半写入 |
| **judge** | 逐项判定 FAI 是否在 Spec 范围内 | engine.py, chunker.py, dedup.py | 向量化运算用 NumPy 不逐行循环；NaN/#REF! 视为 OK 不扣良率；检查点原子写入 |
| **aggregator** | 从 judged Parquet 中做聚合分析 | yield_calc.py, top_defects.py, regression.py, queries.py | SQL 模板用 Jinja2 防止拼接注入；日切点统一偏移；UNION ALL 构建 UNPIVOT |
| **dashboard** | Web 可视化面板，数据上传+分析+导出 | app.py, pages/*.py, components/*.py | 路由器用 if/elif 动态 import 按需加载；@st.cache_data 缓存 5 分钟；文件上传上限 2GB |
| **monitor** | 任务进度跟踪（跨进程可见） | tracker.py, models.py | 用 JSON 文件而非内存变量（进程独立）；get_tracker() 单例模式 |
| **scheduler** | 定时任务（每日导入、每周校验） | jobs.py, runner.py | APScheduler 后台线程；shutdown(wait=False) 避免阻塞退出 |
| **db** | DuckDB 单例连接，避免重复初始化 | db.py | _connection 全局变量 + None 检查；首次初始化配置 4 参数 |
| **config** | 全局配置集中管理，支持环境变量覆盖 | config.py | 所有目录 mkdir；所有数值参数可通过环境变量覆盖 |

### 6.2 importer — 数据导入模块

**解决的问题：**
- 产线导出的 Excel 文件结构松散（#REF! 错误值、重复列名、空列）
- 大文件（>500MB）需要流式读取，不能全量加载到内存
- CSV 文件编码和分隔符不确定
- 需要将数据转为高效列式存储（Parquet）供后续处理

**设计决策：**
1. **Excel 用 openpyxl read_only + 生成器模式**：4 万行 × 692 列只占用 ~50MB 内存
2. **CSV 大文件走 DuckDB 直转 Parquet**：利用 DuckDB 的 CSV reader 智能类型推断
3. **FAI 列自动匹配**：Spec 中有定义的 FAI 名称与 Data 列名做精确匹配，跳过元数据列
4. **时间戳保留 wall clock**：`calendar.timegm` 而非 `datetime.timestamp()`，避免本地时区偏移导致数据错乱
5. **#REF! → NaN → 判定时视为 OK**：Excel 公式错误不惩罚良率

**实现注意点：**
- `openpyxl.load_workbook(read_only=True, data_only=True)` 必须两个参数都设置
- 重复列名自动加 `_1`, `_2` 后缀
- PyArrow `write_batch` 必须在 `ParquetWriter` 上下文内调用，最后 close 写 footer

### 6.3 spec_manager — 规格管理模块

**解决的问题：**
- Spec 规格会随时间更新（工艺改进、客户要求变化）
- 历史数据需要用当时的 Spec 版本重新判定
- 多人协作时需要知道当前激活的是哪个版本

**设计决策：**
1. **UUID 版本号**：避免版本名冲突，全球唯一
2. **单版本激活**：`is_active=TRUE` 只允许一个，`set_active_version()` 先全 FALSE 再目标 TRUE
3. **新版本默认不激活**：防止半写入数据被意外使用
4. **时间旅行查询**：`get_spec_at_time(timestamp)` 支持历史数据回溯判定
5. **Sentinel 值 999999**：Spec 中用 ±999999 表示无上限/无下限

**实现注意点：**
- `executemany` 批量插入比逐条 INSERT 快 10×
- `DELETE` 旧数据再 `INSERT` 新数据支持覆盖导入
- `init_spec_tables()` 在模块 import 时自动执行，确保表存在

### 6.4 judge — FAI 判定引擎（最核心）

**解决的问题：**
- 每条 SN 记录有 ~600 个 FAI 测量项，需要逐项判断是否在 Spec 范围内
- 几十万行 × 600 列的矩阵运算，不能逐行循环
- 处理崩溃后需要能从断点继续，不重复已完成的 chunks
- Spec 列名和 Data 列名可能因为命名习惯不同而不完全一致

**设计决策：**
1. **NumPy 向量化判定**：`ok_mask = (values>=lower) & (values<=upper) | isnan(values)`，一行代码完成 N×M 矩阵判定
2. **断点续传**：JSON 检查点记录已完成 chunk 索引，验证 raw_file/spec_version/chunk_size 一致性
3. **临时 chunk 文件 + 最终合并**：每 chunk 独立 Parquet 文件，完成后 DuckDB `read_parquet([...])` 合并
4. **模糊列名匹配**：`_fuzzy_match_column()` 处理 Spec 中 `_Z` 后缀 vs Data 中 `_T` 后缀的差异
5. **NaN 容错策略**：`#REF!` → NaN → 判定为 OK，不扣良率（测量设备故障不归咎于产品）

**实现注意点：**
- `_extract_fai_matrix()` 对数值列使用 `zero_copy_only=False` 以支持含 null 的整数列
- `_persist_checkpoint()` 先写 `.tmp` 再 `replace`，原子操作防崩溃损坏
- `_safe_timestamp()` 用 `calendar.timegm` 而非 `datetime.timestamp()`，防止时区偏移
- 内存估算：25000 行 × 600 列 × 8 bytes ≈ 120MB，设置 16GB 内存机器安全

### 6.5 aggregator — 聚合分析模块

**解决的问题：**
- 从 judged Parquet 中快速计算各种统计（日良率、周良率、按CFG、TOP不良）
- 支持 SN 回归规则（同一 SN 多次出现时取最新数据）
- 支持按日期范围筛选不良分析

**设计决策：**
1. **Jinja2 SQL 模板**：所有查询集中管理在 queries.py，通过模板参数化
2. **日切点偏移**：所有时间聚合都在 SQL 层做 `Time - INTERVAL '{{cutoff_hour}} hours'`
3. **UNPIVOT 统计 TOP N**：用 UNION ALL 遍历所有 `*_result` 列，统计每个 FAI 的 NG 数
4. **DuckDB 窗口函数**：ROW_NUMBER 做 SN 去重，MIN 记录首次时间

**实现注意点：**
- `parquet_glob` 用 `union_by_name=true` 支持不同批次的列不完全一致
- UNION ALL 构建的表需在 SQL 模板里循环构造，每列一个 SELECT
- `NULLIF(count, 0)` 避免除零错误

### 6.6 dashboard — 可视化面板

**解决的问题：**
- 非技术用户需要直观查看良率趋势和不良分布
- 需要在线完成数据上传→判定→分析的完整流程
- 支持数据导出和报告生成

**设计决策：**
1. **Streamlit 纯 Python**：无需写 HTML/CSS/JS，适合数据科学家
2. **页面路由器**：`if/elif` 链按选择动态 `import` 页面模块，避免全量加载
3. **缓存 5 分钟**：`@st.cache_data(ttl=300)` 减少 DuckDB 重复查询
4. **文件上传后立即处理**：`_process_uploaded_file()` 完成导入→判定→刷新全流程
5. **Plotly 交互图表**：支持 hover 详细数据、缩放、点击钻取

**实现注意点：**
- `.streamlit/config.toml` 的 `maxUploadSize` 必须匹配实际文件大小（2GB）
- `st.cache_data.clear()` 在数据更新后必须调用，否则显示旧数据
- 页面组件文件放在 `components/` 和 `pages/` 分离关注点

### 6.7 monitor — 进度追踪

**解决的问题：**
- 长时间判定任务（几十万行）需要展示实时进度
- Dashboard 重启后进度不能丢失
- 多个任务并发时需要独立追踪

**设计决策：**
1. **JSON 文件持久化**：每个任务一个 `{task_id}.json`，进程无关
2. **ETA 估算**：基于已完成 chunks 的平均耗时推算剩余时间
3. **TaskTracker 单例**：全局一个 tracker 实例，统一管理

**实现注意点：**
- 任务完成/失败后不删除 JSON 文件，保留历史记录
- `estimated_remaining_seconds` 基于已完成 chunk 的平均速率线性估算

### 6.8 scheduler — 定时任务

**解决的问题：**
- 产线每天固定时间（如早 8:00）自动扫描新数据并导入

**设计决策：**
1. **APScheduler 后台线程**：轻量级，不需要额外中间件
2. **默认占位任务**：`_placeholder_scan` 只打日志，实际逻辑留给业务方填充

**实现注意点：**
- `shutdown(wait=False)` 避免 Dashboard 关闭时卡住
- `replace_existing=True` 重复添加同一 ID 的 job 不会冲突

---

## 七、实现注意事项总结

### 7.1 性能

| 关注点 | 做法 | 若不注意的后果 |
|--------|------|---------------|
| Excel 读取 | openpyxl `read_only=True` | 4万行×600列 全量加载 → 内存爆炸 |
| FAI 判定 | NumPy 向量化 `(N, num_fai)` 矩阵运算 | 逐行循环 → 判定耗时 ×100 |
| SQL 查询 | DuckDB 直接读 Parquet | Pandas read_parquet 全量加载 → 内存不足 |
| 批量写入 | ParquetWriter 流式 write_batch | 等全部数据才写 → 内存峰值翻倍 |

### 7.2 数据正确性

| 关注点 | 做法 | 若不注意的后果 |
|--------|------|---------------|
| 时间戳 | `calendar.timegm` 保留 wall clock | `datetime.timestamp()` 带时区 → 跨时区数据错乱 |
| Excel 错误值 | `#REF!` → None → NaN | 错误值被当作字符串比较 → 判定异常 |
| Spec 无穷值 | `±999999` → `±inf` | Sentinel 值被当作真实限制 → All NG |
| 除零保护 | `NULLIF(count, 0)` | 空数据查询 → Division by zero error |

### 7.3 健壮性

| 关注点 | 做法 | 若不注意的后果 |
|--------|------|---------------|
| 检查点写入 | 先写 `.tmp` 再 `replace` 原子操作 | 写入中途崩溃 → 检查点损坏 → 断点丢失 |
| 新版本激活 | 默认 `is_active=FALSE` | 半写入数据被误用 → 判定结果错误 |
| 列名不匹配 | 精确匹配 + 模糊匹配 `_T↔_Z` | Spec 和 Data 列名不一致 → 全部 unmatch → 无法判定 |

### 7.4 可维护性

| 关注点 | 做法 | 若不注意的后果 |
|--------|------|---------------|
| 配置集中 | config.py + 环境变量覆盖 | 硬编码散落各处 → 换环境需改多处代码 |
| SQL 集中 | queries.py Jinja2 模板 | SQL 散落各文件 → 修改时四处查找 |
| 单例连接 | db.py `get_connection()` | 多处创建连接 → 重复初始化 + 锁竞争 |
| 模块解耦 | 每个模块独立 package + `__init__.py` 导出 | 循环导入 → 启动失败 |

---

## 八、Skill 使用建议

本项目的设计逻辑说明方法论已固化为 Claude Code Skill：**`code-design-doc`**

以后对任何代码项目，使用以下命令即可按相同模板生成完整设计文档：

```
/code-design-doc
```

Skill 会自动：
1. 扫描项目全部源码
2. 生成设计逻辑 PPT 文档（Markdown格式）
3. 逐行总结代码目的
4. 生成使用说明书
5. 分析运行环境要求和选型理由
6. 解析配置项的设计意图
7. 梳理模块架构和设计决策
8. 列出实现注意事项（性能/正确性/健壮性/可维护性四个维度）

---

*文档生成时间：2026-07-23*
*项目：yield-analyzer 良率分析系统*
