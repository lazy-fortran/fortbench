from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fortbench.progress_summary import build_progress_rows, build_progress_rows_multi, render_markdown


class ProgressSummaryTest(unittest.TestCase):
    def test_build_progress_rows_tracks_done_solved_and_active_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_dir = root / "tasks" / "corpus-20-v1"
            suites_dir = root / "suites"
            output_dir = root / "run"
            output_dir.mkdir()
            (output_dir / "artifacts").mkdir()
            suites_dir.mkdir()

            task_ids = ["task-one", "task-two"]
            for task_id in task_ids:
                task_dir = tasks_dir / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "task.yaml").write_text(f"id: {task_id}\n")

            suite_path = suites_dir / "suite.yaml"
            suite_path.write_text(
                "\n".join(
                    [
                        "tasks:",
                        "  - tasks/corpus-20-v1/task-one/task.yaml",
                        "  - tasks/corpus-20-v1/task-two/task.yaml",
                        "rows:",
                        "  - {name: model-a}",
                        "  - {name: model-b}",
                    ]
                )
                + "\n"
            )

            (output_dir / "results.json").write_text(
                json.dumps(
                    [
                        {
                            "task_id": "task-one",
                            "row_name": "model-a",
                            "final_status": "solved",
                            "runtime_seconds_total": 12.0,
                        }
                    ]
                )
                + "\n"
            )
            (output_dir / "artifacts" / "task-two__model-a").mkdir()
            (output_dir / "artifacts" / "task-one__model-b").mkdir()

            summary_rows, active = build_progress_rows(suite_path, output_dir)

            self.assertEqual(
                summary_rows,
                [
                    {
                        "row_name": "model-a",
                        "done": 1,
                        "total": 2,
                        "solved": 1,
                        "solve_rate_pct": 100.0,
                        "avg_runtime_seconds": 12.0,
                        "total_runtime_seconds": 12.0,
                        "status": "active",
                    },
                    {
                        "row_name": "model-b",
                        "done": 0,
                        "total": 2,
                        "solved": 0,
                        "solve_rate_pct": None,
                        "avg_runtime_seconds": None,
                        "total_runtime_seconds": None,
                        "status": "pending",
                    },
                ],
            )
            self.assertEqual(active, {"model-a": ["task-two"]})

    def test_render_markdown_formats_summary(self) -> None:
        text = render_markdown(
            [
                {
                    "row_name": "model-a",
                    "done": 2,
                    "total": 4,
                    "solved": 1,
                    "solve_rate_pct": 50.0,
                    "avg_runtime_seconds": 90.0,
                    "total_runtime_seconds": 180.0,
                    "status": "active",
                }
            ],
            {"model-a": ["task-three"]},
        )

        self.assertIn("| `model-a` | `2/4` | 1/2 (50.0%) | avg 0:01:30, total 0:03:00 | active |", text)
        self.assertIn("- `model-a`: `task-three`", text)

    def test_build_progress_rows_multi_merges_multiple_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_dir = root / "tasks" / "corpus-20-v1"
            suites_dir = root / "suites"
            suites_dir.mkdir()
            for task_id in ["task-one", "task-two"]:
                task_dir = tasks_dir / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "task.yaml").write_text(f"id: {task_id}\n")

            suite_a = suites_dir / "suite-a.yaml"
            suite_a.write_text(
                "tasks:\n"
                "  - tasks/corpus-20-v1/task-one/task.yaml\n"
                "  - tasks/corpus-20-v1/task-two/task.yaml\n"
                "rows:\n"
                "  - {name: local-a}\n"
            )
            suite_b = suites_dir / "suite-b.yaml"
            suite_b.write_text(
                "tasks:\n"
                "  - tasks/corpus-20-v1/task-one/task.yaml\n"
                "  - tasks/corpus-20-v1/task-two/task.yaml\n"
                "rows:\n"
                "  - {name: cloud-b, provider_class: cloud}\n"
            )

            run_a = root / "run-a"
            run_b = root / "run-b"
            (run_a / "artifacts").mkdir(parents=True)
            (run_b / "artifacts").mkdir(parents=True)
            (run_a / "results.json").write_text(
                json.dumps([{"task_id": "task-one", "row_name": "local-a", "final_status": "solved", "runtime_seconds_total": 10.0}]) + "\n"
            )
            (run_b / "results.json").write_text(
                json.dumps([{"task_id": "task-one", "row_name": "cloud-b", "final_status": "failed", "runtime_seconds_total": 20.0}]) + "\n"
            )
            (run_a / "artifacts" / "task-two__local-a").mkdir()
            (run_b / "artifacts" / "task-two__cloud-b").mkdir()

            summary_rows, active = build_progress_rows_multi([(suite_a, run_a), (suite_b, run_b)])

            self.assertEqual([row["row_name"] for row in summary_rows], ["local-a", "cloud-b"])
            self.assertEqual(active, {"local-a": ["task-two"], "cloud-b": ["task-two"]})


if __name__ == "__main__":
    unittest.main()
