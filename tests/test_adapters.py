from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fortbench.adapters import (
    AgentResponse,
    ClaudeCodeAdapter,
    CodexAdapter,
    OpenCodeAdapter,
    _codex_command,
    _codex_reasoning_effort,
    _current_user_name,
    _extract_text,
    _local_benchmark_user,
    _local_sampling_options,
    _opencode_variant,
    _run_command,
    _sudo_local_command,
    _collect_claude_cli_protocol,
    _write_codex_benchmark_config,
    _write_codex_cloud_config,
    _write_opencode_benchmark_config,
)


class AdapterConfigTests(unittest.TestCase):
    def test_codex_benchmark_config_is_isolated_from_user_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            env = _write_codex_benchmark_config(
                root / ".codex-benchmark",
                workspace,
                {"model": "Qwen3.5-2B", "provider_class": "local"},
                home_dir=root / ".codex-home",
            )

            config_path = Path(env["CODEX_CONFIG_PATH"])
            catalog_path = config_path.parent / "local-models.json"
            config_text = config_path.read_text()
            catalog = json.loads(catalog_path.read_text())

            self.assertEqual(env["CODEX_HOME"], str(config_path.parent))
            self.assertEqual(Path(env["HOME"]), root / ".codex-home")
            self.assertEqual(Path(env["GIT_CONFIG_GLOBAL"]), root / ".codex-home" / ".gitconfig")
            self.assertIn('wire_api = "responses"', config_text)
            self.assertIn('model_reasoning_effort = "medium"', config_text)
            self.assertIn('web_search = "disabled"', config_text)
            self.assertNotIn("mcp_servers", config_text)
            self.assertEqual(catalog["models"][0]["slug"], "Qwen3.5-2B")
            gitconfig = (root / ".codex-home" / ".gitconfig").read_text()
            self.assertIn(str(workspace), gitconfig)

    def test_opencode_benchmark_config_uses_openai_compatible_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            env, model_id = _write_opencode_benchmark_config(
                root / ".opencode-benchmark",
                {"provider_class": "local", "local_served_model_name": "qwen"},
                home_dir=home,
            )

            config_path = Path(env["OPENCODE_CONFIG"])
            config = json.loads(config_path.read_text())

            self.assertEqual(model_id, "local/qwen")
            self.assertEqual(config_path.parent.parent, Path(env["XDG_CONFIG_HOME"]))
            self.assertEqual(Path(env["HOME"]), home)
            self.assertEqual(config["model"], "local/qwen")
            self.assertTrue(config["agent"]["title"]["disable"])
            self.assertNotIn("summary", config["agent"])
            self.assertEqual(config["provider"]["local"]["npm"], "@ai-sdk/openai-compatible")
            self.assertEqual(config["provider"]["local"]["options"]["baseURL"], "http://127.0.0.1:4000/v1")
            self.assertTrue(config["provider"]["local"]["models"]["qwen"]["tool_call"])
            self.assertIn("anthropic", config["disabled_providers"])

    def test_codex_cloud_config_uses_isolated_home_and_copies_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source_home = root / "source-home"
            source_auth = source_home / ".codex" / "auth.json"
            source_auth.parent.mkdir(parents=True)
            source_auth.write_text('{"token": "test-only"}\n')
            with patch("fortbench.adapters.Path.home", return_value=source_home):
                env = _write_codex_cloud_config(
                    root / ".codex-cloud",
                    workspace,
                    {"model": "gpt-5.4-mini", "provider_class": "cloud"},
                    home_dir=root / ".codex-home",
                )

            config_path = Path(env["CODEX_CONFIG_PATH"])
            config_text = config_path.read_text()
            # codex-cli 0.x rejects the legacy profile selector; settings live at
            # the top level of config.toml, before any table header.
            self.assertNotIn("[profiles.fortbench-cloud]", config_text)
            self.assertLess(
                config_text.index('model = "gpt-5.4-mini"'),
                config_text.index("[projects"),
            )
            self.assertIn('web_search = "disabled"', config_text)
            self.assertNotIn("model_reasoning_effort", config_text)
            self.assertEqual(Path(env["HOME"]), root / ".codex-home")
            copied_auth = config_path.parent / "auth.json"
            self.assertEqual(copied_auth.read_text(), source_auth.read_text())
            self.assertEqual(copied_auth.stat().st_mode & 0o777, 0o600)

    def test_local_sampling_options_follow_model_family(self) -> None:
        self.assertEqual(
            _local_sampling_options({"local_model_alias": "qwen3.5-122b-a10b"}),
            {
                "temperature": 0.6,
                "top_p": 0.95,
                "top_k": 20,
                "min_p": 0.0,
                "presence_penalty": 0.0,
                "repeat_penalty": 1.0,
            },
        )
        self.assertEqual(
            _local_sampling_options({"local_model_alias": "devstral-2-123b"}),
            {"temperature": 0.15},
        )
        self.assertEqual(
            _local_sampling_options({"local_model_alias": "mistral-small-4-119b"}),
            {"temperature": 0.15, "top_p": 0.95},
        )
        self.assertEqual(
            _local_sampling_options({"local_model_alias": "nemotron-120b-a12b"}),
            {"temperature": 1.0, "top_p": 0.95},
        )
        self.assertEqual(
            _local_sampling_options({"local_model_alias": "kimi-k2.6"}),
            {"temperature": 0.6, "top_p": 0.95},
        )
        self.assertEqual(_local_sampling_options({"local_model_alias": "gpt-oss-120b"}), {})
        self.assertEqual(
            _local_sampling_options({"local_model_alias": "deepseek-v4-flash-q4kexp"}),
            {
                "temperature": 1.0,
                "top_p": 1.0,
            },
        )

    def test_opencode_benchmark_config_uses_model_specific_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"

            _, qwen_model_id = _write_opencode_benchmark_config(
                root / ".opencode-qwen",
                {"provider_class": "local", "local_served_model_name": "qwen", "local_model_alias": "qwen3.5-122b-a10b"},
                home_dir=home / "qwen",
            )
            qwen_cfg = json.loads((home / "qwen" / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(qwen_model_id, "local/qwen")
            self.assertEqual(
                qwen_cfg["provider"]["local"]["models"]["qwen"]["options"],
                {
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": 0.0,
                    "presence_penalty": 0.0,
                    "repeat_penalty": 1.0,
                },
            )

            _, dev_cfg_id = _write_opencode_benchmark_config(
                root / ".opencode-devstral",
                {"provider_class": "local", "local_served_model_name": "qwen", "local_model_alias": "devstral-2-123b"},
                home_dir=home / "devstral",
            )
            self.assertEqual(dev_cfg_id, "local/qwen")
            dev_cfg = json.loads((home / "devstral" / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(dev_cfg["provider"]["local"]["models"]["qwen"]["options"], {"temperature": 0.15})

            _, kimi_cfg_id = _write_opencode_benchmark_config(
                root / ".opencode-kimi",
                {"provider_class": "local", "local_served_model_name": "qwen", "local_model_alias": "kimi-k2.6"},
                home_dir=home / "kimi",
            )
            self.assertEqual(kimi_cfg_id, "local/qwen")
            kimi_cfg = json.loads((home / "kimi" / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(kimi_cfg["provider"]["local"]["models"]["qwen"]["options"], {"temperature": 0.6, "top_p": 0.95})

            _, gpt_cfg_id = _write_opencode_benchmark_config(
                root / ".opencode-gptoss",
                {"provider_class": "local", "local_served_model_name": "qwen", "local_model_alias": "gpt-oss-120b"},
                home_dir=home / "gptoss",
            )
            self.assertEqual(gpt_cfg_id, "local/qwen")
            gpt_cfg = json.loads((home / "gptoss" / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(gpt_cfg["provider"]["local"]["models"]["qwen"]["options"], {})

            _, deepseek_cfg_id = _write_opencode_benchmark_config(
                root / ".opencode-deepseek",
                {
                    "provider_class": "local",
                    "local_served_model_name": "deepseek-v4-flash",
                    "local_model_alias": "deepseek-v4-flash-q4kexp",
                },
                home_dir=home / "deepseek",
            )
            self.assertEqual(deepseek_cfg_id, "local/deepseek-v4-flash")
            deepseek_cfg = json.loads((home / "deepseek" / ".config" / "opencode" / "opencode.json").read_text())
            deepseek_model = deepseek_cfg["provider"]["local"]["models"]["deepseek-v4-flash"]
            self.assertEqual(
                deepseek_model["options"],
                {
                    "temperature": 1.0,
                    "top_p": 1.0,
                },
            )
            self.assertNotIn("reasoning", deepseek_model)
            self.assertNotIn("interleaved", deepseek_model)

    def test_codex_extract_text_handles_list_wrapped_events(self) -> None:
        stdout = "\n".join(
            [
                json.dumps(
                    [
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "agent_message",
                                "message": "list wrapped message",
                            },
                        }
                    ]
                )
            ]
        )

        self.assertEqual(_extract_text("codex", stdout, ""), "list wrapped message")

    def test_codex_extract_text_handles_response_item_messages(self) -> None:
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "first"},
                                {"type": "output_text", "text": "second"},
                            ],
                        },
                    }
                )
            ]
        )

        self.assertEqual(_extract_text("codex", stdout, ""), "first\nsecond")

    def test_reasoning_defaults_only_enable_for_reasoning_families(self) -> None:
        self.assertEqual(_codex_reasoning_effort({"local_model_alias": "qwen3.5-9b"}), "medium")
        self.assertIsNone(_opencode_variant({"local_model_alias": "deepseek-v4-flash-q4kexp"}))
        self.assertEqual(_opencode_variant({"local_model_alias": "gpt-oss-20b"}), "medium")
        self.assertIsNone(_codex_reasoning_effort({"local_model_alias": "devstral-small-2-24b"}))
        self.assertIsNone(_opencode_variant({"local_model_alias": "nemotron-120b-a12b"}))
        self.assertIsNone(_codex_reasoning_effort({"provider_class": "cloud", "model": "gpt-5.4-mini"}))

    def test_run_command_can_launch_from_neutral_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            launcher = root / "launcher"
            workspace.mkdir()
            launcher.mkdir()

            response = _run_command(
                ["/bin/pwd"],
                workspace,
                timeout_seconds=5,
                process_cwd=launcher,
            )

            self.assertTrue(response.ok)
            self.assertEqual(Path(response.stdout.strip()).resolve(), launcher.resolve())

    def test_codex_command_prefers_native_binary(self) -> None:
        command = _codex_command()
        self.assertTrue(command)
        self.assertTrue(command[0].endswith("codex"))

    def test_local_benchmark_user_defaults_to_fortbench(self) -> None:
        self.assertTrue(_local_benchmark_user())
        self.assertNotEqual(_local_benchmark_user(), "does-not-exist")

    def test_sudo_local_command_wraps_login_shell_env_and_cwd(self) -> None:
        user = _local_benchmark_user()
        command = _sudo_local_command(
            ["codex", "exec", "--cd", "/tmp/workspace", "--", "hello"],
            Path("/tmp/launcher"),
            {"CODEX_HOME": "/tmp/.codex-home", "PATH": "/usr/bin:/bin"},
        )

        if user == _current_user_name():
            self.assertEqual(command[:2], ["/bin/zsh", "-lc"])
            self.assertIn("cd /tmp/launcher", command[2])
            self.assertNotIn("sudo", command[0])
            shell_cmd = command[2]
        else:
            self.assertEqual(command[:5], ["sudo", "-n", "-iu", user, "/bin/zsh"])
            self.assertEqual(command[5], "-lc")
            self.assertIn("cd /tmp/launcher", command[6])
            shell_cmd = command[6]
        self.assertIn("CODEX_HOME=/tmp/.codex-home", shell_cmd)
        self.assertIn("codex exec --cd /tmp/workspace -- hello", shell_cmd)

    @patch("fortbench.adapters.collect_proxy_log")
    @patch("fortbench.adapters.snapshot_proxy_log")
    @patch("fortbench.adapters._write_codex_benchmark_config")
    @patch("fortbench.adapters._run_command")
    def test_local_codex_stage_uses_proxy_logging_and_sudo(
        self,
        mock_run_command: MagicMock,
        mock_write_config: MagicMock,
        mock_snapshot_proxy: MagicMock,
        mock_collect_proxy: MagicMock,
    ) -> None:
        mock_write_config.return_value = {"PATH": "/usr/bin:/bin", "CODEX_HOME": "/tmp/.codex"}
        mock_snapshot_proxy.return_value = object()
        mock_collect_proxy.return_value = {"request_count": 2, "log_write_errors": 0, "drained_cleanly": True}
        mock_run_command.return_value = AgentResponse(
            ok=True,
            command=[],
            returncode=0,
            stdout="{}",
            stderr="",
            duration_seconds=0.1,
            text="ok",
        )

        row = {"provider_class": "local", "model": "Qwen3.5-0.8B", "local_model_alias": "qwen3.5-0.8b", "local_instance": "local"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = CodexAdapter().stage(1, "prompt", root / "workspace", root / "run", row, 10)

        self.assertEqual(response.protocol_summary["request_count"], 2)
        launched_command = mock_run_command.call_args.args[0]
        if _local_benchmark_user() == _current_user_name():
            self.assertEqual(launched_command[:2], ["/bin/zsh", "-lc"])
        else:
            self.assertEqual(launched_command[:4], ["sudo", "-n", "-iu", _local_benchmark_user()])
        self.assertEqual(mock_collect_proxy.call_args.args[2], mock_snapshot_proxy.return_value)

    @patch("fortbench.adapters._write_codex_cloud_config")
    @patch("fortbench.adapters._run_command")
    def test_cloud_codex_stage_uses_isolated_user_and_writes_protocol(
        self,
        mock_run_command: MagicMock,
        mock_write_cloud_config: MagicMock,
    ) -> None:
        mock_write_cloud_config.return_value = {"PATH": "/usr/bin:/bin", "CODEX_HOME": "/tmp/.codex"}
        mock_run_command.return_value = AgentResponse(
            ok=True,
            command=[],
            returncode=0,
            stdout="\n".join(
                [
                    json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "thinking"}}),
                    json.dumps({"type": "result", "result": "done"}),
                ]
            ),
            stderr="",
            duration_seconds=0.1,
            text="done",
        )

        row = {"name": "codex-gpt-5.4-mini-default", "provider_class": "cloud", "model": "gpt-5.4-mini"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            response = CodexAdapter().stage(1, "prompt", workspace, root / "run", row, 10)

            self.assertEqual(response.protocol_summary["kind"], "codex-cli")
            self.assertEqual(response.protocol_summary["log_write_errors"], 0)
            self.assertIn("protocol_path", response.artifacts)
            config_dir = mock_write_cloud_config.call_args.args[0]
            self.assertEqual(config_dir, root / "run" / ".codex-cloud" / "stage-1")
            launched_command = mock_run_command.call_args.args[0]
            if _local_benchmark_user() == _current_user_name():
                self.assertEqual(launched_command[:2], ["/bin/zsh", "-lc"])
            else:
                self.assertEqual(launched_command[:4], ["sudo", "-n", "-iu", _local_benchmark_user()])
            protocol_path = root / "run" / "stages" / "stage-1" / "protocol.jsonl"
            self.assertTrue(protocol_path.exists())

    @patch("fortbench.adapters.collect_proxy_log")
    @patch("fortbench.adapters.snapshot_proxy_log")
    @patch("fortbench.adapters._write_opencode_benchmark_config")
    @patch("fortbench.adapters._run_command")
    def test_local_opencode_stage_uses_proxy_logging_and_sudo(
        self,
        mock_run_command: MagicMock,
        mock_write_config: MagicMock,
        mock_snapshot_proxy: MagicMock,
        mock_collect_proxy: MagicMock,
    ) -> None:
        mock_write_config.return_value = ({"PATH": "/usr/bin:/bin", "HOME": "/tmp/home"}, "local/qwen")
        mock_snapshot_proxy.return_value = object()
        mock_collect_proxy.return_value = {"request_count": 1, "log_write_errors": 0, "drained_cleanly": True}
        mock_run_command.return_value = AgentResponse(
            ok=True,
            command=[],
            returncode=0,
            stdout="{}",
            stderr="",
            duration_seconds=0.1,
            text="ok",
        )

        row = {"provider_class": "local", "model": "ignored", "local_served_model_name": "qwen", "local_model_alias": "qwen3.5-0.8b", "local_instance": "local"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = OpenCodeAdapter().stage(1, "prompt", root / "workspace", root / "run", row, 10)

        self.assertEqual(response.protocol_summary["request_count"], 1)
        launched_command = mock_run_command.call_args.args[0]
        if _local_benchmark_user() == _current_user_name():
            self.assertEqual(launched_command[:2], ["/bin/zsh", "-lc"])
        else:
            self.assertEqual(launched_command[:4], ["sudo", "-n", "-iu", _local_benchmark_user()])
        self.assertEqual(mock_collect_proxy.call_args.args[2], mock_snapshot_proxy.return_value)

    @patch("fortbench.adapters._run_command")
    def test_cloud_claude_stage_uses_neutral_cwd_and_structured_protocol(
        self,
        mock_run_command: MagicMock,
    ) -> None:
        mock_run_command.return_value = AgentResponse(
            ok=True,
            command=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "done",
                    "stop_reason": "end_turn",
                    "duration_ms": 123,
                    "num_turns": 1,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }
            ),
            stderr="",
            duration_seconds=0.1,
            text="done",
        )

        row = {"name": "claude-haiku-default", "provider_class": "cloud", "model": "haiku"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            response = ClaudeCodeAdapter().stage(1, "prompt text", workspace, root / "run", row, 10)

            launched_command = mock_run_command.call_args.args[0]
            self.assertEqual(launched_command[:4], ["claude", "--print", "--output-format", "json"])
            self.assertIn("--setting-sources", launched_command)
            self.assertIn("user", launched_command)
            self.assertIn("--add-dir", launched_command)
            self.assertIn(str(workspace), launched_command)
            self.assertEqual(mock_run_command.call_args.kwargs["process_cwd"], root / "run" / ".launcher")
            self.assertEqual(mock_run_command.call_args.kwargs["stdin_text"], "prompt text")
            self.assertEqual(response.protocol_summary["kind"], "claude-cli")
            protocol_path = root / "run" / "stages" / "stage-1" / "protocol.jsonl"
            self.assertTrue(protocol_path.exists())

    def test_collect_claude_cli_protocol_parses_json_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            summary = _collect_claude_cli_protocol(
                stage_dir,
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "result": "ok",
                        "stop_reason": "end_turn",
                        "duration_ms": 42,
                        "num_turns": 1,
                        "usage": {"input_tokens": 12, "output_tokens": 3},
                    }
                ),
                "",
            )
            self.assertEqual(summary["kind"], "claude-cli")
            self.assertEqual(summary["result_length"], 2)
            self.assertEqual(summary["input_tokens"], 12)
            self.assertEqual(summary["output_tokens"], 3)
            self.assertTrue((stage_dir / "protocol.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
