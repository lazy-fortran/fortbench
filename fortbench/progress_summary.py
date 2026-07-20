from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import yaml


def load_results(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return data["rows"]
    raise TypeError(f"unsupported results format in {path}")


def load_suite(path: Path) -> tuple[list[str], list[dict]]:
    suite = yaml.safe_load(path.read_text())
    repo_root = path.parent.parent
    task_ids = [yaml.safe_load((repo_root / task_path).read_text())["id"] for task_path in suite["tasks"]]
    return task_ids, suite["rows"]


def format_duration(total_seconds: float | int | None) -> str:
    if total_seconds is None:
        return "-"
    total = int(round(float(total_seconds)))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours}:{minutes:02d}:{seconds:02d}"
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def active_tasks_by_row(output_dir: Path, completed_keys: set[tuple[str, str]]) -> dict[str, list[str]]:
    active: dict[str, list[str]] = defaultdict(list)
    artifacts_dir = output_dir / "artifacts"
    if not artifacts_dir.exists():
        return {}
    for artifact in sorted(artifacts_dir.iterdir()):
        if not artifact.is_dir() or "__" not in artifact.name:
            continue
        task_id, row_name = artifact.name.split("__", 1)
        key = (task_id, row_name)
        if key in completed_keys:
            continue
        active[row_name].append(task_id)
    return dict(active)


def build_progress_rows(suite_path: Path, output_dir: Path) -> tuple[list[dict], dict[str, list[str]]]:
    task_ids, suite_rows = load_suite(suite_path)
    total_tasks = len(task_ids)
    results_path = output_dir / "results.json"
    results = load_results(results_path) if results_path.exists() else []
    rows_by_name: dict[str, list[dict]] = defaultdict(list)
    completed_keys: set[tuple[str, str]] = set()
    for row in results:
        row_name = row.get("row_name")
        task_id = row.get("task_id")
        if row_name is not None:
            rows_by_name[row_name].append(row)
        if row_name is not None and task_id is not None:
            completed_keys.add((task_id, row_name))
    artifact_active = active_tasks_by_row(output_dir, completed_keys)
    local_active_row: str | None = None
    active: dict[str, list[str]] = {}
    for row in suite_rows:
        if row.get("provider_class", "local") != "local":
            continue
        row_name = row["name"]
        if len(rows_by_name.get(row_name, [])) < total_tasks:
            local_active_row = row_name
            break
    if local_active_row is not None:
        completed_tasks = {task_id for task_id, row_name in completed_keys if row_name == local_active_row}
        next_task = next((task_id for task_id in task_ids if task_id not in completed_tasks), None)
        if next_task is not None:
            active[local_active_row] = [next_task]
    for row in suite_rows:
        row_name = row["name"]
        if row.get("provider_class", "local") == "local":
            continue
        if artifact_active.get(row_name):
            active[row_name] = artifact_active[row_name]

    summary_rows = []
    for row in suite_rows:
        row_name = row["name"]
        items = rows_by_name.get(row_name, [])
        solved = sum(1 for item in items if item.get("final_status") == "solved")
        total_runtime = sum(float(item.get("runtime_seconds_total") or 0.0) for item in items)
        done = len(items)
        if done == total_tasks:
            status = "done"
        elif active.get(row_name):
            status = "active"
        elif done > 0:
            status = "partial"
        else:
            status = "pending"
        summary_rows.append(
            {
                "row_name": row_name,
                "done": done,
                "total": total_tasks,
                "solved": solved,
                "solve_rate_pct": round((solved / done) * 100, 1) if done else None,
                "avg_runtime_seconds": (total_runtime / done) if done else None,
                "total_runtime_seconds": total_runtime if done else None,
                "status": status,
            }
        )
    return summary_rows, active


def build_progress_rows_multi(run_specs: list[tuple[Path, Path]]) -> tuple[list[dict], dict[str, list[str]]]:
    summary_rows: list[dict] = []
    active: dict[str, list[str]] = {}
    for suite_path, output_dir in run_specs:
        rows, active_rows = build_progress_rows(suite_path, output_dir)
        summary_rows.extend(rows)
        active.update(active_rows)
    return summary_rows, active


def render_markdown(summary_rows: list[dict], active: dict[str, list[str]]) -> str:
    lines = [
        "| Model | Done | Good | Fast | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for row in summary_rows:
        good = "-" if row["solve_rate_pct"] is None else f"{row['solved']}/{row['done']} ({row['solve_rate_pct']}%)"
        fast = "-"
        if row["avg_runtime_seconds"] is not None and row["total_runtime_seconds"] is not None:
            fast = f"avg {format_duration(row['avg_runtime_seconds'])}, total {format_duration(row['total_runtime_seconds'])}"
        lines.append(
            f"| `{row['row_name']}` | `{row['done']}/{row['total']}` | {good} | {fast} | {row['status']} |"
        )

    active_lines = []
    for row_name, task_ids in active.items():
        task_list = ", ".join(f"`{task_id}`" for task_id in task_ids)
        active_lines.append(f"- `{row_name}`: {task_list}")
    if active_lines:
        lines.extend(["", "Active tasks:"])
        lines.extend(active_lines)
    return "\n".join(lines) + "\n"
