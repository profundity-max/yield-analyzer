# AIM D-T 数据分析网站 V2.0.1

内网 AIM D-T 原始数据上传、后台判定、结果图表与质量追溯平台。首版包含：

- XLSX / CSV 上传后在分析中心原地展示进度和图表
- 文件内嵌 USL/LSL 优先，默认标准规格启用 `T1-T2` 到 `T1-T5`
- 按 `SN + 检测时间 + 启用点测量值` 去重，保留重复来源
- 首测、复测、最终结果、Error/NG 口径
- PPT 对应的总览 KPI、时良率、Pareto、Cell、Tester、分布和 SN 明细
- PNG 图表下载、明细 CSV、汇总 XLSX
- admin / analyst / viewer 三级权限、可视化 Spec/Mapping/类别配置和审计

## 目录

```text
aim-dt/
├── backend/   FastAPI、SQLite、DuckDB/Parquet、后台 worker
├── frontend/  React 19、TypeScript、Vite、ECharts
├── deploy/    Nginx、launchd、内部证书脚本
└── storage/   运行时数据，不提交 Git
```

## 本地开发

后端：

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
AIM_SECRET_KEY=dev-secret-key-at-least-32-characters \
AIM_COOKIE_SECURE=false \
.venv/bin/uvicorn app.main:app --reload --port 8503
```

另开终端启动 worker：

```bash
cd backend
AIM_SECRET_KEY=dev-secret-key-at-least-32-characters \
AIM_COOKIE_SECURE=false \
.venv/bin/python -m app.worker
```

前端：

```bash
cd frontend
pnpm install
pnpm dev
```

访问 `http://127.0.0.1:5173`。首次启动使用 `.env` 中的管理员账号；生产环境必须强制修改初始密码。

## 测试

```bash
cd backend && .venv/bin/pytest -q
cd frontend && pnpm test && pnpm build
```

样例数据校验结果：182 条原始记录去重为 91 个事件、90 个 SN；默认四点结果为 90 个输入、12 个最终通过、78 个最终 NG；Pareto 分别为 26、46、64、67；Avg Processing Time 为 8.99 ms。

## 生产部署

1. `cp .env.example .env`，替换密钥、管理员初始密码和绝对路径。
2. `./deploy/generate-internal-cert.sh` 生成内部证书，或替换成公司证书。
3. 将 `deploy/nginx-aim-dt.conf` 放入 Nginx `servers/` 并执行 `nginx -t && nginx -s reload`。
4. `./deploy/install-launchd.sh` 安装 API 和 worker 服务。
5. 访问 `https://quality-server.local:8502`。

生产环境必须设置 `AIM_COOKIE_SECURE=true`。原始文件、Parquet 和结果快照默认长期保留，管理员可通过接口删除批次；磁盘达到阈值时由部署监控告警。

## 核心计算口径

- 生产日：Asia/Shanghai，默认 08:00 至次日 08:00。
- 去重：同 SN、同时间、同启用点测量值视为导出重复；不同测量值保留为真实复测。
- 单元结果：第一条为 First，最后一条为 Final；First Fail 后 Final Pass 为 Retest Pass。
- Error：空值、解析错误、`-999/9999` 测量哨兵均计 Error，最终计 NG。
- Pareto：按最终失败单位计数，同一单位同一测试点最多一次。
- Cell：最终良率按末次测试 Cell 归属；明细保留每次事件归属供追责。
- 分布：四分位数使用全量数据，KDE 每组最多确定性采样 100,000 点。

## API

主要入口位于 `/api/v1`：

- `/auth/login|logout|me|change-password`
- `/batches`、`/batches/{id}/workbench`
- `/analyses`、`/analyses/{id}/rerun-with|summary|events|exports/...`
- `/specs/editor`、`/mapping-editor`、`/mappings/editor`、`/categories`
- `/admin/specs|mappings|users|audit-logs`（兼容旧接口）

完整 OpenAPI 文档在运行后访问 `/docs`。
