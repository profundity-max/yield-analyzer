"""
FAI 判定引擎 — 命令行入口

提供判定、重新判定和进度查看的命令行接口。

使用方式：
    python -m src.judge.cli judge                     # 判定所有未处理的批次
    python -m src.judge.cli judge --batch <batch_id>  # 判定指定批次
    python -m src.judge.cli judge --chunk-size 10000  # 自定义 chunk 大小
    python -m src.judge.cli rejudge --batch <batch_id># 用最新 spec 重新判定
    python -m src.judge.cli rejudge --all              # 重新判定全部批次
    python -m src.judge.cli status                     # 查看判定进度
"""

import logging
from pathlib import Path
from typing import Optional

import click

from src.config import (
    JUDGE_CHUNK_SIZE,
    RAW_DIR,
    JUDGED_DIR,
)
from src.monitor.models import TaskType
from src.monitor.tracker import get_tracker
from src.spec_manager.versioning import get_active_spec

logger = logging.getLogger(__name__)

# ── 配置日志（CLI 场景下的基本输出） ────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ═══════════════════════════════════════════════════════════════
# Click 命令组
# ═══════════════════════════════════════════════════════════════


@click.group()
@click.version_option(version="0.1.0", prog_name="yield-judge")
def cli():
    """良率分析工具 - FAI 判定引擎

    对原始测量数据执行自动化 FAI（First Article Inspection）判定，
    支持断点续传、大规模并行处理和 SN 去重。
    """
    pass


@cli.command("judge")
@click.option(
    "--batch", "-b",
    default=None,
    help="批次 ID（如 20260721_a1b2c3d4）。不指定则处理所有未判定批次。",
)
@click.option(
    "--chunk-size", "-c",
    default=None,
    type=int,
    help=f"每批次处理行数（默认 {JUDGE_CHUNK_SIZE:,}）",
)
def judge_cmd(batch: Optional[str], chunk_size: Optional[int]):
    """
    执行 FAI 判定。

    流程：获取激活的 Spec → 找到 raw parquet → 分批判定 → 输出到 judged/

    \b
    示例：
        python -m src.judge.cli judge                        # 判定所有未处理批次
        python -m src.judge.cli judge -b 20260721_a1b2c3d4  # 判定指定批次
        python -m src.judge.cli judge -c 10000               # 小 chunk 模式
    """
    # ── 参数处理 ─────────────────────────────────────────────
    _chunk_size = chunk_size if chunk_size else JUDGE_CHUNK_SIZE

    # ── 获取激活的 Spec ──────────────────────────────────────
    click.echo("=" * 60)
    click.echo("  FAI 判定引擎")
    click.echo("=" * 60)
    click.echo()

    click.echo("[1/3] 获取激活的 Spec 版本...")
    try:
        spec_data = get_active_spec()
    except Exception as e:
        click.echo(f"  错误: 无法获取 Spec 数据: {e}", err=True)
        raise SystemExit(1) from e

    if spec_data["version_id"] is None:
        click.echo("  错误: 没有激活的 Spec 版本。请先导入并激活 Spec。")
        click.echo("  使用: python -m src.spec_manager.cli activate <version_id>")
        raise SystemExit(1)

    click.echo(f"  Spec 版本: {spec_data['version_id']}")
    click.echo(f"  FAI 定义数: {len(spec_data['fai_limits'])}")
    click.echo()

    # ── 确定要处理的原始文件 ────────────────────────────────
    click.echo("[2/3] 查找待判定批次...")

    if batch:
        raw_path = RAW_DIR / f"raw_{batch}.parquet"
        if not raw_path.exists():
            click.echo(f"  错误: 批次 '{batch}' 不存在 ({raw_path})")
            click.echo(f"  可用批次列表:")
            for f in RAW_DIR.glob("raw_*.parquet"):
                click.echo(f"    - {f.stem.replace('raw_', '')}")
            raise SystemExit(1)
        raw_files = [raw_path]
    else:
        raw_files = _find_unjudged_batches()
        if not raw_files:
            click.echo("  所有批次均已判定，无需处理。")
            click.echo("  使用 rejudge --all 强制重新判定。")
            return

    click.echo(f"  待处理: {len(raw_files)} 个批次")
    for rf in raw_files:
        click.echo(f"    - {rf.name}")
    click.echo()

    # ── 执行判定 ─────────────────────────────────────────────
    click.echo("[3/3] 执行判定...")
    click.echo()

    # 延迟导入，避免循环依赖
    from src.judge.chunker import process_with_progress

    success_count = 0
    fail_count = 0

    for raw_path in raw_files:
        this_batch = raw_path.stem.replace("raw_", "")
        output_path = JUDGED_DIR / f"judged_{this_batch}.parquet"

        click.echo(f"  >>> 判定批次: {this_batch}")
        click.echo(f"      输入: {raw_path}")
        click.echo(f"      输出: {output_path}")

        try:
            result = process_with_progress(
                raw_path=raw_path,
                spec_data=spec_data,
                output_path=output_path,
                chunk_size=_chunk_size,
                batch_id=this_batch,
            )

            click.echo(f"      完成: {result['total_rows']:,} 行")
            click.echo(f"      良率: {result['yield_rate']}%")
            click.echo(f"      OK: {result['ok_count']:,}, NG: {result['ng_count']:,}")
            click.echo(f"      FAI 列: {result['matched_fai_columns']} 匹配"
                       f" / {result['unmatched_fai_columns']} 未匹配")
            click.echo()
            success_count += 1

        except Exception as e:
            click.echo(f"      失败: {e}", err=True)
            click.echo()
            fail_count += 1
            logger.exception("批次 %s 判定失败", this_batch)

    # ── 汇总 ─────────────────────────────────────────────────
    click.echo("=" * 60)
    if fail_count == 0:
        click.echo(f"  全部完成: {success_count} 个批次判定成功")
    else:
        click.echo(f"  完成: {success_count} 成功, {fail_count} 失败, 共 {len(raw_files)} 个批次")
    click.echo("=" * 60)


