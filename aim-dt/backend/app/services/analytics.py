from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from app.config import get_settings
from app.services.rules import effective_limits, resolve_mapping

settings = get_settings()
SENTINELS = {-999.0, 9999.0}
DETAIL_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("sn", pa.string()),
        ("detected_at", pa.timestamp("us")),
        ("production_day", pa.date32()),
        ("config", pa.string()),
        ("site_name", pa.string()),
        ("equipment_id", pa.string()),
        ("slot", pa.string()),
        ("cell", pa.string()),
        ("tester", pa.string()),
        ("qpl", pa.string()),
        ("processing_ms", pa.float64()),
        ("original_final_result", pa.string()),
        ("event_outcome", pa.string()),
        ("error_reason", pa.string()),
        ("measurement_json", pa.string()),
        ("point_results_json", pa.string()),
    ]
)


@dataclass(slots=True)
class EventRow:
    event_id: str
    sn: str
    detected_at: datetime
    production_day: Any
    config: str | None
    site_name: str | None
    equipment_id: str | None
    slot: str | None
    processing_ms: float | None
    original_final_result: str | None
    measurement: dict[str, float | None]
    source_sequence: int
    cell: str = "Unassigned"
    tester: str = "Unassigned"
    qpl: str = "Unassigned"
    point_results: dict[str, str] = field(default_factory=dict)
    outcome: str = "ERROR"
    error_reason: str = ""


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return None if not denominator else round(numerator / denominator, 6)


def _safe_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number in SENTINELS:
        return None
    return number


def evaluate_event(
    measurement: dict[str, Any],
    spec_rules: dict[str, Any],
    config: str | None,
    enabled_points: Iterable[str],
) -> tuple[dict[str, str], str, str]:
    point_results: dict[str, str] = {}
    reasons: list[str] = []
    for point in enabled_points:
        value = _safe_value(measurement.get(point))
        if value is None:
            point_results[point] = "ERROR"
            reasons.append(f"{point}:无效值")
            continue
        lsl, usl = effective_limits(spec_rules, config, point)
        if lsl is not None and value < lsl:
            point_results[point] = "FAIL"
            reasons.append(f"{point}:{value:g}<{lsl:g}")
        elif usl is not None and value > usl:
            point_results[point] = "FAIL"
            reasons.append(f"{point}:{value:g}>{usl:g}")
        else:
            point_results[point] = "PASS"
    if any(result == "FAIL" for result in point_results.values()):
        return point_results, "FAIL", "; ".join(reasons)
    if any(result == "ERROR" for result in point_results.values()):
        return point_results, "ERROR", "; ".join(reasons)
    return point_results, "PASS", ""


class Reservoir:
    def __init__(self, limit: int = 100_000) -> None:
        self.limit = limit
        self.seen = 0
        self.values: list[float] = []

    def add(self, value: float) -> None:
        self.seen += 1
        if len(self.values) < self.limit:
            self.values.append(value)
            return
        probe = (self.seen * 2654435761) % self.limit
        if probe < self.limit:
            self.values[probe] = value


def _kde(values: list[float], bins: int = 128, points: int = 80) -> list[dict[str, float]]:
    if len(values) < 2:
        return []
    data = np.asarray(values, dtype=float)
    hist, edges = np.histogram(data, bins=bins, density=False)
    if hist.sum() == 0:
        return []
    density = hist.astype(float) / max(1.0, hist.sum() * np.diff(edges).mean())
    kernel = np.exp(-0.5 * np.linspace(-3, 3, 15) ** 2)
    kernel /= kernel.sum()
    smooth = np.convolve(np.pad(density, (7, 7), mode="edge"), kernel, mode="valid")
    centers = (edges[:-1] + edges[1:]) / 2
    indexes = np.linspace(0, len(centers) - 1, min(points, len(centers))).astype(int)
    return [
        {"x": round(float(centers[i]), 8), "density": round(float(smooth[i]), 10)} for i in indexes
    ]


def _parse_measurement(raw: Any) -> dict[str, float | None]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _detail_writer(path: Path):
    writer = pq.ParquetWriter(path, DETAIL_SCHEMA, compression="zstd", use_dictionary=True)
    return writer


