from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fortbench import litellm_proxy


class LiteLLMProxyTests(unittest.TestCase):
    def test_callback_source_uses_sync_pre_call_hook_and_epoch_time(self) -> None:
        source = litellm_proxy._callback_source()
        self.assertIn("def log_pre_api_call", source)
        self.assertIn("epoch = time.time()", source)
        self.assertIn("complete_input_dict", source)
        self.assertIn('request["method"] = method', source)
        self.assertIn("timezone.utc", source)

    def test_callback_request_extraction_does_not_mutate_live_body(self) -> None:
        source = litellm_proxy._callback_source()
        custom_logger = types.ModuleType("litellm.integrations.custom_logger")

        class CustomLogger:
            pass

        custom_logger.CustomLogger = CustomLogger
        sys.modules["litellm.integrations.custom_logger"] = custom_logger
        namespace: dict[str, object] = {}
        with patch.dict("os.environ", {"FORTBENCH_LITELLM_LOG": "/tmp/fortbench-test-log.jsonl"}):
            exec(source, namespace)

            live_body = {"model": "qwen", "messages": [{"role": "user", "content": "hi"}]}
            kwargs = {"proxy_server_request": {"body": live_body}, "input": [{"role": "user", "content": "shadow"}]}
            request = namespace["_extract_request"](kwargs, "qwen", [{"role": "user", "content": "hi"}])

        self.assertNotIn("input", live_body)
        self.assertNotIn("input", request["body"])
        self.assertEqual(request["body"]["messages"][0]["content"], "hi")

    def test_callback_writer_serializes_concurrent_jsonl_appends(self) -> None:
        source = litellm_proxy._callback_source()
        custom_logger = types.ModuleType("litellm.integrations.custom_logger")

        class CustomLogger:
            pass

        custom_logger.CustomLogger = CustomLogger
        sys.modules["litellm.integrations.custom_logger"] = custom_logger

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "requests.jsonl"
            namespace: dict[str, object] = {}
            with patch.dict("os.environ", {"FORTBENCH_LITELLM_LOG": str(log_path)}):
                exec(source, namespace)

            write = namespace["_write"]

            def worker(start: int) -> None:
                for idx in range(100):
                    write({"type": "request_start", "request_started_at_epoch": float(start + idx), "worker": start})

            threads = [threading.Thread(target=worker, args=(n * 1000,)) for n in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]

        self.assertEqual(len(records), 800)
        self.assertTrue(all(record["type"] == "request_start" for record in records))

    def test_prepare_proxy_root_clears_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proxy"
            root.mkdir(parents=True)
            (root / "old.jsonl").write_text("old\n")
            prepared = litellm_proxy.prepare_proxy_root(root)

            self.assertEqual(prepared, root.resolve())
            self.assertTrue(root.exists())
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["requests.jsonl"])

    def test_collect_proxy_log_compacts_new_records_and_clears_raw_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proxy"
            stage_dir = Path(tmp) / "stage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"FORTBENCH_LITELLM_PROXY_ROOT": str(root)}):
                first_record = {
                    "type": "request_start",
                    "request_started_at_epoch": 1.0,
                    "route": "http://127.0.0.1:4000/v1/responses",
                    "request": {"method": "POST", "body": {"model": "Qwen3.5-0.8B"}},
                    "response": None,
                }
                second_record = {
                    "type": "request_start",
                    "request_started_at_epoch": 3.0,
                    "route": "http://127.0.0.1:4000/v1/responses",
                    "request": {"method": "POST", "body": {"model": "Qwen3.5-0.8B"}},
                    "response": None,
                }
                third_record = {
                    "type": "success",
                    "request_started_at_epoch": 3.0,
                    "duration_seconds": 0.5,
                    "route": "http://127.0.0.1:4000/v1/responses",
                    "request": {"method": "POST", "body": {"model": "Qwen3.5-0.8B"}},
                    "response": {"id": "resp-2"},
                }
                log_path = litellm_proxy.proxy_log_path()
                raw = "".join(json.dumps(record) + "\n" for record in [first_record, second_record, third_record])
                log_path.write_text(raw)
                cursor = litellm_proxy.ProxyLogCursor(offset=len(json.dumps(first_record) + "\n"))
                summary = litellm_proxy.collect_proxy_log(stage_dir, started_at_epoch=2.0, cursor=cursor)

                protocol_records = [json.loads(line) for line in (stage_dir / "protocol.jsonl").read_text().splitlines()]

            self.assertEqual(summary["request_count"], 1)
            self.assertEqual(summary["response_finish_count"], 1)
            self.assertEqual(summary["foreign_record_count"], 0)
            self.assertEqual(summary["log_write_errors"], 0)
            self.assertEqual(summary["first_request_method"], "POST")
            self.assertEqual(summary["first_request_path"], "http://127.0.0.1:4000/v1/responses")
            self.assertAlmostEqual(summary["total_upstream_seconds"], 0.5)
            self.assertEqual(protocol_records[-1]["response"]["id"], "resp-2")
            self.assertEqual(log_path.read_text(), "")

    def test_collect_proxy_log_counts_parse_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proxy"
            stage_dir = Path(tmp) / "stage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"FORTBENCH_LITELLM_PROXY_ROOT": str(root)}):
                cursor = litellm_proxy.snapshot_proxy_log()
                litellm_proxy.proxy_log_path().write_text(
                    'not-json\n'
                    '{"type":"request_start","request_started_at_epoch":2.0}\n'
                    '{"type":"success","request_started_at_epoch":2.0,"duration_seconds":1.0}\n'
                )
                summary = litellm_proxy.collect_proxy_log(stage_dir, started_at_epoch=0.0, cursor=cursor)

            self.assertEqual(summary["log_write_errors"], 1)
            self.assertEqual(summary["request_count"], 1)

    def test_collect_proxy_log_counts_request_start_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proxy"
            stage_dir = Path(tmp) / "stage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"FORTBENCH_LITELLM_PROXY_ROOT": str(root)}):
                litellm_proxy.proxy_log_path().write_text(
                    "\n".join(
                        [
                            json.dumps({"type": "request_start", "request_started_at_epoch": 2.0, "route": "/v1/chat/completions"}),
                            json.dumps({"type": "success", "request_started_at_epoch": 2.0, "duration_seconds": 1.25, "route": "/v1/chat/completions"}),
                            "",
                        ]
                    )
                )
                cursor = litellm_proxy.ProxyLogCursor(offset=0)
                summary = litellm_proxy.collect_proxy_log(stage_dir, started_at_epoch=0.0, cursor=cursor)

            self.assertEqual(summary["request_count"], 1)
            self.assertEqual(summary["response_finish_count"], 1)
            self.assertEqual(summary["first_request_path"], "/v1/chat/completions")
            self.assertAlmostEqual(summary["total_upstream_seconds"], 1.25)

    def test_collect_proxy_log_allows_foreign_finish_without_foreign_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proxy"
            stage_dir = Path(tmp) / "stage"
            root.mkdir(parents=True)
            with patch.dict("os.environ", {"FORTBENCH_LITELLM_PROXY_ROOT": str(root)}):
                litellm_proxy.proxy_log_path().write_text(
                    "\n".join(
                        [
                            json.dumps({"type": "success", "request_started_at_epoch": 1.0, "duration_seconds": 5.0}),
                            json.dumps({"type": "request_start", "request_started_at_epoch": 2.0, "route": "/v1/chat/completions"}),
                            json.dumps({"type": "success", "request_started_at_epoch": 2.0, "duration_seconds": 1.25}),
                            "",
                        ]
                    )
                )
                cursor = litellm_proxy.ProxyLogCursor(offset=0)
                summary = litellm_proxy.collect_proxy_log(stage_dir, started_at_epoch=2.0, cursor=cursor)

            self.assertEqual(summary["foreign_record_count"], 1)
            self.assertEqual(summary["foreign_request_start_count"], 0)
            self.assertEqual(summary["foreign_finish_count"], 1)
            self.assertEqual(summary["request_count"], 1)
            self.assertEqual(summary["response_finish_count"], 1)

    @patch("fortbench.litellm_proxy.subprocess.Popen")
    @patch("fortbench.litellm_proxy._wait_for_proxy_ready")
    @patch("fortbench.litellm_proxy.stop_proxy")
    def test_start_proxy_writes_config_and_callback(
        self,
        mock_stop_proxy: MagicMock,
        mock_wait_ready: MagicMock,
        mock_popen: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proxy"
            with patch.dict("os.environ", {"FORTBENCH_LITELLM_PROXY_ROOT": str(root)}):
                mock_popen.return_value.pid = 123
                litellm_proxy.start_proxy(
                    {
                        "adapter": "codex",
                        "model": "Qwen3.5-0.8B",
                        "local_model_alias": "qwen3.5-0.8b",
                    }
                )

                config = (root / "config.yaml").read_text()
                callback = (root / "fortbench_callback.py").read_text()

            self.assertIn("model_name: \"Qwen3.5-0.8B\"", config)
            self.assertIn("callbacks: [\"fortbench_callback.proxy_handler_instance\"]", config)
            self.assertIn("drop_params: true", config)
            self.assertIn("class FortbenchLogger", callback)
            self.assertIn("def log_pre_api_call", callback)
            self.assertIn("async_log_pre_api_call", callback)
            mock_wait_ready.assert_called_once()
            self.assertEqual(mock_wait_ready.call_args.args[0], "Qwen3.5-0.8B")
            self.assertIs(mock_wait_ready.call_args.kwargs["proc"], mock_popen.return_value)

    @patch("fortbench.litellm_proxy.subprocess.Popen")
    @patch("fortbench.litellm_proxy._wait_for_proxy_ready")
    @patch("fortbench.litellm_proxy.stop_proxy")
    def test_start_proxy_retries_once_after_failed_boot(
        self,
        mock_stop_proxy: MagicMock,
        mock_wait_ready: MagicMock,
        mock_popen: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proxy"
            first_proc = MagicMock(pid=123)
            second_proc = MagicMock(pid=124)
            mock_popen.side_effect = [first_proc, second_proc]
            mock_wait_ready.side_effect = [RuntimeError("boom"), None]
            with patch.dict(
                "os.environ",
                {
                    "FORTBENCH_LITELLM_PROXY_ROOT": str(root),
                    "FORTBENCH_LITELLM_PROXY_START_ATTEMPTS": "2",
                },
            ):
                litellm_proxy.start_proxy(
                    {
                        "adapter": "codex",
                        "model": "Qwen3.5-0.8B",
                        "local_model_alias": "qwen3.5-0.8b",
                    }
                )

        self.assertEqual(mock_popen.call_count, 2)
        self.assertEqual(mock_wait_ready.call_count, 2)
        self.assertEqual(mock_stop_proxy.call_count, 2)

    def test_config_forwards_served_model_for_strict_upstreams(self) -> None:
        # Default opencode row stays backward-compatible with the hardcoded
        # openai/qwen upstream that llama.cpp ignores.
        default_cfg = litellm_proxy._config_yaml(
            {"adapter": "opencode", "model": "llamacpp/qwen"}
        )
        self.assertIn('model: "openai/qwen"', default_cfg)
        self.assertIn('model_name: "qwen"', default_cfg)
        # An explicit served name is forwarded so strict OpenAI servers
        # (mlx_lm.server, Rapid-MLX, vLLM) accept the request instead of
        # rejecting an unknown model id.
        strict_cfg = litellm_proxy._config_yaml(
            {
                "adapter": "opencode",
                "model": "llamacpp/qwen",
                "local_served_model_name": "deepseek",
            }
        )
        self.assertIn('model: "openai/deepseek"', strict_cfg)
        self.assertIn('model_name: "deepseek"', strict_cfg)

    def test_config_uses_custom_endpoint_and_environment_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "FORTBENCH_ENDPOINT": "https://api.example/v1",
                "FORTBENCH_SERVED_MODEL": "custom-model",
            },
        ):
            config = litellm_proxy._config_yaml(
                {
                    "adapter": "opencode",
                    "endpoint": "${FORTBENCH_ENDPOINT}",
                    "local_served_model_name": "${FORTBENCH_SERVED_MODEL}",
                    "api_key_env": "FORTBENCH_UPSTREAM_API_KEY",
                }
            )
        self.assertIn('api_base: "https://api.example/v1"', config)
        self.assertIn('model: "openai/custom-model"', config)
        self.assertIn('api_key: "os.environ/FORTBENCH_UPSTREAM_API_KEY"', config)


if __name__ == "__main__":
    unittest.main()
