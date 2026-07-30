"""
聚合分析 CLI

提供命令行接口用于快速查看分析报告。
用法:
  python -m src.aggregator.cli report
  python -m src.aggregator.cli top-defects
  python -m src.aggregator.cli export
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from src.config import EXPORTS_DIR
from src.aggregator.yield_calc import (
    get_summary, get_daily_yield, get_weekly_yield,
    get_cfg_yield, get_regression_yield, get_multi_production_sns,
)
from src.aggregator.top_defects import get_top_defects, get_fai_defect_detail
from src.aggregator.regression import get_duplicate_sn_count, get_regression_summary
from src.aggregator.exporter import (
    export_daily_report,
    export_daily_report_regression,
    export_both_reports,
)

console = Console()


@click.group()
def main():
    """良率聚合分析工具"""
    pass


@main.command()
def report():
    """生成完整分析报告"""
    console.print("\n[bold cyan]══════════════════════════════════[/]")
    console.print("[bold cyan]  良率分析报告[/]")
    console.print("[bold cyan]══════════════════════════════════[/]\n")

    # 总体良率
    s = get_summary()
    console.print(f"[bold]总体良率:[/] {s['yield_pct']}%")
    console.print(f"  总记录: {s['total']:,}  |  OK: {s['ok_count']:,}  |  NG: {s['ng_count']:,}\n")

    # 按 Line
    cfg_data = get_cfg_yield()
    if cfg_data:
        table = Table(title="按 Line 良率")
        table.add_column("Line", style="cyan")
        table.add_column("总数", justify="right")
        table.add_column("OK数", justify="right")
        table.add_column("良率", justify="right")
        for r in cfg_data:
            table.add_row(r['cfg'], f"{r['total']:,}", f"{r['ok_count']:,}", f"{r['yield_pct']}%")
        console.print(table)
        console.print()

    # 每日良率（最近10天）
    daily = get_daily_yield()
    if daily:
        table = Table(title="最近日良率")
        table.add_column("日期", style="cyan")
        table.add_column("总数", justify="right")
        table.add_column("OK", justify="right")
        table.add_column("NG", justify="right")
        table.add_column("良率", justify="right")
        for r in daily[-10:]:
            table.add_row(
                r['production_day'][:10], f"{r['total']:,}",
                f"{r['ok_count']:,}", f"{r['ng_count']:,}",
                f"{r['yield_pct']}%"
            )
        console.print(table)
        console.print()

    # SN 回归统计
    reg = get_regression_summary()
    console.print(f"[bold]SN 分析:[/]")
    console.print(f"  总SN: {reg['total_sn']:,}  |  重复投产: {reg['duplicate_sn']:,}")
    console.print(f"  重复率: {reg['duplicate_rate_pct']}%  |  最多投产: {reg['max_productions']}次\n")

    # TOP10 不良
    top = get_top_defects(top_n=10)
    if top:
        table = Table(title="TOP 10 不良 FAI")
        table.add_column("FAI名称", style="red")
        table.add_column("NG数", justify="right")
        table.add_column("总数", justify="right")
        table.add_column("不良率", justify="right")
        for r in top:
            table.add_row(
                r['fai_name'], f"{r['ng_count']:,}",
                f"{r['total']:,}", f"{r['ng_rate_pct']}%"
            )
        console.print(table)


@main.command()
@click.option("--top-n", "-n", default=20, help="返回前N个不良项")
def top_defects(top_n):
    """查看 TOP N 不良 FAI"""
    defects = get_top_defects(top_n=top_n)
    if not defects:
        console.print("[yellow]未找到不良数据[/]")
        return

    table = Table(title=f"TOP {top_n} 不良 FAI")
    table.add_column("排名", justify="right")
    table.add_column("FAI名称", style="red")
    table.add_column("NG数", justify="right")
    table.add_column("不良率", justify="right")

    for i, d in enumerate(defects, 1):
        table.add_row(
            str(i), d['fai_name'],
            f"{d['ng_count']:,}", f"{d['ng_rate_pct']}%"
        )
    console.print(table)


@main.command()
@click.option("--fai", "-f", required=True, help="FAI 名称")
@click.option("--top-n", "-n", default=50, help="返回行数")
def fai_detail(fai, top_n):
    """查看指定 FAI 的不良明细"""
    details = get_fai_defect_detail(fai_name=fai, top_n=top_n)
    if not details:
        console.print(f"[yellow]FAI '{fai}' 无不良记录[/]")
        return

    console.print(f"\n[bold]FAI: {fai}[/] - 共 {len(details)} 条不良记录\n")
    table = Table(title="不良明细")
    table.add_column("SN", style="cyan")
    table.add_column("测量值", justify="right")
    table.add_column("时间")
    table.add_column("Line")
    for d in details[:20]:
        table.add_row(
            d['SN'][:30], f"{d['measured_value']}",
            d['Time'][:19] if d['Time'] else "N/A",
            d['Line'] or "N/A"
        )
    console.print(table)


@main.command()
@click.option("--top-n", "-n", default=10, help="每天导出的 TOP N 不良数（默认10）")
@click.option("--mode", "-m", default="both",
              type=click.Choice(["pre", "post", "both"]),
              help="导出模式: pre=回归前, post=回归后, both=两者都导出（默认）")
@click.option("--output", "-o", default=None, help="输出文件路径（仅 --mode pre/post 时有效）")
def export(top_n, mode, output):
    """
    导出每日良率 + 每日 TOP N 不良 → Excel

    生成结构化的 .xlsx 文件，包含「每日良率」和「每日TOP不良」两个 Sheet。

    \b
    回归前（pre）：使用原始 judged 数据，每条 SN 独立计数
    回归后（post）：SN 去重，同一 SN 取最新记录，归入首次投产日
    """
    try:
        if mode == "both":
            pre_path, post_path = export_both_reports(top_n=top_n)
            console.print(f"\n[green]✅ 两份日报已导出:[/]")
            console.print(f"  回归前: [cyan]{pre_path}[/]")
            console.print(f"  回归后: [cyan]{post_path}[/]")
        elif mode == "pre":
            path = export_daily_report(output_path=output, top_n=top_n)
            console.print(f"\n[green]✅ 回归前日报已导出:[/] [cyan]{path}[/]")
        elif mode == "post":
            path = export_daily_report_regression(output_path=output, top_n=top_n)
            console.print(f"\n[green]✅ 回归后日报已导出:[/] [cyan]{path}[/]")
    except RuntimeError as e:
        console.print(f"[red]❌ 导出失败: {e}[/]")
        sys.exit(1)


@main.command()
def summary():
    """快速查看 Summary"""
    s = get_summary()
    console.print(f"良率: {s['yield_pct']}%  |  总: {s['total']:,}  |  OK: {s['ok_count']:,}  |  NG: {s['ng_count']:,}")


if __name__ == "__main__":
    main()
