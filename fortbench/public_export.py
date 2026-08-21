from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "fortbench-public-v1"
_ABSOLUTE_UNIX_PATH = re.compile(r"(?<![\w.])/(?:home|Users|Volumes|tmp|var|opt|srv|mnt)/[^\s`'\"]+")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\s`'\"]+")
_IP_ADDRESS = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _redact_text(value: str) -> str:
    value = _ABSOLUTE_UNIX_PATH.sub("[redacted-path]", value)
    value = _WINDOWS_PATH.sub("[redacted-path]", value)
    return _IP_ADDRESS.sub("[redacted-network-address]", value)


def _safe_json(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"public metadata contains unsupported value: {type(value).__name__}")


def _public_stage(stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": stage.get("stage"),
        "agent_ok": bool(stage.get("agent_ok")),
        "model_output": _redact_text(str(stage.get("agent_text") or "")),
        "acceptance_ok": bool(stage.get("acceptance_ok")),
    }


def _public_result(row: dict[str, Any]) -> dict[str, Any]:
    result = {
        "task_id": row.get("task_id"),
        "task_title": row.get("task_title"),
        "row_name": row.get("row_name"),
        "agent": row.get("agent"),
        "model_alias": row.get("model_alias"),
        "budget_tier": row.get("budget_tier"),
        "final_status": row.get("final_status"),
        "solved_stage": row.get("solved_stage"),
        "stages": [_public_stage(stage) for stage in row.get("stage_results", [])],
    }
    if row.get("excluded_from_score"):
        result["excluded_from_score"] = True
        result["exclusion_reason"] = _redact_text(str(row.get("exclusion_reason") or ""))
    return result


def build_public_export(
    raw_results: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_results, list) or not all(isinstance(row, dict) for row in raw_results):
        raise TypeError("results.json must contain a list of objects")
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": _safe_json(metadata or {}),
        "results": [_public_result(row) for row in raw_results],
    }


def export_public_results(results_path: Path, output_path: Path, metadata_path: Path | None = None) -> None:
    raw_results = json.loads(results_path.read_text())
    metadata = json.loads(metadata_path.read_text()) if metadata_path else None
    public = build_public_export(raw_results, metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n")
