"""
Spec 管理命令行工具

提供规格数据的加载、版本查看和版本切换功能。
使用 Click 框架 + Rich 美化输出。
"""

from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from src.spec_manager.loader import load_spec_from_excel, validate_spec
from src.spec_manager.versioning import (
    create_spec_version,
    get_active_spec,
    list_versions,
    save_spec_limits,
    set_active_version,
)

console = Console()


@click.group(name="spec")
def spec_cli():
    """Spec 规格管理工具 —— 导入、查看和切换 FAI 规格版本。"""
    pass


@spec_cli.command("load")
@click.option(
    "--file", "-f",
    required=True,
    type=click.Path(exists=True),
    help="Spec Excel 文件路径。",
)
@click.option(
    "--sheet", "-s",
    default="Spec",
    show_default=True,
    help="Excel 中的 Sheet 名称。",
)
@click.option(
    "--description", "-d",
    default="",
    help="版本描述（如 '2024Q3 基线'）。",
)
def load_command(file: str, sheet: str, description: str):
    """
    从 Excel 文件加载规格数据并创建新版本。

    流程：读取 → 校验 → 创建版本 → 保存 limits → 激活。
    """
    console.print(f"[bold cyan]正在加载 Spec 文件...[/bold cyan]")
    console.print(f"  文件: {file}")
    console.print(f"  Sheet: {sheet}")

    # 1. 读取
    try:
        spec_data = load_spec_from_excel(file, sheet_name=sheet)
    except FileNotFoundError as e:
        console.print(f"[bold red]错误:[/bold red] {e}")
        raise SystemExit(1)
    except ValueError as e:
        console.print(f"[bold red]错误:[/bold red] {e}")
        raise SystemExit(1)

    console.print(f"  [green]✓[/green] 读取到 {len(spec_data)} 条 FAI 规格")

    if len(spec_data) == 0:
        console.print("[bold red]错误:[/bold red] 未读取到任何有效数据，请检查文件内容")
        raise SystemExit(1)

    # 2. 校验
    errors = validate_spec(spec_data)
    if errors:
        console.print(f"[bold yellow]⚠ 校验发现 {len(errors)} 个问题:[/bold yellow]")
        for err in errors[:20]:  # 最多显示前 20 条
            console.print(f"    [yellow]- {err}[/yellow]")
        if len(errors) > 20:
            console.print(f"    [dim]... 还有 {len(errors) - 20} 条错误未显示[/dim]")
        if not click.confirm("校验未完全通过，是否继续导入？"):
            console.print("[dim]已取消[/dim]")
            raise SystemExit(0)
    else:
        console.print("  [green]✓[/green] 校验通过")

    # 3. 创建版本
    version_id = create_spec_version(file, description)
    console.print(f"  [green]✓[/green] 创建版本: [bold]{version_id}[/bold]")

    # 4. 保存 limits
    count = save_spec_limits(version_id, spec_data)
    console.print(f"  [green]✓[/green] 已保存 {count} 条规格上下限")

    # 5. 激活
    set_active_version(version_id)
    console.print(f"  [green]✓[/green] 已激活版本 [bold]{version_id}[/bold]")

    console.print(f"\n[bold green]导入完成！[/bold green] 当前激活版本: {version_id}")


@spec_cli.command("list-versions")
def list_versions_command():
    """
    列出所有 Spec 版本历史（表格格式）。
    """
    versions = list_versions()

    if not versions:
        console.print("[dim]暂无任何 Spec 版本[/dim]")
        return

    table = Table(title="Spec 版本历史", title_style="bold cyan")
    table.add_column("版本 ID", style="dim", max_width=40)
    table.add_column("来源文件", max_width=30)
    table.add_column("导入时间")
    table.add_column("FAI 数量", justify="right")
    table.add_column("状态")
    table.add_column("描述")

    for v in versions:
        status = "[bold green]● 当前[/bold green]" if v["is_active"] else "[dim]○ 历史[/dim]"
        vid = v["version_id"]
        # 截断过长的 version_id 以保持表格整洁
        if len(vid) > 36:
            vid = vid[:33] + "..."

        table.add_row(
            vid,
            v["source_file"] or "-",
            v["imported_at"] or "-",
            str(v["limit_count"]),
            status,
            v["description"] or "-",
        )

    console.print(table)


@spec_cli.command("activate")
@click.option(
    "--version-id", "-v",
    required=True,
    help="要激活的版本 ID。",
)
def activate_command(version_id: str):
    """
    激活指定的 Spec 版本。
    """
    try:
        set_active_version(version_id)
    except ValueError as e:
        console.print(f"[bold red]错误:[/bold red] {e}")
        raise SystemExit(1)

    console.print(f"[bold green]✓[/bold green] 已激活版本: [bold]{version_id}[/bold]")

    # 显示该版本摘要
    versions = list_versions()
    for v in versions:
        if v["version_id"] == version_id:
            console.print(f"  来源文件: {v['source_file']}")
            console.print(f"  FAI 数量: {v['limit_count']}")
            console.print(f"  导入时间: {v['imported_at']}")
            break


@spec_cli.command("show")
@click.option(
    "--fai", "-f",
    default=None,
    help="查询特定 FAI 名称的规格（不指定则显示摘要）。",
)
def show_command(fai: Optional[str]):
    """
    显示当前激活版本的信息，或查询特定 FAI 的规格。
    """
    active = get_active_spec()

    if active["version_id"] is None:
        console.print("[dim]当前没有激活的 Spec 版本[/dim]")
        return

    if fai:
        # 查询特定 FAI
        limit = active["fai_limits"].get(fai)
        if limit is None:
            console.print(f"[yellow]FAI '{fai}' 在当前版本中不存在[/yellow]")
            return

        table = Table(title=f"FAI: {fai}")
        table.add_column("项目", style="bold")
        table.add_column("值")
        table.add_row("下限 (LSL)", _fmt_limit(limit["lower"]))
        table.add_row("标准值 (Nominal)", _fmt_limit(limit["nominal"]))
        table.add_row("上限 (USL)", _fmt_limit(limit["upper"]))
        table.add_row("版本", active["version_id"])
        console.print(table)
    else:
        # 显示摘要
        console.print(f"[bold]当前激活版本:[/bold] {active['version_id']}")
        console.print(f"  来源文件: {active['source_file']}")
        console.print(f"  导入时间: {active['imported_at']}")
        console.print(f"  描述: {active['description'] or '-'}")
        console.print(f"  FAI 总数: {len(active['fai_limits'])}")

        # 显示前 10 个 FAI 预览
        if active["fai_limits"]:
            console.print("\n[bold]FAI 规格预览（前 10 条）:[/bold]")
            preview_table = Table()
            preview_table.add_column("FAI 名称")
            preview_table.add_column("下限", justify="right")
            preview_table.add_column("标准值", justify="right")
            preview_table.add_column("上限", justify="right")

            for idx, (name, limits) in enumerate(active["fai_limits"].items()):
                if idx >= 10:
                    break
                preview_table.add_row(
                    name,
                    _fmt_limit(limits["lower"]),
                    _fmt_limit(limits["nominal"]),
                    _fmt_limit(limits["upper"]),
                )
            console.print(preview_table)


def _fmt_limit(value: Optional[float]) -> str:
    """格式化规格上下限值用于显示。"""
    if value is None:
        return "[dim]不限[/dim]"
    return f"{value:.4f}"


if __name__ == "__main__":
    spec_cli()
