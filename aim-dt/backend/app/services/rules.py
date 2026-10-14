from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def effective_limits(
    rules: dict[str, Any], config: str | None, point: str
) -> tuple[float | None, float | None]:
    by_config = rules.get("by_config", {})
    if config and config in by_config and point in by_config[config]:
        item = by_config[config][point]
    else:
        item = rules.get("default", {}).get(point, {})
    return item.get("lsl"), item.get("usl")


@dataclass(slots=True)
class MappingRule:
    equipment_id: str | None = None
    site_name: str | None = None
    config: str | None = None
    slot: str | None = None
    cell: str = "Unassigned"
    tester: str = "Unassigned"
    qpl: str = "Unassigned"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MappingRule:
        return cls(
            equipment_id=value.get("equipment_id") or None,
            site_name=value.get("site_name") or None,
            config=value.get("config") or None,
            slot=str(value["slot"]) if value.get("slot") is not None else None,
            cell=value.get("cell") or "Unassigned",
            tester=value.get("tester") or "Unassigned",
            qpl=value.get("qpl") or "Unassigned",
        )

    @property
    def specificity(self) -> int:
        return sum(
            value is not None
            for value in (self.equipment_id, self.site_name, self.config, self.slot)
        )

    def matches(self, event: dict[str, Any]) -> bool:
        checks = (
            (self.equipment_id, event.get("equipment_id")),
            (self.site_name, event.get("site_name")),
            (self.config, event.get("config")),
            (self.slot, event.get("slot")),
        )
        return all(expected is None or expected == actual for expected, actual in checks)


def resolve_mapping(event: dict[str, Any], rules: list[dict[str, Any]]) -> tuple[str, str, str]:
    candidates = [MappingRule.from_dict(item) for item in rules]
    matched = [rule for rule in candidates if rule.matches(event)]
    if not matched:
        return "Unassigned", "Unassigned", "Unassigned"
    selected = max(matched, key=lambda rule: rule.specificity)
    return selected.cell, selected.tester, selected.qpl
