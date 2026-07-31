"""
DedupIndex — 回归去重的纯逻辑

从 (SN, Time, Result) 序列中提取"同 SN 留最新 Time 那条"的结果。
纯函数, 无 DuckDB 依赖, 可独立测试。

术语 (来自 CONTEXT.md):
- 回归 (regression): 同一 SN 多次投产时取最新一次
- 输入: 一组原始测量记录 (每条带 SN, Time, Result)
- 输出: 去重后的记录 (每 SN 留 Time 最新)

原则 (来自 codebase-design):
- "the interface is the test surface"
  DedupIndex.dedupe(rows) 接收任何 Iterable[(SN, Time, Result)],
  任何调用方都可独立测试。
- 纯逻辑 vs IO 分离: DuckDB 查询在 regression.py,
  去重规则在这里。100% 覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable, TypeVar

S = TypeVar("S", bound=Hashable)  # SN 类型 (str 居多)
T = TypeVar("T", bound=Hashable)  # Time 类型 (datetime / str 都可)


@dataclass(frozen=True)
class DedupKey:
    """去重键: 同一 SN 视为同一组"""
    sn: object

    def __hash__(self):
        return hash(self.sn)

    def __eq__(self, other):
        return isinstance(other, DedupKey) and self.sn == other.sn


def latest_per_sn(
    rows: Iterable[tuple],
    sn_index: int = 0,
    time_index: int = 1,
) -> list[tuple]:
    """
    提取每 SN 的 Time 最新那条记录。

    Args:
        rows: 原始记录序列, 每条至少包含 (SN, Time, ...)
        sn_index: SN 在元组中的位置
        time_index: Time 在元组中的位置

    Returns:
        去重后的记录列表 (顺序: 第一次出现该 SN 的顺序)

    Examples:
        >>> rows = [
        ...     ("SN1", "2026-07-25", "OK"),
        ...     ("SN1", "2026-07-26", "OK"),
        ...     ("SN2", "2026-07-25", "NG"),
        ... ]
        >>> [r[0] for r in latest_per_sn(rows)]
        ['SN1', 'SN2']
        # SN1 留 "2026-07-26" 那条, SN2 留自己的
    """
    latest: dict[object, tuple] = {}
    order: list[object] = []

    for row in rows:
        sn = row[sn_index]
        time = row[time_index]
        if sn not in latest:
            order.append(sn)
            latest[sn] = row
        else:
            # 比较 Time, 保留更大的 (字符串/日期/数字都支持 >)
            if time > latest[sn][time_index]:
                latest[sn] = row

    return [latest[sn] for sn in order]


def first_per_sn(
    rows: Iterable[tuple],
    sn_index: int = 0,
    time_index: int = 1,
) -> list[tuple]:
    """
    提取每 SN 的 Time 最早那条记录 (用于"同 SN 归入首次投产日"逻辑)。

    Args:
        rows: 原始记录序列
        sn_index: SN 位置
        time_index: Time 位置

    Returns:
        每 SN 留 Time 最早的那条
    """
    earliest: dict[object, tuple] = {}
    order: list[object] = []

    for row in rows:
        sn = row[sn_index]
        time = row[time_index]
        if sn not in earliest:
            order.append(sn)
            earliest[sn] = row
        else:
            if time < earliest[sn][time_index]:
                earliest[sn] = row

    return [earliest[sn] for sn in order]


__all__ = ["latest_per_sn", "first_per_sn"]
