from __future__ import annotations

import argparse
from pathlib import Path

from fortbench.core import check_task, run_suite


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fortbench")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run-suite", help="Run a benchmark suite")
    run_parser.add_argument("suite", help="Path to suite YAML")
    run_parser.add_argument(
        "--output-dir",
        default="reports/latest",
        help="Directory for generated reports and per-run JSON",
    )
    run_parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Deprecated and ignored. Suite runs now stop on real errors.",
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted suite run from existing results.json in the output directory",
    )

    check_parser = sub.add_parser("check-task", help="Verify a task oracle on base and fixed commits")
    check_parser.add_argument("task", help="Path to task YAML")
    check_parser.add_argument(
        "--output-dir",
        default="reports/task-check",
        help="Directory for oracle validation artifacts",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "run-suite":
        return run_suite(Path(args.suite), Path(args.output_dir), False, resume=args.resume)
    if args.command == "check-task":
        return check_task(Path(args.task), Path(args.output_dir))
    return 1