def _write_details(rows: list[dict[str, Any]], writer: pq.ParquetWriter) -> None:
    if not rows:
        return
    writer.write_table(pa.Table.from_pylist(rows, schema=DETAIL_SCHEMA))


def _source_sql(paths: list[Path], filters: dict[str, Any]) -> tuple[str, list[Any]]:
    if not paths:
        raise ValueError("没有可分析的数据批次")
    placeholders: list[Any] = []
    conditions: list[str] = []
    if filters.get("date_from"):
        conditions.append("production_day >= ?")
        placeholders.append(filters["date_from"])
    if filters.get("date_to"):
        conditions.append("production_day <= ?")
        placeholders.append(filters["date_to"])
    if filters.get("configs"):
        marks = ",".join("?" for _ in filters["configs"])
        conditions.append(f"config IN ({marks})")
        placeholders.extend(filters["configs"])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return f"SELECT * FROM raw{where} ORDER BY sn, detected_at, source_sequence", placeholders


def analyze_parquet(
    paths: list[Path],
    *,
    spec: dict[str, Any],
    mapping: list[dict[str, Any]],
    filters: dict[str, Any],
    snapshot_dir: Path,
    heartbeat=None,
    category_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    detail_path = snapshot_dir / "events.parquet"
    detail_writer = _detail_writer(detail_path)
    con = duckdb.connect(":memory:")
    try:
        path_sql = ",".join("'" + str(path).replace("'", "''") + "'" for path in paths)
        con.execute(
            f"""
            CREATE TEMP VIEW raw AS
            WITH combined AS (
                SELECT * FROM read_parquet([{path_sql}])
            ), dedup AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY event_hash ORDER BY detected_at, source_sequence
                ) AS rn
                FROM combined
            )
            SELECT * EXCLUDE (rn) FROM dedup WHERE rn = 1
            """
        )
        query, params = _source_sql(paths, filters)
        cursor = con.execute(query, params)

        enabled_points = spec["enabled_points"]
        spec_rules = spec["rules"]
        time_buckets: dict[str, dict[str, int]] = defaultdict(
            lambda: {"input": 0, "pass": 0, "fail_error": 0}
        )
        tester_stats: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
            lambda: {"pass": 0, "fail": 0, "error": 0}
        )
        dist: dict[tuple[str, str], Reservoir] = defaultdict(Reservoir)
        quality_counter: Counter[str] = Counter()
        mismatch_count = 0
        unknown_mapping = 0
        processing_sum = 0.0
        processing_count = 0
        total_events = 0
        current_sn: str | None = None
        unit_events: list[EventRow] = []
        pareto_counts: Counter[str] = Counter()
        cell_pie: dict[str, Counter[str]] = defaultdict(Counter)
        unit_states: Counter[str] = Counter()
        detail_batch: list[dict[str, Any]] = []

        def finish_unit(events: list[EventRow]) -> None:
            nonlocal mismatch_count
            if not events:
                return
            first = events[0]
            last = events[-1]
            if first.outcome == "PASS":
                unit_states["first_pass"] += 1
            if last.outcome == "PASS":
                if first.outcome == "PASS":
                    unit_states["final_pass"] += 1
                    cell_pie[last.cell]["First Pass"] += 1
                else:
                    unit_states["retest_pass"] += 1
                    cell_pie[last.cell]["Retest Pass"] += 1
            else:
                unit_states["final_ng"] += 1
                cell_pie[last.cell]["Final NG"] += 1
            if first.outcome != "PASS":
                if len(events) > 1:
                    unit_states["retested_first_fail"] += 1
                else:
                    unit_states["unretested_ng"] += 1
            if last.outcome != "PASS":
                for point, result in last.point_results.items():
                    if result != "PASS":
                        pareto_counts[point] += 1
                if not last.point_results:
                    pareto_counts["ERROR"] += 1

        while True:
            rows = cursor.fetchmany(20_000)
            if not rows:
                break
            columns = [item[0] for item in cursor.description]
            for raw in rows:
                row = dict(zip(columns, raw, strict=True))
                if current_sn is not None and row["sn"] != current_sn:
                    finish_unit(unit_events)
                    unit_events = []
                current_sn = row["sn"]
                event = EventRow(
                    event_id=row["event_id"],
                    sn=row["sn"],
                    detected_at=row["detected_at"],
                    production_day=row["production_day"],
                    config=row.get("config"),
                    site_name=row.get("site_name"),
                    equipment_id=row.get("equipment_id"),
                    slot=str(row["slot"]) if row.get("slot") is not None else None,
                    processing_ms=row.get("processing_ms"),
                    original_final_result=row.get("original_final_result"),
                    measurement=_parse_measurement(row["measurement_json"]),
                    source_sequence=int(row["source_sequence"]),
                )
                event.cell, event.tester, event.qpl = resolve_mapping(
                    {
                        "equipment_id": event.equipment_id,
                        "site_name": event.site_name,
                        "config": event.config,
                        "slot": event.slot,
                    },
                    mapping,
                )
                labels = category_labels or {}
                event.cell = labels.get(event.cell, event.cell)
                event.tester = labels.get(event.tester, event.tester)
                event.qpl = labels.get(event.qpl, event.qpl)
                if filters.get("cells") and event.cell not in filters["cells"]:
                    continue
                if filters.get("testers") and event.tester not in filters["testers"]:
                    continue
                event.point_results, event.outcome, event.error_reason = evaluate_event(
                    event.measurement, spec_rules, event.config, enabled_points
                )
                if event.cell == "Unassigned":
                    unknown_mapping += 1
                hour = event.detected_at.replace(minute=0, second=0, microsecond=0)
                bucket = hour.isoformat(timespec="minutes")
                time_buckets[bucket]["input"] += 1
                if event.outcome == "PASS":
                    time_buckets[bucket]["pass"] += 1
                else:
                    time_buckets[bucket]["fail_error"] += 1
                tester_key = (event.cell, event.qpl, event.tester)
                tester_stats[tester_key][event.outcome.lower()] += 1
                if event.processing_ms is not None and event.processing_ms not in SENTINELS:
                    processing_sum += event.processing_ms
                    processing_count += 1
                for point, value in event.measurement.items():
                    numeric = _safe_value(value)
                    if numeric is not None:
                        dist[(event.cell, point)].add(numeric)
                original = (event.original_final_result or "").strip().lower()
                original_pass = original in {"pass", "ok", "1", "true"}
                if original and original_pass != (event.outcome == "PASS"):
                    mismatch_count += 1
                quality_counter[event.outcome] += 1
                unit_events.append(event)
                total_events += 1
                detail_batch.append(
                    {
                        "event_id": event.event_id,
                        "sn": event.sn,
                        "detected_at": event.detected_at,
                        "production_day": event.production_day,
                        "config": event.config,
                        "site_name": event.site_name,
                        "equipment_id": event.equipment_id,
                        "slot": event.slot,
                        "cell": event.cell,
                        "tester": event.tester,
                        "qpl": event.qpl,
                        "processing_ms": event.processing_ms,
                        "original_final_result": event.original_final_result,
                        "event_outcome": event.outcome,
                        "error_reason": event.error_reason,
                        "measurement_json": json.dumps(event.measurement, ensure_ascii=False),
                        "point_results_json": json.dumps(event.point_results, ensure_ascii=False),
                    }
                )
                if len(detail_batch) >= 50_000:
                    _write_details(detail_batch, detail_writer)
                    detail_batch = []
                if heartbeat and total_events % 50_000 == 0:
                    heartbeat(total_events)
        finish_unit(unit_events)
        _write_details(detail_batch, detail_writer)
    finally:
        detail_writer.close()
        con.close()

    total_input = (
        sum(unit_states.values())
        - unit_states["retested_first_fail"]
        - unit_states["unretested_ng"]
    )
    # unit_states contains overlapping retest diagnostics; total is explicitly counted below.
    total_input = unit_states["first_pass"] + unit_states["final_ng"] + unit_states["retest_pass"]
    first_pass_qty = unit_states["first_pass"]
    retest_pass_qty = unit_states["retest_pass"]
    final_pass_qty = first_pass_qty + retest_pass_qty
    final_ng_qty = total_input - final_pass_qty
    retest_denominator = unit_states["retested_first_fail"]
    time_yield = []
    for bucket, item in sorted(time_buckets.items()):
        time_yield.append(
            {
                "bucket": bucket,
                "input_qty": item["input"],
                "pass_qty": item["pass"],
                "fail_error_qty": item["fail_error"],
                "yield_rate": _ratio(item["pass"], item["input"]),
            }
        )
    pareto = [
        {"point": point, "count": count, "pct_total_input": _ratio(count, total_input)}
        for point, count in pareto_counts.most_common()
    ]
    tester_yield = []
    for (cell, qpl, tester), item in sorted(tester_stats.items()):
        total = item["pass"] + item["fail"] + item["error"]
        tester_yield.append(
            {
                "cell": cell,
                "qpl": qpl,
                "tester": tester,
                "pass_qty": item["pass"],
                "fail_qty": item["fail"],
                "error_qty": item["error"],
                "yield_rate": _ratio(item["pass"], total),
            }
        )
    cell_yield = []
    for cell, counts in sorted(cell_pie.items()):
        total = sum(counts.values())
        cell_yield.append(
            {
                "cell": cell,
                "first_pass": counts["First Pass"],
                "retest_pass": counts["Retest Pass"],
                "final_ng": counts["Final NG"],
                "total": total,
            }
        )
    distribution = []
    for (cell, point), values in sorted(dist.items()):
        if not values.values:
            continue
        array = np.asarray(values.values, dtype=float)
        lsl, _ = effective_limits(spec_rules, None, point)
        _, usl = effective_limits(spec_rules, None, point)
        distribution.append(
            {
                "cell": cell,
                "point": point,
                "count": values.seen,
                "sampled": values.seen > len(values.values),
                "min": round(float(np.min(array)), 6),
                "q1": round(float(np.quantile(array, 0.25)), 6),
                "median": round(float(np.median(array)), 6),
                "q3": round(float(np.quantile(array, 0.75)), 6),
                "max": round(float(np.max(array)), 6),
                "mean": round(float(np.mean(array)), 6),
                "lsl": lsl,
                "usl": usl,
                "density": _kde(values.values),
            }
        )
    tester_rates = [item["yield_rate"] for item in tester_yield if item["yield_rate"] is not None]
    max_gap = round(max(tester_rates) - min(tester_rates), 6) if len(tester_rates) > 1 else 0.0
    warnings: list[str] = []
    if unknown_mapping:
        warnings.append(f"{unknown_mapping} 个事件未匹配 Cell/Tester 映射")
    if mismatch_count:
        warnings.append(f"{mismatch_count} 个事件与原始最终结果冲突")
    if not mapping:
        warnings.append("尚未配置 Cell/Tester 映射")
    summary = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "timezone": settings.timezone,
            "day_cutoff_hour": settings.day_cutoff_hour,
            "event_count": total_events,
            "warnings": warnings,
        },
        "kpis": {
            "total_input": total_input,
            "first_pass_qty": first_pass_qty,
            "final_pass_qty": final_pass_qty,
            "final_ng_qty": final_ng_qty,
            "first_pass_rate": _ratio(first_pass_qty, total_input),
            "final_pass_rate": _ratio(final_pass_qty, total_input),
            "retest_pass_qty": retest_pass_qty,
            "retest_pass_rate": _ratio(retest_pass_qty, retest_denominator),
            "avg_processing_ms": round(processing_sum / processing_count, 3)
            if processing_count
            else None,
            "max_tester_yield_gap": max_gap,
            "unretested_ng_qty": unit_states["unretested_ng"],
            "error_event_qty": quality_counter["ERROR"],
            "mismatch_event_qty": mismatch_count,
        },
        "time_yield": time_yield,
        "pareto": pareto,
        "cell_yield": cell_yield,
        "tester_yield": tester_yield,
        "distribution": distribution,
        "quality": {
            "event_outcomes": dict(quality_counter),
            "unknown_mapping_events": unknown_mapping,
            "mismatch_events": mismatch_count,
        },
    }
    (snapshot_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
