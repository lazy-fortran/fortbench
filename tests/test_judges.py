from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from fortbench.judges import build_code_evidence, judge_prompt, select_stage_for_judging


class JudgesTest(unittest.TestCase):
    def test_build_code_evidence_reports_patch_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "code.f90").write_text("print *, 'hello'\n")
            subprocess.run(["git", "add", "code.f90"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            (repo / "code.f90").write_text("print *, 'hello world'\n")
            (repo / "notes.txt").write_text("extra\n")

            evidence = build_code_evidence(repo)

            self.assertEqual(evidence["changed_files"], ["code.f90"])
            self.assertIn("M code.f90", evidence["git_status_short"])
            self.assertIn("?? notes.txt", evidence["git_status_short"])
            self.assertIn("code.f90", evidence["diff_stat"])
            self.assertIn("hello world", evidence["patch_excerpt"])

    def test_select_stage_for_judging_prefers_solved_stage(self) -> None:
        row = {
            "solved_stage": 2,
            "stage_results": [
                {"stage": 1, "acceptance_ok": False},
                {"stage": 2, "acceptance_ok": True},
                {"stage": 3, "acceptance_ok": False},
            ],
        }
        self.assertEqual(select_stage_for_judging(row)["stage"], 2)
        self.assertEqual(select_stage_for_judging({"stage_results": row["stage_results"]})["stage"], 3)

    def test_judge_prompt_mentions_code_quality_evidence(self) -> None:
        prompt = judge_prompt(
            {"id": "task", "issue_url": "https://example.com", "title": "Fix thing"},
            {"stage": 1, "agent_ok": True, "agent_error": None, "agent_duration_seconds": 1.0, "agent_text": "done", "setup_results": [], "acceptance_ok": True},
            {"ok": True, "command_results": []},
            code_evidence={"changed_files": ["code.f90"], "git_status_short": "M code.f90"},
        )
        self.assertIn("Rubric version: code_quality_v1", prompt)
        self.assertIn("Code evidence from archived workspace", prompt)
        self.assertIn("code.f90", prompt)


if __name__ == "__main__":
    unittest.main()
