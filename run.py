#!/usr/bin/env python3
"""
良率分析工具 — 一站式启动脚本

用法:
  python run.py                    # 本地启动 Dashboard
  python run.py --public           # 启动 Dashboard + 开启公网访问
  python run.py import             # 导入 Excel 数据
  python run.py judge              # 执行 FAI 判定
  python run.py report             # 生成分析报告
  python run.py clean-data         # 剔除脏数据 (默认 dry-run，加 --apply 才执行)
  python run.py all                # 一键执行：导入 → 判定 → 报告
"""

from __future__ import annotations

import sys
import shutil
import subprocess
import time
import signal
import atexit
import json
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# ── 查找 streamlit ─────────────────────────────────────
_STREAMLIT_BIN = shutil.which("streamlit")
if _STREAMLIT_BIN is None:
    _candidates = [
        Path.home() / "Library/Python/3.9/bin/streamlit",
        Path.home() / "Library/Python/3.10/bin/streamlit",
        Path.home() / "Library/Python/3.11/bin/streamlit",
        Path.home() / "Library/Python/3.12/bin/streamlit",
    ]
    for _c in _candidates:
        if _c.exists():
            _STREAMLIT_BIN = str(_c)
            break
if _STREAMLIT_BIN is None:
    _STREAMLIT_BIN = "streamlit"

_STREAMLIT_ARGS = [
    _STREAMLIT_BIN, "run", "src/dashboard/app.py",
    "--server.headless", "true",
    "--server.port", "8501",
]

# ── 查找 ngrok ─────────────────────────────────────────
_NGROK_BIN = shutil.which("ngrok")
if _NGROK_BIN is None:
    _candidates = [
        Path.home() / ".local/bin/ngrok",
        Path("/usr/local/bin/ngrok"),
        Path("/opt/homebrew/bin/ngrok"),
    ]
    for _c in _candidates:
        if _c.exists():
            _NGROK_BIN = str(_c)
            break

_ngrok_process = None


def _get_public_url() -> str | None:
    """从 ngrok API 获取公网 URL"""
    try:
        req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            for tunnel in data.get("tunnels", []):
                if tunnel.get("proto") == "https":
                    return tunnel["public_url"]
    except Exception:
        pass
    return None


def _start_ngrok(port: int = 8501):
    """后台启动 ngrok tunnel"""
    global _ngrok_process
    if _NGROK_BIN is None:
        print("⚠️ 未找到 ngrok，跳过公网访问")
        print("   安装: brew install ngrok")
        print("   配置: ngrok config add-authtoken <你的token>")
        return

    print(f"🌐 启动 ngrok (端口 {port})...")
    _ngrok_process = subprocess.Popen(
        [_NGROK_BIN, "http", str(port), "--log=stdout"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 等待 ngrok 就绪
    for i in range(30):
        time.sleep(1)
        url = _get_public_url()
        if url:
            print(f"\n{'='*60}")
            print(f"  🌐 公网访问地址（任意网络可用）:")
            print(f"  {url}")
            print(f"{'='*60}\n")
            break
    else:
        print("⚠️ ngrok 启动超时，请检查网络或 ngrok 配置")


def _stop_ngrok():
    """关闭 ngrok"""
    global _ngrok_process
    if _ngrok_process:
        _ngrok_process.terminate()
        _ngrok_process.wait(timeout=5)
        print("🔒 ngrok 已关闭")


def _run_dashboard(with_public: bool = False):
    """启动 Streamlit Dashboard"""
    if with_public:
        _start_ngrok()
        atexit.register(_stop_ngrok)

    print(f"[启动] Streamlit Dashboard")
    print(f"  本地: http://localhost:8501")

    # 尝试获取局域网 IP
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print(f"  局域网: http://{local_ip}:8501")
    except Exception:
        pass

    subprocess.run(_STREAMLIT_ARGS, cwd=PROJECT_ROOT)


def main():
    args = sys.argv[1:]

    # 检查 --public 参数
    with_public = "--public" in args
    if with_public:
        args.remove("--public")

    if not args or args[0] in ("dashboard", "web", "app"):
        _run_dashboard(with_public=with_public)
    elif args[0] == "import":
        print("[导入] 数据导入模块")
        from src.importer.cli import main as importer_main
        importer_main()
    elif args[0] == "spec":
        print("[规格] 规格管理模块")
        from src.spec_manager.cli import main as spec_main
        spec_main()
    elif args[0] == "judge":
        print("[判定] FAI 判定引擎")
        from src.judge.cli import main as judge_main
        judge_main()
    elif args[0] == "report":
        print("[分析] 聚合分析模块")
        from src.aggregator.cli import main as aggr_main
        aggr_main()
    elif args[0] == "clean-data":
        print("[清洗] 剔除缺失 Vendor/Project/Line 的脏数据")
        from src.importer.data_cleaner import clean_glob, aggregate
        from src.config import RAW_DIR, JUDGED_DIR

        dry_run = "--apply" not in args
        if dry_run:
            print("→ 预览模式 (dry-run)，加 --apply 才会真正写入\n")
        else:
            args.remove("--apply")
            print("→ 执行模式: 将原子替换原 parquet 文件\n")

        for label, pattern in (("raw", str(RAW_DIR / "raw_*.parquet")), ("judged", str(JUDGED_DIR / "judged_*.parquet"))):
            print(f"=== {label}: {pattern} ===")
            results = clean_glob(pattern, dry_run=dry_run)
            if not results:
                print("  (无文件)\n")
                continue
            for r in results:
                flag = "DRY" if r["dry_run"] else "OK"
                print(f"  [{flag}] {Path(r["path"]).name}: rows={r["total_rows"]:,}  invalid={r["removed"]:,}  remaining={r["remaining"]:,}")
            agg = aggregate(results)
            print(f"  ── 汇总: 文件={agg["file_count"]} 总行={agg["total_rows"]:,} 剔除={agg["removed"]:,} 剩余={agg["remaining"]:,}")
            print(f"     各列缺失行数: Vendor={agg["per_column"]["Vendor"]:,}  Project={agg["per_column"]["Project"]:,}  Line={agg["per_column"]["Line"]:,}\n")

    elif args[0] == "all":
        print("=" * 50)
        print("[一键执行] 导入 → Spec → 判定 → 报告")
        print("=" * 50)
        from src.importer.cli import main as importer_main
        from src.spec_manager.cli import main as spec_main
        from src.judge.cli import main as judge_main
        from src.aggregator.cli import main as aggr_main
        print("\n>>> 步骤 1/4: 导入数据 + Spec")
        importer_main()
        spec_main()
        print("\n>>> 步骤 2/4: 执行判定")
        judge_main()
        print("\n>>> 步骤 3/4: 生成报告")
        aggr_main()
        print("\n>>> 步骤 4/4: 启动 Dashboard")
        _run_dashboard(with_public=with_public)
    else:
        print(f"未知命令: {args[0]}")
        print("可用命令: dashboard | import | spec | judge | report | clean-data | all")
        print("可选参数: --public (开启公网访问)")


if __name__ == "__main__":
    main()
