"""
数据导入模块

负责从 Excel 文件读取良率测量数据和规格定义，
转换为 Parquet 格式存储，供后续判定和分析使用。

主要入口：
    CLI: python -m src.importer.cli import --file <path>
    API: from src.importer import excel_reader, parquet_writer
"""

from src.importer.excel_reader import (
    detect_fai_columns,
    read_data_sheet,
    read_spec_sheet,
)
from src.importer.parquet_writer import generate_batch_id, write_to_parquet
from src.importer.csv_reader import (
    csv_to_parquet_fast,
    read_csv_stream,
    read_csv_columns,
    detect_csv_encoding,
    detect_delimiter,
)

__all__ = [
    # Excel
    "read_data_sheet",
    "read_spec_sheet",
    "detect_fai_columns",
    "write_to_parquet",
    "generate_batch_id",
    # CSV
    "csv_to_parquet_fast",
    "read_csv_stream",
    "read_csv_columns",
    "detect_csv_encoding",
    "detect_delimiter",
]