@cli.command("rejudge")
@click.option(
    "--batch", "-b",
    default=None,
    help="要重新判定的批次 ID",
)
@click.option(
    "--all", "rejudge_all",
    is_flag=True,
    default=False,
    help="重新判定所有已判定批次",
)
def rejudge_cmd(batch: Optional[str], rejudge_all: bool):
    """
    使用最新 Spec 重新判定。

    删除旧的判定结果，用当前激活的 Spec 版本重新执行判定。

    \b
    示例：
        python -m src.judge.cli rejudge -b 20260721_a1b2c3d4  # 重新判定单个批次
        python -m src.judge.cli rejudge --all                   # 重新判定全部
    """
    if not batch and not rejudge_all:
        click.echo("请指定 --batch <batch_id> 或 --all", err=True)
        raise SystemExit(1)

    # ── 获取激活 Spec ────────────────────────────────────────
    click.echo("获取激活的 Spec 版本...")
    try:
        spec_data = get_active_spec()
    except Exception as e:
        click.echo(f"错误: 无法获取 Spec 数据: {e}", err=True)
        raise SystemExit(1) from e

    if spec_data["version_id"] is None:
        click.echo("错误: 没有激活的 Spec 版本。", err=True)
        raise SystemExit(1)

    click.echo(f"Spec 版本: {spec_data['version_id']}")
    click.echo()

    # ── 确定要重新判定的批次 ────────────────────────────────
    if rejudge_all:
        judged_files = list(JUDGED_DIR.glob("judged_*.parquet"))
        if not judged_files:
            click.echo("没有已判定的批次。使用 judge 命令开始判定。")
            return
        batches = [f.stem.replace("judged_", "") for f in judged_files]
        click.echo(f"将重新判定 {len(batches)} 个批次:")
    else:
        batches = [batch]

    for b in batches:
        click.echo(f"  - {b}")

    click.echo()

    # 确认操作（交互式终端下）
    if click.confirm("确认删除旧判定结果并重新执行？"):
        # 删除旧文件，调用 judge
        for b in batches:
            old_output = JUDGED_DIR / f"judged_{b}.parquet"
            if old_output.exists():
                old_output.unlink()
                click.echo(f"  已删除: {old_output.name}")

        # 复用 judge 命令逻辑
        ctx = click.get_current_context()
        ctx.invoke(judge_cmd, batch=batch if not rejudge_all else None)
    else:
        click.echo("已取消。")


