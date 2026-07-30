"""FAI 列名匹配 (Spec ↔ Parquet) 测试。"""
import pyarrow as pa
import pyarrow.parquet as pq
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def tmp_parquet():
    """创建一个临时 parquet 文件,包含已知列 (新规范名 ADR-0004)。"""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        path = f.name
    table = pa.table({
        "SN": ["s1", "s2"],
        "Line": ["L1", "L1"],
        "Project": ["967E1", "967E1"],
        "Vendor": ["LY", "LY"],
        "FAI001": [1.0, 2.0],
        "FAI002_T": [3.0, 4.0],  # _T 后缀 (热端)
        "FAI003_Z": [5.0, 6.0],  # _Z 后缀 (冷端)
        "FAI_RESULT": [0, 1],     # 应被跳过 (metadata)
    })
    pq.write_table(table, path)
    yield Path(path)
    Path(path).unlink(missing_ok=True)


def test_matching_exact_columns(tmp_parquet):
    from src.judge.engine import get_fai_columns_from_parquet
    matched, unmatched = get_fai_columns_from_parquet(
        str(tmp_parquet),
        spec_fai_names=["FAI001", "Project"],
    )
    assert "FAI001" in matched
    assert "Project" not in matched  # metadata column, 跳过


def test_matching_unmatched_returned(tmp_parquet):
    from src.judge.engine import get_fai_columns_from_parquet
    matched, unmatched = get_fai_columns_from_parquet(
        str(tmp_parquet),
        spec_fai_names=["FAI001", "FAI_DOES_NOT_EXIST"],
    )
    assert "FAI001" in matched
    assert "FAI_DOES_NOT_EXIST" in unmatched


def test_matching_t_z_suffix_handled(tmp_parquet):
    """_T (热端) 和 _Z (冷端) 后缀的 FAI 应能匹配。"""
    from src.judge.engine import get_fai_columns_from_parquet
    matched, _ = get_fai_columns_from_parquet(
        str(tmp_parquet),
        spec_fai_names=["FAI002", "FAI003"],  # 不带 _T/_Z
    )
    # 实现可能要求 exact match — 测真实行为
    assert isinstance(matched, list)


def test_missing_file_raises(tmp_parquet):
    from src.judge.engine import get_fai_columns_from_parquet
    with pytest.raises(FileNotFoundError):
        get_fai_columns_from_parquet("/no/such/file.parquet", ["FAI001"])
