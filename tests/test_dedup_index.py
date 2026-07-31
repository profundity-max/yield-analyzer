"""
DedupIndex 纯逻辑单元测试

无需 DuckDB, 测试回归规则的正确性。
"""
from src.aggregator.dedup import latest_per_sn, first_per_sn


class TestLatestPerSN:
    def test_keeps_latest_for_each_sn(self):
        rows = [
            ("SN1", "2026-07-25", "NG"),
            ("SN1", "2026-07-26", "OK"),  # 最新
            ("SN2", "2026-07-25", "OK"),
        ]
        result = latest_per_sn(rows)
        assert len(result) == 2
        # SN1 留最新那条
        sn1 = [r for r in result if r[0] == "SN1"][0]
        assert sn1[1] == "2026-07-26"
        assert sn1[2] == "OK"
        # SN2 留自己的
        sn2 = [r for r in result if r[0] == "SN2"][0]
        assert sn2[1] == "2026-07-25"
        assert sn2[2] == "OK"

    def test_single_occurrence_unchanged(self):
        rows = [
            ("SN1", "2026-07-25", "OK"),
            ("SN2", "2026-07-26", "NG"),
        ]
        result = latest_per_sn(rows)
        assert len(result) == 2
        assert result[0] == ("SN1", "2026-07-25", "OK")
        assert result[1] == ("SN2", "2026-07-26", "NG")

    def test_preserves_first_appearance_order(self):
        """返回顺序按 SN 第一次出现"""
        rows = [
            ("SN_C", "2026-07-25", "X"),
            ("SN_A", "2026-07-25", "X"),
            ("SN_B", "2026-07-25", "X"),
            ("SN_C", "2026-07-27", "X"),  # SN_C 第二次
        ]
        result = latest_per_sn(rows)
        sns = [r[0] for r in result]
        assert sns == ["SN_C", "SN_A", "SN_B"]

    def test_empty_input(self):
        assert latest_per_sn([]) == []

    def test_custom_indices(self):
        """支持自定义 SN/Time 位置"""
        rows = [
            ("2026-07-25", "SN1", "NG"),  # SN 在 index 1, Time 在 index 0
            ("2026-07-26", "SN1", "OK"),
        ]
        result = latest_per_sn(rows, sn_index=1, time_index=0)
        assert len(result) == 1
        assert result[0][0] == "2026-07-26"  # Time 最新

    def test_with_datetime_objects(self):
        """Time 字段支持 datetime 对象"""
        from datetime import datetime
        rows = [
            ("SN1", datetime(2026, 7, 25), "NG"),
            ("SN1", datetime(2026, 7, 26), "OK"),
        ]
        result = latest_per_sn(rows)
        assert result[0][1] == datetime(2026, 7, 26)


class TestFirstPerSN:
    def test_keeps_earliest_for_each_sn(self):
        rows = [
            ("SN1", "2026-07-26", "OK"),  # 不是首次
            ("SN1", "2026-07-25", "NG"),  # 首次
            ("SN2", "2026-07-25", "OK"),
        ]
        result = first_per_sn(rows)
        assert len(result) == 2
        sn1 = [r for r in result if r[0] == "SN1"][0]
        assert sn1[1] == "2026-07-25"
        assert sn1[2] == "NG"

    def test_use_case_first_production_date(self):
        """回归后: 同一 SN 归入首次投产日 (日报表)"""
        rows = [
            ("SN1", "2026-07-25", "NG"),
            ("SN1", "2026-07-26", "OK"),
        ]
        result = first_per_sn(rows)
        # 用于"回归后"日良率: 7/25 显示 SN1, 但 OK
        # (因为 lastest 的 result 是 OK)
        # 这里 first_per_sn 返回 7/25 的 NG, 因为我们取的是首次记录
        # 实际生产中: first_per_sn 用于日期, latest_per_sn 用于判定结果
        assert result[0][1] == "2026-07-25"


class TestRegressionRule:
    """回归规则集成: 首次 Time + 末次 Result"""

    def test_regression_same_sn_takes_latest_result_with_first_date(self):
        """验证: SN1 7/25 NG, 7/26 OK
        回归后: 在 7/25 (首次日期) 显示 OK (末次结果)"""
        rows = [
            ("SN1", "2026-07-25", "NG"),
            ("SN1", "2026-07-26", "OK"),
        ]
        # Step 1: 找到首次日期
        firsts = first_per_sn(rows)
        first_date_map = {r[0]: r[1] for r in firsts}
        # Step 2: 找到末次结果
        latests = latest_per_sn(rows)
        latest_result_map = {r[0]: r[2] for r in latests}
        # 验证
        assert first_date_map["SN1"] == "2026-07-25"
        assert latest_result_map["SN1"] == "OK"  # 末次是 OK
