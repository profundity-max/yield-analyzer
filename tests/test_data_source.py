"""
data_source.py 单元测试

覆盖:
- Filters 数据类
- ParquetSource: SQL 模板渲染
- 默认单例
"""
import pytest

from src.aggregator.data_source import (
    DataSource, ParquetSource, Filters, get_default_source, set_default_source,
)


# ════════════════════════════════════════════════════════════
# Filters
# ════════════════════════════════════════════════════════════


class TestFilters:
    def test_empty_filters(self):
        f = Filters()
        assert f.where_clause() == ""
        assert f.and_sql() == ""

    def test_project_only(self):
        f = Filters(project="967E1")
        assert f.where_clause() == '"Project" = \'967E1\''
        assert f.and_sql() == ' AND "Project" = \'967E1\''

    def test_line_only(self):
        f = Filters(line="L1")
        assert f.where_clause() == '"Line" = \'L1\''

    def test_both_filters(self):
        f = Filters(project="967E1", line="L1")
        clause = f.where_clause()
        assert '"Project" = \'967E1\'' in clause
        assert '"Line" = \'L1\'' in clause
        assert " AND " in clause

    def test_sql_injection_safety(self):
        """单引号必须被双写, 防止 SQL 注入"""
        f = Filters(project="bad'name")
        # The apostrophe in 'name' should be escaped as ''
        assert "''" in f.where_clause() or "bad''name" in f.where_clause()

    def test_frozen(self):
        """Filters 是 frozen dataclass, 不能修改"""
        f = Filters(project="967E1")
        with pytest.raises(Exception):
            f.project = "LY"  # type: ignore


# ════════════════════════════════════════════════════════════
# ParquetSource
# ════════════════════════════════════════════════════════════


class TestParquetSource:
    def test_parquet_glob(self):
        src = ParquetSource()
        glob = src.parquet_glob()
        assert "judged_*.parquet" in glob
        assert glob.startswith("'") and glob.endswith("'")

    def test_render_simple_template(self):
        src = ParquetSource()
        sql = src.read_sql("SELECT * FROM read_parquet('{{ parquet_glob }}', union_by_name=true)")
        assert "read_parquet(" in sql
        assert "judged_*.parquet" in sql

    def test_render_with_filters(self):
        """Filters 注入到 extra_where"""
        src = ParquetSource()
        template = "SELECT * FROM t WHERE 1=1{% if extra_where %} {{ extra_where }}{% endif %}"
        sql = src.read_sql(template, Filters(project="967E1", line="L1"))
        assert "Project" in sql
        assert "Line" in sql

    def test_render_with_no_filters(self):
        """无 filters 时 extra_where 为空, 条件块不渲染"""
        src = ParquetSource()
        template = "SELECT 1{% if extra_where %} WHERE {{ extra_where }}{% endif %}"
        sql = src.read_sql(template)
        assert "WHERE" not in sql

    def test_render_passes_extra_context(self):
        """额外的模板变量能透传"""
        src = ParquetSource()
        template = "SELECT {{ cutoff_hour }} AS cutoff, {{ top_n }} AS top_n"
        sql = src.read_sql(template, cutoff_hour=7, top_n=10)
        assert "7" in sql
        assert "10" in sql

    def test_cutoff_hour_in_filters(self):
        """cutoff_hour 也能从 Filters 透传"""
        src = ParquetSource()
        f = Filters(cutoff_hour=12)
        template = "SELECT {{ cutoff_hour }} AS h"
        sql = src.read_sql(template, filters=f)
        assert "12" in sql


# ════════════════════════════════════════════════════════════
# 默认单例
# ════════════════════════════════════════════════════════════


class TestDefaultSource:
    def test_get_default_is_parquet(self):
        set_default_source(ParquetSource())  # reset
        src = get_default_source()
        assert isinstance(src, ParquetSource)

    def test_inject_custom_source(self):
        class _FakeSource(DataSource):
            def parquet_glob(self):
                return "'memory'"
            def read_sql(self, template, filters=None, **ctx):
                return f"FROM {self.parquet_glob()}"
        fake = _FakeSource()
        set_default_source(fake)
        assert get_default_source() is fake
        # reset
        set_default_source(ParquetSource())


# ════════════════════════════════════════════════════════════
# DataSource 是 abstract
# ════════════════════════════════════════════════════════════


class TestDataSourceIsAbstract:
    def test_cannot_instantiate_directly(self):
        """DataSource 是抽象基类, 不应直接实例化"""
        with pytest.raises(TypeError):
            DataSource()  # type: ignore
