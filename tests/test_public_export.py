from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fortbench.public_export import build_public_export, export_public_results


class PublicExportTest(unittest.TestCase):
    def test_allowlists_public_fields_and_drops_performance_and_host_data(self) -> None:
        raw = [{
            "task_id": "task-one",
            "task_title": "Repair one thing",
            "row_name": "model-a",
            "agent": "opencode",
            "model_alias": "llamacpp/model-a",
            "budget_tier": "fixed/default",
            "final_status": "solved",
            "solved_stage": 1,
            "runtime_seconds_total": 99.2,
            "local_model_switch_seconds": 4.1,
            "hostname": "private-host",
            "setup_results": [{"duration_seconds": 2.0}],
            "stage_results": [{
                "stage": 1,
                "agent_ok": True,
                "agent_text": "Changed /home/person/work/file.f90 via 10.0.0.8",
                "acceptance_ok": True,
                "agent_duration_seconds": 80,
                "agent_stdout_excerpt": "private log",
            }],
        }]

        public = build_public_export(raw, {
            "model": "model-a",
            "weight_file": "model-a-q4.gguf",
            "settings": {"temperature": 0.6},
        })

        encoded = json.dumps(public)
        self.assertEqual(public["schema_version"], "fortbench-public-v1")
        self.assertNotIn("runtime_seconds", encoded)
        self.assertNotIn("hostname", encoded)
        self.assertNotIn("duration_seconds", encoded)
        self.assertNotIn("private log", encoded)
        self.assertNotIn("/home/person", encoded)
        self.assertNotIn("10.0.0.8", encoded)
        self.assertIn("[redacted-path]", encoded)
        self.assertIn("[redacted-network-address]", encoded)
        self.assertEqual(public["metadata"]["weight_file"], "model-a-q4.gguf")

    def test_writes_a_stable_json_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.json"
            metadata = root / "metadata.json"
            output = root / "public.json"
            source.write_text(json.dumps([{"task_id": "one", "stage_results": []}]))
            metadata.write_text(json.dumps({"engine": "llama.cpp"}))

            export_public_results(source, output, metadata)

            data = json.loads(output.read_text())
            self.assertEqual(data["metadata"], {"engine": "llama.cpp"})
            self.assertEqual(data["results"][0]["task_id"], "one")

    def test_preserves_scoring_exclusion_without_private_fields(self) -> None:
        public = build_public_export(
            [
                {
                    "task_id": "invalid-task",
                    "excluded_from_score": True,
                    "exclusion_reason": "Base acceptance passed on /home/private/workspace",
                    "runtime_seconds_total": 2.0,
                }
            ]
        )

        self.assertTrue(public["results"][0]["excluded_from_score"])
        self.assertEqual(
            public["results"][0]["exclusion_reason"],
            "Base acceptance passed on [redacted-path]",
        )


if __name__ == "__main__":
    unittest.main()