@cli.command("status")
def status_cmd():
    """
    查看当前判定进度。

    展示正在运行、已完成和失败的判定任务状态，
    包含进度百分比、当前步骤和预估剩余时间。
    """
    tracker = get_tracker()

    # ── 获取所有判定相关任务 ─────────────────────────────────
    all_tasks = tracker.list_tasks()
    judge_tasks = [
        t for t in all_tasks
        if t.task_type in (TaskType.JUDGE, TaskType.REJUDGE)
    ]

    if not judge_tasks:
        click.echo("暂无判定任务记录。")
        return

    # ── 分类展示 ─────────────────────────────────────────────
    running = [t for t in judge_tasks if t.status.value == "running"]
    completed = [t for t in judge_tasks if t.status.value == "completed"]
    failed = [t for t in judge_tasks if t.status.value == "failed"]

    click.echo("=" * 60)
    click.echo("  FAI 判定任务状态")
    click.echo("=" * 60)
    click.echo()

    if running:
        click.echo(f"  运行中 ({len(running)}):")
        click.echo("  " + "-" * 56)
        for t in running:
            _print_task_status(t)
        click.echo()

    if completed:
        click.echo(f"  已完成 ({len(completed)}):")
        click.echo("  " + "-" * 56)
        # 只显示最近 5 个完成的任务
        for t in completed[-5:]:
            _print_task_status(t)
        if len(completed) > 5:
            click.echo(f"  ... 及其他 {len(completed) - 5} 个任务")
        click.echo()

    if failed:
        click.echo(f"  失败 ({len(failed)}):")
        click.echo("  " + "-" * 56)
        for t in failed[-5:]:
            _print_task_status(t)
        if len(failed) > 5:
            click.echo(f"  ... 及其他 {len(failed) - 5} 个任务")
        click.echo()


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _find_unjudged_batches() -> list[Path]:
    """
    查找所有未判定的 raw parquet 文件。

    比较 RAW_DIR 和 JUDGED_DIR 中的文件，返回在 raw 中存在
    但 judged 中不存在的批次对应的原始文件。

    Returns:
        未判定批次的 raw parquet 文件路径列表
    """
    raw_files = {f.stem.replace("raw_", ""): f for f in RAW_DIR.glob("raw_*.parquet")}
    judged_ids = {f.stem.replace("judged_", "") for f in JUDGED_DIR.glob("judged_*.parquet")}

    unjudged_ids = set(raw_files.keys()) - judged_ids
    return [raw_files[bid] for bid in sorted(unjudged_ids)]


def _print_task_status(t) -> None:
    """格式化输出单个任务状态"""
    batch_id = t.task_id.replace("judge_", "").replace("rejudge_", "")

    # 状态标记
    status_char = {
        "running": "▶",
        "completed": "✓",
        "failed": "✗",
        "queued": "○",
    }.get(t.status.value, "?")

    click.echo(f"   {status_char} {batch_id}")

    if t.percentage > 0:
        bar_width = 20
        filled = int(bar_width * t.percentage / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        click.echo(f"     [{bar}] {t.percentage:.0f}%")

    if t.current_step:
        click.echo(f"     步骤: {t.current_step}")

    if t.estimated_remaining_seconds:
        mins = t.estimated_remaining_seconds // 60
        secs = t.estimated_remaining_seconds % 60
        click.echo(f"     预计剩余: {mins}分{secs}秒")

    if t.errors:
        for err in t.errors[-2:]:  # 最多显示 2 个错误
            click.echo(f"     错误: {err}")

    if t.started_at:
        click.echo(f"     开始: {t.started_at.strftime('%Y-%m-%d %H:%M:%S')}")

    if t.finished_at:
        click.echo(f"     完成: {t.finished_at.strftime('%Y-%m-%d %H:%M:%S')}")

    click.echo()


# ═══════════════════════════════════════════════════════════════
# 入口函数（兼容 run.py 的导入方式）
# ═══════════════════════════════════════════════════════════════


def main():
    """CLI 入口函数，供 run.py 通过 `from src.judge.cli import main` 调用"""
    cli()


if __name__ == "__main__":
    main()
