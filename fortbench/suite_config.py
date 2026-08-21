from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def excluded_task_reasons(suite: Mapping[str, Any]) -> dict[str, str]:
    raw = suite.get("excluded_tasks", {})
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return {str(task_id): str(reason) for task_id, reason in raw.items()}
    if isinstance(raw, list):
        reasons: dict[str, str] = {}
        for item in raw:
            if isinstance(item, str):
                reasons[item] = ""
            elif isinstance(item, Mapping) and "id" in item:
                reasons[str(item["id"])] = str(item.get("reason", ""))
            else:
                raise TypeError("excluded_tasks list entries must be task IDs or mappings with an id")
        return reasons
    raise TypeError("excluded_tasks must be a mapping or list")


def excluded_task_ids(suite: Mapping[str, Any]) -> set[str]:
    return set(excluded_task_reasons(suite))
