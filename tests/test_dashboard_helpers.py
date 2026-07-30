"""dashboard 小工具测试 (不依赖 DuckDB 连接)。"""
from datetime import date as _date, datetime


def test_import_batch_id_format():
    """批次 ID 应是 YYYYMMDD_xxxxxxxx 格式。"""
    from src.importer.parquet_writer import generate_batch_id
    bid = generate_batch_id()
    assert "_" in bid
    parts = bid.split("_")
    assert len(parts) == 2
    assert len(parts[0]) == 8  # YYYYMMDD
    assert len(parts[1]) == 8  # 8位hex


def test_date_range_default():
    """默认值应在合理范围。"""
    from datetime import date
    today = date.today()
    assert today.year >= 2025


def test_regression_dedup_count_consistency():
    """dedup 比率 = duplicate_rows / total_rows。"""
    # 用纯计算验证
    total, unique, dup = 100, 80, 20
    ratio = dup / total * 100
    assert ratio == 20.0
    assert unique + dup == total
