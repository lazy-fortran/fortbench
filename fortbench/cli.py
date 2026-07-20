from __future__ import annotations

import argparse
from pathlib import Path

from fortbench.core import check_task, run_suite
from fortbench.public_export import export_public_results


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

    export_parser = sub.add_parser("export-public", help="Create a hardware-free public results file")
    export_parser.add_argument("results", help="Private raw results.json")
    export_parser.add_argument("output", help="Public JSON file to create")
    export_parser.add_argument(
        "--metadata",
        help="Optional JSON containing model, weight, engine, and inference settings",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "run-suite":
        return run_suite(Path(args.suite), Path(args.output_dir), False, resume=args.resume)
    if args.command == "check-task":
        return check_task(Path(args.task), Path(args.output_dir))
    if args.command == "export-public":
        export_public_results(
            Path(args.results),
            Path(args.output),
            Path(args.metadata) if args.metadata else None,
        )
        return 0
    return 1
