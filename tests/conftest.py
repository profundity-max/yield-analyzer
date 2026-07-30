import pytest
"""pytest 公共配置 + fixture。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _ensure_data_dirs():
    """测试期间确保数据目录存在。"""
    from src.config import DATA_DIR, RAW_DIR, JUDGED_DIR, UPLOADS_DIR, PROGRESS_DIR, EXPORTS_DIR, ARCHIVE_DIR, LOGS_DIR
    for d in [DATA_DIR, RAW_DIR, JUDGED_DIR, UPLOADS_DIR, PROGRESS_DIR, EXPORTS_DIR, ARCHIVE_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)



class _InMemoryDuckDB:
    """测试用 in-memory DuckDB adapter (无 DataAccess 依赖)。"""
    def __init__(self):
        import duckdb
        self._conn = duckdb.connect(":memory:")

    def query(self, sql, params=None):
        if params:
            return self._conn.execute(sql, params)
        return self._conn.execute(sql)

    def fetchdf(self, sql, params=None):
        if params:
            return self._conn.execute(sql, params).fetchdf()
        return self._conn.execute(sql).fetchdf()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


@pytest.fixture
def in_memory_db():
    """in-memory DuckDB, 测试用, 不影响生产数据库。"""
    da = _InMemoryDuckDB()
    yield da
    da.close()


@pytest.fixture
def parquet_dir_with_sample(tmp_path):
    """创建带样本数据的临时目录, 让 read_parquet 能读到。"""
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.table({
        "SN": ["SN001", "SN001", "SN002", "SN002", "SN002"],
        "CFG": ["LineA", "LineA", "LineA", "LineA", "LineA"],
        "Time": ["2026-07-25 10:00", "2026-07-25 12:00",
                 "2026-07-26 09:00", "2026-07-26 14:00", "2026-07-27 08:00"],
        "Yield1": [1, 1, 1, 1, 1],
        "Yield2": [1, 1, 1, 1, 1],
        "Yield3": [1, 1, 1, 1, 1],
        "FAI001": [10.0, 10.5, 9.8, 10.2, 10.1],
        "FAI001_result": [0, 0, 0, 0, 0],
        "FAI002": [20.0, 20.1, 19.9, 20.0, 20.05],
        "FAI002_result": [0, 0, 0, 0, 0],
        "overall_result": [0, 0, 0, 0, 0],
    })
    pq_dir = tmp_path / "judged"
    pq_dir.mkdir()
    pq.write_table(table, str(pq_dir / "test_20260725.parquet"))
    return str(pq_dir)
