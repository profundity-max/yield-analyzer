"""测试 _safe_timestamp 支持多种输入格式。"""
from datetime import datetime
from src.importer.parquet_writer import _safe_timestamp


def test_string_iso_datetime():
    ts = _safe_timestamp('2026-07-28 06:59:35')
    assert ts is not None
    dt = datetime.utcfromtimestamp(ts / 1000)
    assert dt.year == 2026 and dt.month == 7 and dt.day == 28
    assert dt.hour == 6 and dt.minute == 59


def test_string_date_only():
    ts = _safe_timestamp('2026-07-28')
    assert ts is not None
    dt = datetime.utcfromtimestamp(ts / 1000)
    assert dt.year == 2026 and dt.month == 7 and dt.day == 28


def test_string_slash_format():
    ts = _safe_timestamp('2026/07/28 06:59:35')
    assert ts is not None


def test_datetime_object():
    dt = datetime(2026, 7, 28, 6, 59, 35)
    ts = _safe_timestamp(dt)
    assert ts is not None
    # 验证 wall clock 时间保留
    assert datetime.utcfromtimestamp(ts/1000) == dt


def test_none_returns_none():
    assert _safe_timestamp(None) is None


def test_empty_string_returns_none():
    assert _safe_timestamp('') is None
    assert _safe_timestamp('   ') is None


def test_invalid_string_returns_none():
    assert _safe_timestamp('not a date') is None
    assert _safe_timestamp('NaN') is None
    assert _safe_timestamp('-') is None


def test_excel_serial_number():
    # Excel 日期序列号 45595.2904 ≈ 2024-10-30
    ts = _safe_timestamp(45595.2904)
    assert ts is not None


def test_int_serial_number():
    ts = _safe_timestamp(45595)
    assert ts is not None
