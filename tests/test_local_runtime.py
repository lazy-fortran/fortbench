from __future__ import annotations

import json
import os
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fortbench.adapters import AgentResponse
from fortbench.core import (
    AcceptanceResult,
    archive_row_artifacts,
    assert_local_stage_healthy,
    assert_local_server_model,
    failure_result,
    local_model_env,
    local_models_url,
    local_profile_key,
    local_served_model_name,
    run_suite,
    run_task_row,
    stop_local_server,
    switch_local_model,
    write_suite_artifacts,
)


class LocalRuntimeTests(unittest.TestCase):
    def test_local_served_model_name_uses_row_override(self) -> None:
        row = {"adapter": "codex", "model": "Qwen3.5-4B", "local_served_model_name": "custom-name"}
        self.assertEqual(local_served_model_name(row), "custom-name")

    def test_local_served_model_name_uses_qwen_for_opencode(self) -> None:
        row = {"adapter": "opencode", "model": "ignored"}
        self.assertEqual(local_served_model_name(row), "qwen")

    def test_local_served_model_name_uses_model_for_codex(self) -> None:
        row = {"adapter": "codex", "model": "Qwen3.5-4B"}
        self.assertEqual(local_served_model_name(row), "qwen")

    def test_local_model_env_sets_llamacpp_contract(self) -> None:
        row = {"adapter": "codex", "model": "Qwen3.5-4B", "local_model_alias": "qwen3.5-4b"}
        env = local_model_env(row)
        self.assertEqual(env["LLAMACPP_MODEL_ALIAS"], "qwen3.5-4b")
        self.assertEqual(env["LLAMACPP_SERVED_MODEL_NAME"], "qwen")
        self.assertEqual(env["LLAMACPP_START_TIMEOUT"], "1800")
        self.assertEqual(env["LLAMACPP_SMOKE_TEST"], "false")
        self.assertEqual(env["LLAMACPP_EXTRA_FLAGS"], "-ctk q8_0 -ctv q8_0")

    def test_local_model_env_preserves_explicit_cache_quantization_flags(self) -> None:
        row = {"adapter": "codex", "model": "Qwen3.5-4B", "local_model_alias": "qwen3.5-4b"}
        with patch.dict("os.environ", {"LLAMACPP_EXTRA_FLAGS": "--foo 1 -ctk q4_0"}, clear=False):
            env = local_model_env(row)
        self.assertEqual(env["LLAMACPP_EXTRA_FLAGS"], "--foo 1 -ctk q4_0 -ctv q8_0")

    def test_local_profile_key_tracks_effective_runtime_profile(self) -> None:
        row = {
            "adapter": "opencode",
            "model": "ignored-by-opencode",
            "local_model_alias": "qwen3.5-4b",
            "local_instance": "fast",
        }
        self.assertEqual(local_profile_key(row), ("fast", "qwen3.5-4b", "qwen"))

    def test_local_models_url_tracks_instance(self) -> None:
        self.assertEqual(local_models_url({"local_instance": "fast"}), "http://127.0.0.1:8081/v1/models")
        self.assertEqual(local_models_url({"local_instance": "local"}), "http://127.0.0.1:8080/v1/models")

    @patch.dict(os.environ, {"FORTBENCH_ENDPOINT": "https://api.example/v1"})
    def test_local_models_url_expands_custom_endpoint(self) -> None:
        row = {"endpoint": "${FORTBENCH_ENDPOINT}"}
        self.assertEqual(local_models_url(row), "https://api.example/v1/models")

    def test_assert_local_stage_healthy_allows_foreign_finish_records(self) -> None:
        response = AgentResponse(
            ok=False,
            command=["opencode"],
            returncode=124,
            stdout="",
            stderr="",
            duration_seconds=1.0,
            text="",
            error="timed out after 1 seconds",
            protocol_summary={
                "request_count": 1,
                "response_finish_count": 0,
                "first_request_delay_seconds": 0.1,
                "first_request_method": "POST",
                "first_request_path": "/v1/chat/completions",
                "total_upstream_seconds": 0.0,
                "log_write_errors": 0,
                "drained_cleanly": True,
                "active_requests_at_stop": 0,
                "foreign_record_count": 1,
                "foreign_request_start_count": 0,
                "foreign_finish_count": 1,
            },
        )

        assert_local_stage_healthy({"name": "opencode-local-test", "provider_class": "local"}, 2, response)

    @patch("fortbench.core.urllib.request.urlopen")
    def test_assert_local_server_model_uses_served_name(self, mock_urlopen: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"data":[{"id":"qwen"}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        assert_local_server_model(
            {
                "name": "codex-local-qwen3.5-4b",
                "adapter": "codex",
                "model": "Qwen3.5-4B",
                "local_instance": "local",
            }
        )

        mock_urlopen.assert_called_once_with("http://127.0.0.1:8080/v1/models", timeout=5)

    @patch("fortbench.core.urllib.request.urlopen")
    def test_assert_local_server_model_raises_on_mismatch(self, mock_urlopen: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"data":[{"id":"wrong-model"}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with self.assertRaisesRegex(RuntimeError, "served model mismatch"):
            assert_local_server_model(
                {
                    "name": "codex-local-qwen3.5-4b",
                    "adapter": "codex",
                    "model": "Qwen3.5-4B",
                    "local_instance": "local",
                }
            )

    @patch("fortbench.core.time.sleep")
    @patch("fortbench.core.subprocess.run")
    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {"FORTBENCH_SCRIPTS_DIR": "/tmp/fortbench-runtime"})
    def test_switch_local_model_uses_llamacpp_scripts(
        self,
        mock_urlopen: MagicMock,
        mock_run: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(stdout="")
        mock_urlopen.return_value = MagicMock()
        row = {
            "adapter": "codex",
            "model": "Qwen3.5-4B",
            "local_model_alias": "qwen3.5-4b",
            "local_instance": "fast",
        }

        switch_seconds = switch_local_model(row)

        self.assertGreaterEqual(switch_seconds, 0.0)
        stop_call = mock_run.call_args_list[0]
        start_call = mock_run.call_args_list[1]
        self.assertIn("server_stop_llamacpp.sh", stop_call.args[0][1])
        self.assertEqual(stop_call.args[0][2], "all")
        self.assertIn("server_start_llamacpp.sh", start_call.args[0][1])
        self.assertEqual(start_call.args[0][2], "fast")
        self.assertEqual(start_call.kwargs["env"]["LLAMACPP_MODEL_ALIAS"], "qwen3.5-4b")
        self.assertEqual(start_call.kwargs["env"]["LLAMACPP_SERVED_MODEL_NAME"], "qwen")
        mock_urlopen.assert_called_once_with("http://127.0.0.1:8081/v1/models", timeout=5)
        mock_sleep.assert_called()

    def test_archive_row_artifacts_skips_private_agent_runtime_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "row"
            stage_dir = run_dir / "stages" / "stage-1"
            workspace_dir = run_dir / "workspace"
            config_dir = run_dir / ".codex-benchmark"
            volatile_dir = config_dir / "tmp"
            home_dir = run_dir / ".codex-home"
            cloud_dir = run_dir / ".codex-cloud"

            stage_dir.mkdir(parents=True)
            workspace_dir.mkdir(parents=True)
            volatile_dir.mkdir(parents=True)
            home_dir.mkdir(parents=True)
            cloud_dir.mkdir(parents=True)

            (stage_dir / "stdout.log").write_text("stage output\n")
            (workspace_dir / "README.md").write_text("workspace\n")
            (config_dir / "config.toml").write_text("config\n")
            (volatile_dir / "arg0").write_text("secret\n")
            (home_dir / "state.json").write_text("home\n")
            (cloud_dir / "config.toml").write_text("cloud config\n")

            original_add = tarfile.TarFile.add

            def checked_add(self, name, arcname=None, recursive=True, *, filter=None):
                if arcname and str(arcname).startswith(".codex-benchmark/tmp"):
                    raise AssertionError("volatile codex tmp should not be archived")
                if arcname and str(arcname).startswith(".codex-home"):
                    raise AssertionError("codex home should not be archived")
                if arcname and str(arcname).startswith(".codex-cloud"):
                    raise AssertionError("codex cloud home should not be archived")
                return original_add(self, name, arcname=arcname, recursive=recursive, filter=filter)

            def fake_zstd(args, check, capture_output, text):
                src = Path(args[-1])
                src.rename(src.with_suffix(".tar.zst"))
                return MagicMock(stdout="", stderr="", returncode=0)

            with patch("fortbench.core.subprocess.run", side_effect=fake_zstd), patch.object(
                tarfile.TarFile, "add", new=checked_add
            ):
                archive_name = archive_row_artifacts(run_dir)

            archive_path = run_dir / archive_name
            self.assertTrue(archive_path.exists())
            with tarfile.open(archive_path) as tar:
                names = tar.getnames()
            self.assertIn("stages/stage-1/stdout.log", names)
            self.assertIn("workspace/README.md", names)
            self.assertIn(".codex-benchmark/config.toml", names)
            self.assertNotIn(".codex-benchmark/tmp", names)
            self.assertNotIn(".codex-benchmark/tmp/arg0", names)
            self.assertNotIn(".codex-home", names)
            self.assertNotIn(".codex-cloud", names)

    def test_archive_row_artifacts_repairs_permissions_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "row"
            workspace_dir = run_dir / "workspace"
            workspace_dir.mkdir(parents=True)
            unreadable_path = workspace_dir / "Oops.rej"
            unreadable_path.write_text("reject\n")

            original_add = tarfile.TarFile.add
            raised = False
            chmod_calls = []

            def flaky_add(self, name, arcname=None, recursive=True, *, filter=None):
                nonlocal raised
                if Path(name) == unreadable_path and not raised:
                    raised = True
                    raise PermissionError("permission denied")
                return original_add(self, name, arcname=arcname, recursive=recursive, filter=filter)

            def fake_run(args, check, capture_output, text, timeout=None):
                if args[:3] == ["sudo", "-n", "chmod"]:
                    chmod_calls.append(args)
                    return MagicMock(stdout="", stderr="", returncode=0)
                if args[0] == "zstd":
                    src = Path(args[-1])
                    src.rename(src.with_suffix(".tar.zst"))
                    return MagicMock(stdout="", stderr="", returncode=0)
                raise AssertionError(f"unexpected subprocess.run args: {args}")

            with patch("fortbench.core.subprocess.run", side_effect=fake_run), patch.object(
                tarfile.TarFile, "add", new=flaky_add
            ):
                archive_name = archive_row_artifacts(run_dir)

            self.assertEqual(len(chmod_calls), 1)
            self.assertEqual(chmod_calls[0][-1], str(unreadable_path))
            archive_path = run_dir / archive_name
            self.assertTrue(archive_path.exists())
            with tarfile.open(archive_path) as tar:
                names = tar.getnames()
            self.assertIn("workspace/Oops.rej", names)

    def test_failure_result_marks_local_backend(self) -> None:
        task = {"id": "task-1", "title": "Task"}
        row = {"name": "codex-local-qwen3.5-4b", "adapter": "codex", "provider_class": "local"}

        result = failure_result(task, row, RuntimeError("boom"))

        self.assertEqual(result["final_status"], "error")
        self.assertEqual(result["local_backend"], "llamacpp")

    def test_write_suite_artifacts_excludes_invalid_tasks_from_reports(self) -> None:
        suite = {
            "name": "suite",
            "tasks": ["task-one.yaml", "task-two.yaml"],
            "excluded_tasks": {"task-two": "invalid oracle"},
        }
        rows = [
            {
                "task_id": "task-one",
                "row_name": "model-a",
                "budget_tier": "fixed/default",
                "final_status": "solved",
                "solved_stage": 1,
                "runtime_seconds_total": 1.0,
            },
            {
                "task_id": "task-two",
                "row_name": "model-a",
                "budget_tier": "fixed/default",
                "final_status": "error",
                "solved_stage": None,
                "runtime_seconds_total": 2.0,
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            write_suite_artifacts(output_dir, suite, rows)

            report_rows = json.loads((output_dir / "results.json").read_text())
            csv_text = (output_dir / "summary.csv").read_text()
            markdown_text = (output_dir / "summary.md").read_text()

        self.assertEqual(len(report_rows), 2)
        self.assertTrue(report_rows[1]["excluded_from_score"])
        self.assertEqual(report_rows[1]["exclusion_reason"], "invalid oracle")
        self.assertIn("task-one", csv_text)
        self.assertNotIn("task-two", csv_text)
        self.assertIn("Scored tasks: `1`", markdown_text)
        self.assertIn("Excluded from scoring: `task-two`: invalid oracle", markdown_text)

    @patch("fortbench.core.run_acceptance")
    @patch("fortbench.core.run_setup")
    @patch("fortbench.core.clone_workspace")
    @patch("fortbench.core.build_adapter")
    def test_run_task_row_rejects_zero_request_local_stage(
        self,
        mock_build_adapter: MagicMock,
        mock_clone_workspace: MagicMock,
        mock_run_setup: MagicMock,
        mock_run_acceptance: MagicMock,
    ) -> None:
        response = AgentResponse(
            ok=False,
            command=["codex"],
            returncode=124,
            stdout="",
            stderr="",
            duration_seconds=1.0,
            text="",
            error="timed out after 1 seconds",
            protocol_summary={
                "request_count": 0,
                "first_request_delay_seconds": None,
                "first_request_method": None,
                "first_request_path": None,
                "total_upstream_seconds": 0.0,
                "log_write_errors": 0,
                "drained_cleanly": True,
                "active_requests_at_stop": 0,
            },
        )
        mock_build_adapter.return_value.stage.return_value = response
        mock_run_setup.return_value = []
        mock_run_acceptance.side_effect = [
            AcceptanceResult(ok=False, command_results=[]),
        ]

        task = {
            "id": "task-1",
            "title": "Task 1",
            "issue_url": "https://example.com/issues/1",
            "issue_body": "Fix the bug.",
            "_task_dir": "/tmp/task-1",
        }
        row = {
            "name": "codex-local-qwen3.5-4b",
            "adapter": "codex",
            "provider_class": "local",
            "model": "Qwen3.5-4B",
            "local_model_alias": "qwen3.5-4b",
            "local_instance": "local",
        }

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "made zero backend requests"):
                run_task_row(task, row, Path(tmp), local_model_switch_seconds=0.0)

    @patch("fortbench.core.stop_proxy")
    @patch("fortbench.core.start_proxy")
    @patch("fortbench.core.stop_local_server")
    @patch("fortbench.core.prepare_proxy_root")
    @patch("fortbench.core.write_suite_artifacts")
    @patch("fortbench.core.run_task_row")
    @patch("fortbench.core.assert_local_server_model")
    @patch("fortbench.core.switch_local_model")
    @patch("fortbench.core.load_suite")
    def test_run_suite_switches_local_backend_only_when_profile_changes(
        self,
        mock_load_suite: MagicMock,
        mock_switch_local_model: MagicMock,
        mock_assert_local_server_model: MagicMock,
        mock_run_task_row: MagicMock,
        mock_write_suite_artifacts: MagicMock,
        mock_prepare_proxy_root: MagicMock,
        mock_stop_local_server: MagicMock,
        mock_start_proxy: MagicMock,
        mock_stop_proxy: MagicMock,
    ) -> None:
        tasks = [
            {"id": "task-1", "title": "Task 1", "_task_dir": "/tmp/task-1"},
            {"id": "task-2", "title": "Task 2", "_task_dir": "/tmp/task-2"},
        ]
        suite = {
            "rows": [
                {
                    "name": "codex-local-qwen3.5-4b",
                    "adapter": "codex",
                    "provider_class": "local",
                    "model": "Qwen3.5-4B",
                    "local_model_alias": "qwen3.5-4b",
                    "local_instance": "local",
                },
                {
                    "name": "opencode-qwen3.5-4b-q8",
                    "adapter": "opencode",
                    "provider_class": "local",
                    "model": "llamacpp/qwen",
                    "local_model_alias": "qwen3.5-4b",
                    "local_instance": "local",
                },
            ],
        }
        mock_load_suite.return_value = (suite, tasks)
        mock_switch_local_model.return_value = 12.34
        mock_run_task_row.side_effect = lambda task, row, output_dir, local_model_switch_seconds=0.0: {
            "task_id": task["id"],
            "task_title": task["title"],
            "row_name": row["name"],
            "agent": row["adapter"],
            "provider_class": row["provider_class"],
            "local_model_alias": row["local_model_alias"],
            "local_backend": "llamacpp",
            "final_status": "failed",
            "runtime_seconds_total": 1.0,
            "local_model_switch_seconds": local_model_switch_seconds,
            "stage_results": [],
            "judges": {},
        }

        with patch("fortbench.core.load_existing_results", return_value=[]), patch("fortbench.core.proxy_root", return_value=Path("/tmp/out/.litellm-proxy")):
            rc = run_suite(Path("/tmp/suite.yaml"), Path("/tmp/out"), continue_on_error=True, resume=False)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_switch_local_model.call_count, 1)
        self.assertEqual([call.args[0]["name"] for call in mock_switch_local_model.call_args_list], ["codex-local-qwen3.5-4b"])
        self.assertEqual(
            [call.kwargs["local_model_switch_seconds"] for call in mock_run_task_row.call_args_list],
            [12.34, 0.0, 0.0, 0.0],
        )
        mock_prepare_proxy_root.assert_called_once_with(Path("/tmp/out/.litellm-proxy"))
        self.assertEqual(mock_start_proxy.call_count, 2)
        self.assertGreaterEqual(mock_stop_proxy.call_count, 3)
        mock_stop_local_server.assert_called_once()

    @patch("fortbench.core.stop_proxy")
    @patch("fortbench.core.start_proxy")
    @patch("fortbench.core.stop_local_server")
    @patch("fortbench.core.prepare_proxy_root")
    @patch("fortbench.core.write_suite_artifacts")
    @patch("fortbench.core.run_task_row")
    @patch("fortbench.core.assert_local_server_model")
    @patch("fortbench.core.switch_local_model")
    @patch("fortbench.core.load_suite")
    def test_run_suite_resume_skips_completed_rows(
        self,
        mock_load_suite: MagicMock,
        mock_switch_local_model: MagicMock,
        mock_assert_local_server_model: MagicMock,
        mock_run_task_row: MagicMock,
        mock_write_suite_artifacts: MagicMock,
        mock_prepare_proxy_root: MagicMock,
        mock_stop_local_server: MagicMock,
        mock_start_proxy: MagicMock,
        mock_stop_proxy: MagicMock,
    ) -> None:
        tasks = [
            {"id": "task-1", "title": "Task 1", "_task_dir": "/tmp/task-1"},
            {"id": "task-2", "title": "Task 2", "_task_dir": "/tmp/task-2"},
        ]
        suite = {
            "rows": [
                {
                    "name": "codex-local-qwen3.5-4b",
                    "adapter": "codex",
                    "provider_class": "local",
                    "model": "Qwen3.5-4B",
                    "local_model_alias": "qwen3.5-4b",
                    "local_instance": "local",
                },
                {
                    "name": "codex-gpt-5.4-mini-default",
                    "adapter": "codex",
                    "provider_class": "cloud",
                    "model": "gpt-5.4-mini",
                },
            ],
        }
        mock_load_suite.return_value = (suite, tasks)
        mock_switch_local_model.return_value = 12.34

        def side_effect(task, row, output_dir, local_model_switch_seconds=0.0):
            return {
                "task_id": task["id"],
                "task_title": task["title"],
                "row_name": row["name"],
                "agent": row["adapter"],
                "provider_class": row["provider_class"],
                "local_model_alias": row.get("local_model_alias", ""),
                "local_backend": "llamacpp" if row["provider_class"] == "local" else "",
                "final_status": "failed",
                "runtime_seconds_total": 1.0,
                "local_model_switch_seconds": local_model_switch_seconds,
                "stage_results": [],
                "judges": {},
            }

        mock_run_task_row.side_effect = side_effect
        existing_rows = [
            {
                "task_id": "task-1",
                "task_title": "Task 1",
                "row_name": "codex-local-qwen3.5-4b",
                "agent": "codex",
                "provider_class": "local",
                "local_model_alias": "qwen3.5-4b",
                "local_backend": "llamacpp",
                "final_status": "failed",
                "runtime_seconds_total": 1.0,
                "stage_results": [],
                "judges": {},
            },
            {
                "task_id": "task-1",
                "task_title": "Task 1",
                "row_name": "codex-gpt-5.4-mini-default",
                "agent": "codex",
                "provider_class": "cloud",
                "local_model_alias": "",
                "local_backend": "",
                "final_status": "solved",
                "runtime_seconds_total": 1.0,
                "stage_results": [{"stage": 1, "acceptance_ok": True}],
                "judges": {},
            },
        ]

        with patch("fortbench.core.load_existing_results", return_value=existing_rows), patch(
            "fortbench.core.proxy_root", return_value=Path("/tmp/out/.litellm-proxy")
        ):
            rc = run_suite(Path("/tmp/suite.yaml"), Path("/tmp/out"), continue_on_error=False, resume=True)

        self.assertEqual(rc, 0)
        self.assertEqual(
            [(call.args[0]["id"], call.args[1]["name"]) for call in mock_run_task_row.call_args_list],
            [
                ("task-2", "codex-gpt-5.4-mini-default"),
                ("task-2", "codex-local-qwen3.5-4b"),
            ],
        )
        mock_prepare_proxy_root.assert_called_once_with(Path("/tmp/out/.litellm-proxy"))
        mock_switch_local_model.assert_called_once()
        mock_start_proxy.assert_called_once()
        mock_stop_local_server.assert_called_once()

    def test_load_existing_results_normalizes_completed_rows_for_resume(self) -> None:
        from fortbench.core import load_existing_results

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "results.json").write_text(
                """
[
  {
    "task_id": "task-1",
    "row_name": "codex-gpt-5.4-mini-default",
    "stage_results": [{"stage": 1, "acceptance_ok": true}]
  },
  {
    "task_id": "task-2",
    "row_name": "codex-local-qwen3.5-4b",
    "stage_results": [{"stage": 1, "acceptance_ok": false}]
  }
]
""".strip()
            )

            rows = load_existing_results(output_dir)

            self.assertEqual(rows[0]["solved_stage"], 1)
            self.assertEqual(rows[0]["final_status"], "solved")
            self.assertIsNone(rows[1]["solved_stage"])
            self.assertEqual(rows[1]["final_status"], "failed")

    @patch("fortbench.core.stop_proxy")
    @patch("fortbench.core.start_proxy")
    @patch("fortbench.core.stop_local_server")
    @patch("fortbench.core.prepare_proxy_root")
    @patch("fortbench.core.write_suite_artifacts")
    @patch("fortbench.core.run_task_row")
    @patch("fortbench.core.assert_local_server_model")
    @patch("fortbench.core.switch_local_model")
    @patch("fortbench.core.load_suite")
    def test_run_suite_stops_on_real_error_even_with_continue_on_error(
        self,
        mock_load_suite: MagicMock,
        mock_switch_local_model: MagicMock,
        mock_assert_local_server_model: MagicMock,
        mock_run_task_row: MagicMock,
        mock_write_suite_artifacts: MagicMock,
        mock_prepare_proxy_root: MagicMock,
        mock_stop_local_server: MagicMock,
        mock_start_proxy: MagicMock,
        mock_stop_proxy: MagicMock,
    ) -> None:
        tasks = [
            {"id": "task-1", "title": "Task 1", "_task_dir": "/tmp/task-1"},
            {"id": "task-2", "title": "Task 2", "_task_dir": "/tmp/task-2"},
            {"id": "task-3", "title": "Task 3", "_task_dir": "/tmp/task-3"},
        ]
        suite = {
            "rows": [
                {
                    "name": "codex-local-qwen3.5-4b",
                    "adapter": "codex",
                    "provider_class": "local",
                    "model": "Qwen3.5-4B",
                    "local_model_alias": "qwen3.5-4b",
                    "local_instance": "local",
                }
            ],
        }
        mock_load_suite.return_value = (suite, tasks)
        mock_switch_local_model.return_value = 12.34

        def side_effect(task, row, output_dir, local_model_switch_seconds=0.0):
            if task["id"] == "task-2":
                raise RuntimeError("backend crashed")
            return {
                "task_id": task["id"],
                "task_title": task["title"],
                "row_name": row["name"],
                "agent": row["adapter"],
                "provider_class": row["provider_class"],
                "local_model_alias": row["local_model_alias"],
                "local_backend": "llamacpp",
                "final_status": "failed",
                "runtime_seconds_total": 1.0,
                "local_model_switch_seconds": local_model_switch_seconds,
                "stage_results": [],
                "judges": {},
            }

        mock_run_task_row.side_effect = side_effect

        with patch("fortbench.core.load_existing_results", return_value=[]), patch("fortbench.core.proxy_root", return_value=Path("/tmp/out/.litellm-proxy")):
            rc = run_suite(Path("/tmp/suite.yaml"), Path("/tmp/out"), continue_on_error=True, resume=False)

        self.assertEqual(rc, 1)
        self.assertEqual([call.args[0]["id"] for call in mock_run_task_row.call_args_list], ["task-1", "task-2"])
        mock_prepare_proxy_root.assert_called_once_with(Path("/tmp/out/.litellm-proxy"))
        mock_stop_local_server.assert_called_once()
        self.assertGreaterEqual(mock_stop_proxy.call_count, 2)

    @patch("fortbench.core.subprocess.run")
    def test_stop_local_server_uses_llamacpp_stop_script(self, mock_run: MagicMock) -> None:
        stop_local_server()

        stop_call = mock_run.call_args
        self.assertIn("server_stop_llamacpp.sh", stop_call.args[0][1])
        self.assertEqual(stop_call.args[0][2], "all")


if __name__ == "__main__":
    unittest.main()
