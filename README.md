# Yield Analyzer 🏭

制造业良率分析系统 — 基于 Streamlit + DuckDB 的 FAI 良率监控平台

## 核心功能

- **📊 良率趋势分析** — 按 Project / Line / Vendor 分组的日良率折线图
- **🔄 SN 回归** — 同一 SN 取首次时间 + 末次测量，自动重新分配良率归属日
- **🔧 整形预估** — 基于 FAI 白名单预估可挽救的 NG 产品（86% 挽回率）
- **📈 不良分析** — TOP N 不良 FAI 钻取 + NG SN 下载
- **📥 报表下载** — 每日良率日报 (Excel/CSV)，支持 Project/Line 筛选
- **🌐 局域网部署** — Nginx + Cookie 认证，局域网同事可访问

## 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | Streamlit |
| 数据库 | DuckDB (in-process OLAP) |
| 数据存储 | Parquet |
| 图表 | Plotly |
| 部署 | launchd + Nginx + aiohttp (auth) |
| Python | 3.14 |

## 快速开始

```bash
# 1. 安装依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 启动 Dashboard
streamlit run src/dashboard/app.py

# 3. 访问
open http://127.0.0.1:8501
```

## 目录结构

```
yield-analyzer/
├── src/
│   ├── aggregator/      # 良率计算 / 不良分析 / 报表导出
│   ├── dashboard/       # Streamlit UI
│   │   ├── pages/       # 5 个页面 (汇总/趋势/不良/规格/任务)
│   │   ├── components/  # 可复用 UI 组件
│   │   └── assets/      # CSS 设计系统
│   ├── importer/        # Excel → Parquet
│   ├── judge/           # FAI 判定引擎
│   ├── monitor/         # 任务监控
│   ├── scheduler/       # 定时任务
│   └── spec_manager/    # 规格版本管理
├── tests/               # 26 个单元测试
├── docs/adr/            # 架构决策记录
├── data/                # 数据目录 (gitignored)
├── auth_subhandler.py   # Nginx 认证子服务
└── requirements.txt
```

## 核心算法

### SN 回归 (ADR-0001)
同一 SN 多次投产时，取首次投产时间 + 末次测量结果。
- **回归前**：直接读 Parquet，未去重
- **回归后**：`ROW_NUMBER() OVER (PARTITION BY SN ORDER BY Time DESC) AS rn` + `MIN(Time) OVER (PARTITION BY SN) AS first_prod_time` + `REPLACE(first_prod_time AS "Time")`

### 整形预估
如果一条 SN 的所有 NG FAI 都在白名单（FAI312-348）内，视为可整形。预计挽回 = rectifiable_count × 86%。

## 测试

```bash
pytest tests/ -v
```

当前: **26 passed in 0.4s** ✅

## 部署

详见 `docs/adr/` 中的架构决策记录。

## License

Internal use only.
