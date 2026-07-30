"""
数据导入 CLI 模块

提供命令行接口用于导入 Excel 数据和查看已导入批次。
使用 Click 框架构建命令，集成 TaskTracker 进度跟踪。

使用方式：
    python -m src.importer.cli import --file <path>
    python -m src.importer.cli list-batches
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click

from src.config import RAW_DIR
from src.importer.excel_reader import (
    detect_fai_columns,
    read_data_sheet,
    read_spec_sheet,
)
from src.importer.parquet_writer import generate_batch_id, write_to_parquet
from src.monitor.models import TaskType


@click.group()
@click.version_option(version="0.1.0", prog_name="yield-importer")
def cli():
    """良率分析工具 - 数据导入模块

    支持从 Excel 文件导入良率测量数据和规格定义，
    转换为高性能 Parquet 格式用于后续分析。
    """
    pass


@cli.command("import")
@click.option(
    "--file", "-f",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Excel 文件路径（必填）",
)
@click.option(
    "--data-sheet",
    default="Data",
    show_default=True,
    help="Data Sheet 名称",
)
@click.option(
    "--spec-sheet",
    default="Spec",
    show_default=True,
    help="Spec Sheet 名称",
)
@click.option(
    "--batch-id",
    default=None,
    help="自定义批次 ID（默认自动生成，格式: YYYYMMDD_UUID前缀）",
)
def import_data(
    file: str,
    data_sheet: str,
    spec_sheet: str,
    batch_id: Optional[str],
):
    """
    导入 Excel 数据并转换为 Parquet 格式。

    流程：读取 Spec → 读取 Data 表头 → 检测 FAI 列 → 写入 Parquet

    \b
    示例：
        python -m src.importer.cli import -f rawdata.xlsx
        python -m src.importer.cli import -f rawdata.xlsx --batch-id my_batch
    """
    # ── 生成批次 ID ─────────────────────────────────────
    if batch_id is None:
        batch_id = generate_batch_id()

    output_path = RAW_DIR / f"raw_{batch_id}.parquet"

    # ── 延迟导入 tracker（仅在用到时） ──────────────────
    from src.monitor.tracker import get_tracker
    tracker = get_tracker()
    task_id = f"import_{batch_id}"

    click.echo(f" 批次: {batch_id}")
    click.echo(f" 文件: {file}")
    click.echo(f" 输出: {output_path}")
    click.echo()

    try:
        # ── Step 1: 读取 Spec Sheet ─────────────────────
        click.echo("[1/4] 读取规格定义 (Spec Sheet)...")
        specs = read_spec_sheet(file, sheet_name=spec_sheet)
        spec_fai_names = [s["fai_name"] for s in specs]
        click.echo(f"      读取到 {len(specs)} 条规格定义")

        # ── Step 2: 读取 Data Sheet 表头 ────────────────
        click.echo("[2/4] 读取 Data Sheet 表头...")
        columns, row_gen, total_cols = read_data_sheet(file, sheet_name=data_sheet)
        click.echo(f"      共 {len(columns)} 列（原始 {total_cols} 列，已过滤空列）")

        # ── Step 3: 检测 FAI 测量列 ─────────────────────
        click.echo("[3/4] 匹配 FAI 测量列...")
        matched_fai, unmatched = detect_fai_columns(columns, spec_fai_names)
        click.echo(f"      匹配: {len(matched_fai)} 个 FAI 测量列")
        click.echo(f"      未匹配: {len(unmatched)} 个列（非 FAI 或额外数据列）")

        if len(matched_fai) == 0:
            click.echo("      警告: 没有匹配到任何 FAI 测量列，请检查 Spec 与 Data 列名是否一致")
            if len(unmatched) <= 10:
                click.echo(f"      未匹配列: {unmatched}")

        # ── 启动进度跟踪 ────────────────────────────────
        tracker.start_task(
            task_id=task_id,
            task_type=TaskType.IMPORT,
            total_steps=0,  # 行数未知，不显示百分比
        )

        # ── Step 4: 写入 Parquet ────────────────────────
        click.echo("[4/4] 写入 Parquet 文件...")

        # 进度包装器：每 10000 行报告一次进度
        row_counter = [0]

        def progress_wrapper(rows_written: int, _total: int):
            row_counter[0] = rows_written
            # 避免过于频繁的 I/O（每 chunk 更新一次即可，chunk_size=50000）
            tracker.update_progress(
                task_id=task_id,
                completed=rows_written,
                step_desc=f"已写入 {rows_written:,} 行",
            )

        # 包装生成器以统计行数
        def counting_generator():
            count = 0
            for row in row_gen:
                count += 1
                yield row
            row_counter[0] = count

        wrapped_gen = counting_generator()

        output, total_rows = write_to_parquet(
            rows_generator=wrapped_gen,
            columns=columns,
            output_path=str(output_path),
            progress_callback=progress_wrapper,
        )

        # ── 汇总结果 ─────────────────────────────────────
        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)

        result: Dict[str, Any] = {
            "batch_id": batch_id,
            "source_file": str(Path(file).absolute()),
            "total_columns": len(columns),
            "matched_fai_columns": len(matched_fai),
            "unmatched_columns": len(unmatched),
            "spec_count": len(specs),
            "total_rows": total_rows,
            "output_file": str(output_path),
            "file_size_mb": round(file_size_mb, 2),
        }

        tracker.complete_task(task_id, success=True, result=result)

        click.echo()
        click.echo("━" * 50)
        click.echo(" 导入完成")
        click.echo("━" * 50)
        click.echo(f"  批次 ID:    {batch_id}")
        click.echo(f"  数据行数:   {total_rows:,}")
        click.echo(f"  列数:       {len(columns)}")
        click.echo(f"  FAI 测量列: {len(matched_fai)}")
        click.echo(f"  规格定义:   {len(specs)}")
        click.echo(f"  文件大小:   {file_size_mb:.1f} MB")
        click.echo(f"  输出路径:   {output_path}")
        click.echo()

    except Exception as exc:
        tracker.fail_task(task_id, str(exc))
        click.echo(f"\n 导入失败: {exc}", err=True)
        raise SystemExit(1) from exc


@cli.command("list-batches")
def list_batches():
    """
    列出所有已导入的批次。

    扫描 data/raw/ 目录，展示每个批次的基本信息：
    批次 ID、文件大小、导入时间。
    """
    files = sorted(RAW_DIR.glob("raw_*.parquet"))

    if not files:
        click.echo(" 暂无已导入批次")
        click.echo(f"   数据目录: {RAW_DIR}")
        return

    click.echo(f" 已导入批次（共 {len(files)} 个）:")
    click.echo()

    for f in files:
        batch_id = f.stem.replace("raw_", "")
        size_mb = f.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(f.stat().st_mtime)

        click.echo(f"  {batch_id}")
        click.echo(f"    大小: {size_mb:.1f} MB")
        click.echo(f"    时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        click.echo()


@cli.command("info")
@click.argument("batch_id")
def batch_info(batch_id: str):
    """
    查看指定批次的详细信息。

    BATCH_ID: 批次 ID（如 20260721_a1b2c3d4）
    """
    file_path = RAW_DIR / f"raw_{batch_id}.parquet"

    if not file_path.exists():
        click.echo(f" 批次 '{batch_id}' 不存在")
        click.echo(f"   查找路径: {file_path}")
        return

    import pyarrow.parquet as pq

    # 读取 Parquet 文件的元数据
    parquet_file = pq.ParquetFile(str(file_path))
    metadata = parquet_file.metadata
    schema = parquet_file.schema_arrow

    file_size_mb = file_path.stat().st_size / (1024 * 1024)

    click.echo(f" 批次: {batch_id}")
    click.echo(f" 文件: {file_path}")
    click.echo(f" 大小: {file_size_mb:.1f} MB")
    click.echo(f" 总行数: {metadata.num_rows:,}")
    click.echo(f" 总列数: {metadata.num_columns}")
    click.echo(f" Row Groups: {metadata.num_row_groups}")
    click.echo()

    # 列信息
    click.echo(" 列信息:")
    for i in range(min(metadata.num_columns, 30)):
        col_name = schema.field(i).name
        col_type = schema.field(i).type
        click.echo(f"   {i:3d}. {col_name:<30s} {col_type}")

    if metadata.num_columns > 30:
        click.echo(f"   ... 及其他 {metadata.num_columns - 30} 列")
    click.echo()

    parquet_file.close()


if __name__ == "__main__":
    cli()
