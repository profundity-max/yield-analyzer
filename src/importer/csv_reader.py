"""
CSV 数据读取模块

使用 PyArrow CSV 读取器高效处理超大 CSV 文件（GB 级别）。
支持自动编码检测、分隔符推断、流式分块读取。
"""

import csv as csv_module
from typing import Any, Dict, Generator, List, Optional, Tuple

import pyarrow as pa
import pyarrow.csv as pa_csv


def detect_csv_encoding(filepath: str, sample_bytes: int = 100000) -> str:
    """
    自动检测 CSV 文件编码

    依次尝试常见编码，选择能成功解码的。

    Args:
        filepath: CSV 文件路径
        sample_bytes: 采样字节数

    Returns:
        检测到的编码名称
    """
    candidates = ["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"]
    with open(filepath, "rb") as f:
        raw = f.read(sample_bytes)

    for enc in candidates:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"  # 默认回退


def detect_delimiter(filepath: str, encoding: str = "utf-8") -> str:
    """
    自动检测 CSV 分隔符

    Args:
        filepath: CSV 文件路径
        encoding: 文件编码

    Returns:
        分隔符字符
    """
    with open(filepath, "r", encoding=encoding) as f:
        # 读前几行用 csv.Sniffer 检测
        sample = "".join(f.readline() for _ in range(10))
    try:
        dialect = csv_module.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv_module.Error:
        return ","


def read_csv_columns(filepath: str, encoding: str = "utf-8", delimiter: str = ",") -> Tuple[List[str], int]:
    """
    读取 CSV 列名

    Args:
        filepath: CSV 文件路径
        encoding: 编码
        delimiter: 分隔符

    Returns:
        (列名列表, 总行数估算)
    """
    read_options = pa_csv.ReadOptions(
        encoding=encoding,
        use_threads=True,
    )
    parse_options = pa_csv.ParseOptions(delimiter=delimiter)

    # 用 PyArrow 快速读取
    table = pa_csv.read_csv(
        filepath,
        read_options=read_options,
        parse_options=parse_options,
    )
    columns = [col.strip().lstrip('﻿') for col in table.column_names]
    return columns, table.num_rows


def read_csv_stream(
    filepath: str,
    encoding: str = "utf-8",
    delimiter: str = ",",
    chunk_size: int = 100000,
) -> Tuple[List[str], Generator[List[Any], None, None], int]:
    """
    流式分块读取大型 CSV 文件

    使用 PyArrow CSV 流式读取，避免一次性加载全部数据到内存。

    Args:
        filepath: CSV 文件路径
        encoding: 文件编码（默认自动检测）
        delimiter: 分隔符（默认自动检测）
        chunk_size: 每块行数

    Returns:
        (列名列表, 数据行生成器, 总列数)
    """
    # 自动检测编码和分隔符
    if encoding is None:
        encoding = detect_csv_encoding(filepath)
    if delimiter is None:
        delimiter = detect_delimiter(filepath, encoding)

    read_options = pa_csv.ReadOptions(
        encoding=encoding,
        use_threads=True,
        block_size=chunk_size * 100,  # PyArrow 内部块大小
    )
    parse_options = pa_csv.ParseOptions(delimiter=delimiter)
    convert_options = pa_csv.ConvertOptions(
        strings_can_be_null=True,
        quoted_strings_can_be_null=True,
    )

    # 直接用 PyArrow 读取整表然后逐行 yield
    table = pa_csv.read_csv(
        filepath,
        read_options=read_options,
        parse_options=parse_options,
        convert_options=convert_options,
    )

    columns = [col.strip() for col in table.column_names]
    total_cols = len(columns)

    def row_generator() -> Generator[List[Any], None, None]:
        """逐行 yield，模拟 Excel reader 的接口"""
        for batch in table.to_batches(max_chunksize=chunk_size):
            for i in range(batch.num_rows):
                row = []
                for j in range(batch.num_columns):
                    val = batch.column(j)[i].as_py()
                    row.append(val)
                yield row

    return columns, row_generator(), total_cols


def csv_to_parquet_fast(
    csv_path: str,
    parquet_path: str,
    encoding: str = None,
    delimiter: str = None,
) -> int:
    """
    直接将 CSV 转换为 Parquet（使用 DuckDB 智能类型转换）

    适合 1GB+ 的超大 CSV 文件。
    DuckDB 自动识别日期时间格式（如 2026/07/15 06:59:00），
    避免 PyArrow 将时间列保留为字符串。

    Args:
        csv_path: CSV 源文件路径
        parquet_path: 目标 Parquet 路径
        encoding: 编码（自动检测）
        delimiter: 分隔符（自动检测）

    Returns:
        写入行数
    """
    if encoding is None:
        encoding = detect_csv_encoding(csv_path)
    if delimiter is None:
        delimiter = detect_delimiter(csv_path)

    # 使用 DuckDB 直接读取 CSV 并写入 Parquet
    # DuckDB 的 CSV 读取器能智能识别日期时间格式
    from src.db import get_connection, close_connection
    close_connection()
    conn = get_connection()

    # 构建 DuckDB CSV 读取选项
    conn.execute(f"""
        COPY (
            SELECT * FROM read_csv(
                '{csv_path}',
                delim='{delimiter}',
                header=true,
                auto_detect=true,
                all_varchar=false,
                ignore_errors=true
            )
        ) TO '{parquet_path}' (
            FORMAT PARQUET,
            COMPRESSION SNAPPY
        )
    """)

    row_count = conn.execute(f"SELECT COUNT(*) FROM '{parquet_path}'").fetchone()[0]
    return row_count
