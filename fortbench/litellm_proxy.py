from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROXY_ROOT = Path("/tmp/fortbench-litellm-proxy")
PROXY_PORT = 4000
PROXY_LOG_QUIET_PERIOD_SECONDS = 1.0
PROXY_LOG_QUIET_TIMEOUT_SECONDS = 30.0
PROXY_REQUEST_TIMEOUT_SECONDS = 1800
PROXY_START_ATTEMPTS = 3
PROXY_MASTER_KEY = ""
PROXY_LOG_FILENAME = "requests.jsonl"
PROXY_STDOUT_FILENAME = "proxy.log"
PROXY_PID_FILENAME = "proxy.pid"
PROXY_CONFIG_FILENAME = "config.yaml"
PROXY_CALLBACK_FILENAME = "fortbench_callback.py"


@dataclass(frozen=True)
class ProxyLogCursor:
    offset: int


def proxy_root() -> Path:
    return Path(os.environ.get("FORTBENCH_LITELLM_PROXY_ROOT", str(PROXY_ROOT)))


def proxy_port() -> int:
    return int(os.environ.get("FORTBENCH_LITELLM_PROXY_PORT", str(PROXY_PORT)))


def proxy_base_url() -> str:
    return f"http://127.0.0.1:{proxy_port()}/v1"


def proxy_master_key() -> str:
    return os.environ.get("FORTBENCH_LITELLM_MASTER_KEY", PROXY_MASTER_KEY)


def proxy_request_timeout_seconds() -> int:
    return int(
        os.environ.get(
            "FORTBENCH_LITELLM_REQUEST_TIMEOUT_SECONDS",
            str(PROXY_REQUEST_TIMEOUT_SECONDS),
        )
    )


def proxy_start_attempts() -> int:
    return max(
        1,
        int(
            os.environ.get(
                "FORTBENCH_LITELLM_PROXY_START_ATTEMPTS",
                str(PROXY_START_ATTEMPTS),
            )
        ),
    )


def proxy_log_quiet_period_seconds() -> float:
    return float(
        os.environ.get(
            "FORTBENCH_LITELLM_LOG_QUIET_SECONDS",
            str(PROXY_LOG_QUIET_PERIOD_SECONDS),
        )
    )


def proxy_log_quiet_timeout_seconds() -> float:
    return float(
        os.environ.get(
            "FORTBENCH_LITELLM_LOG_QUIET_TIMEOUT_SECONDS",
            str(PROXY_LOG_QUIET_TIMEOUT_SECONDS),
        )
    )


def proxy_bin() -> str:
    explicit = os.environ.get("FORTBENCH_LITELLM_PROXY_BIN", "").strip()
    if explicit:
        return explicit
    repo_venv = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "litellm"
    if repo_venv.exists():
        return str(repo_venv)
    return "litellm"


def proxy_log_path() -> Path:
    return proxy_root() / PROXY_LOG_FILENAME


def proxy_stdout_path() -> Path:
    return proxy_root() / PROXY_STDOUT_FILENAME


def proxy_pid_path() -> Path:
    return proxy_root() / PROXY_PID_FILENAME


def proxy_config_path() -> Path:
    return proxy_root() / PROXY_CONFIG_FILENAME


def proxy_callback_path() -> Path:
    return proxy_root() / PROXY_CALLBACK_FILENAME


def _proxy_healthcheck_url() -> str:
    return f"http://127.0.0.1:{proxy_port()}/v1/models"


def _proxy_auth_headers() -> dict[str, str]:
    key = proxy_master_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _proxy_stdout_tail(limit_bytes: int = 4096) -> str:
    path = proxy_stdout_path()
    if not path.exists():
        return ""
    raw = path.read_bytes()
    if not raw:
        return ""
    return raw[-limit_bytes:].decode("utf-8", errors="replace").strip()


def _upstream_base_url(row: dict) -> str:
    endpoint = os.path.expandvars(str(row.get("endpoint", ""))).strip()
    if endpoint:
        if "$" in endpoint:
            raise RuntimeError("endpoint references an unset environment variable")
        return endpoint.rstrip("/")
    port = int(row.get("local_port") or (8081 if row.get("local_instance") == "fast" else 8080))
    return f"http://127.0.0.1:{port}/v1"


def _proxy_model_name(row: dict) -> str:
    if row.get("adapter") == "opencode":
        return os.path.expandvars(str(row.get("local_served_model_name") or "qwen"))
    return os.path.expandvars(str(row.get("model", "qwen")))


def prepare_proxy_root(root: Path | None = None) -> Path:
    target = (root or proxy_root()).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    (target / PROXY_LOG_FILENAME).write_text("")
    return target


def _callback_source() -> str:
    return """from __future__ import annotations

import fcntl
import json
import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

from litellm.integrations.custom_logger import CustomLogger


LOG_PATH = Path(os.environ["FORTBENCH_LITELLM_LOG"])
WRITE_LOCK = threading.Lock()


def _utc_now():
    epoch = time.time()
    stamp = datetime.fromtimestamp(epoch, timezone.utc)
    return stamp, epoch


def _serialize_dt(value):
    if value is None:
        return None, None
    try:
        epoch = value.timestamp()
    except Exception:
        return value.isoformat(), None
    iso = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    return iso, epoch


def _sanitize(value, depth=0):
    if depth > 8:
        return repr(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _sanitize(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v, depth + 1) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _sanitize(value.model_dump(mode="json"), depth + 1)
        except Exception:
            try:
                return _sanitize(value.model_dump(), depth + 1)
            except Exception:
                pass
    if hasattr(value, "dict"):
        try:
            return _sanitize(value.dict(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return _sanitize(dict(value.__dict__), depth + 1)
        except Exception:
            pass
    return repr(value)


def _extract_request(kwargs, model, messages):
    request = _sanitize(kwargs.get("proxy_server_request") or {})
    if not isinstance(request, dict):
        request = {}
    additional_args = kwargs.get("additional_args") or {}
    if not isinstance(additional_args, dict):
        additional_args = {}

    body_source = request.get("body")
    if not isinstance(body_source, dict):
        raw_request = kwargs.get("raw_request_typed_dict") or {}
        if isinstance(raw_request, dict):
            raw_body = raw_request.get("raw_request_body")
            if isinstance(raw_body, dict):
                body_source = raw_body
    if not isinstance(body_source, dict):
        complete_input = additional_args.get("complete_input_dict")
        if isinstance(complete_input, dict):
            body_source = complete_input
    body = _sanitize(body_source) if isinstance(body_source, dict) else {}
    has_body_source = isinstance(body_source, dict)
    if not has_body_source and "model" not in body and model is not None:
        body["model"] = model
    if not has_body_source and "messages" not in body and messages is not None:
        body["messages"] = messages
    input_value = kwargs.get("input")
    if not has_body_source and "input" not in body and input_value is not None:
        body["input"] = input_value
    tools = kwargs.get("tools")
    if not has_body_source and "tools" not in body and tools is not None:
        body["tools"] = tools

    method = request.get("method") or "POST"
    headers = request.get("headers")
    if not isinstance(headers, dict):
        header_candidates = [
            additional_args.get("headers"),
            ((kwargs.get("litellm_params") or {}).get("proxy_server_request") or {}).get("headers"),
        ]
        for candidate in header_candidates:
            if isinstance(candidate, dict):
                headers = candidate
                break

    request["method"] = method
    request["body"] = _sanitize(body)
    if isinstance(headers, dict):
        request["headers"] = _sanitize(headers)
    return request


def _build_record(status, kwargs, response_obj, start_time, end_time):
    now_iso, _ = _utc_now()
    request = _extract_request(kwargs, kwargs.get("model"), kwargs.get("messages"))
    metadata = _sanitize(((kwargs.get("litellm_params") or {}).get("metadata")) or {})
    request_body = request.get("body") if isinstance(request, dict) else None
    route = None
    if isinstance(metadata, dict):
        route = metadata.get("user_api_key_request_route")
    if not route and isinstance(request, dict):
        route = request.get("url")
    exc = kwargs.get("exception")
    error = None
    if exc is not None:
        error = repr(exc)
    elif status == "failure":
        error = _sanitize(response_obj)

    request_started_at, request_started_at_epoch = _serialize_dt(start_time)
    request_finished_at, _ = _serialize_dt(end_time)
    return {
        "type": status,
        "ts": now_iso.isoformat(),
        "request_started_at": request_started_at,
        "request_started_at_epoch": request_started_at_epoch,
        "request_finished_at": request_finished_at,
        "duration_seconds": (
            max(0.0, (end_time - start_time).total_seconds())
            if start_time is not None and end_time is not None
            else None
        ),
        "route": route,
        "stream": bool((request_body or {}).get("stream")) if isinstance(request_body, dict) else False,
        "model": (request_body or {}).get("model") if isinstance(request_body, dict) else kwargs.get("model"),
        "request": request,
        "response": _sanitize(response_obj),
        "error": error,
    }


def _build_request_start(model, messages, kwargs):
    now, epoch = _utc_now()
    request = _extract_request(kwargs, model, messages)
    metadata = _sanitize(((kwargs.get("litellm_params") or {}).get("metadata")) or {})
    request_body = request.get("body") if isinstance(request, dict) else None
    route = None
    if isinstance(metadata, dict):
        route = metadata.get("user_api_key_request_route")
    if not route and isinstance(request, dict):
        route = request.get("url")
    return {
        "type": "request_start",
        "ts": now.isoformat(),
        "request_started_at": now.isoformat(),
        "request_started_at_epoch": epoch,
        "request_finished_at": None,
        "duration_seconds": None,
        "route": route,
        "stream": bool((request_body or {}).get("stream")) if isinstance(request_body, dict) else False,
        "model": (request_body or {}).get("model") if isinstance(request_body, dict) else model,
        "request": request,
        "response": None,
        "error": None,
    }


def _write(record):
    payload = (json.dumps(record, ensure_ascii=False) + "\\n").encode("utf-8")
    with WRITE_LOCK:
        fd = os.open(LOG_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, payload)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(fd)


class FortbenchLogger(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        _write(_build_request_start(model, messages, kwargs))

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        _write(_build_record("success", kwargs, response_obj, start_time, end_time))

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        _write(_build_record("failure", kwargs, response_obj, start_time, end_time))

    async def async_log_pre_api_call(self, model, messages, kwargs):
        _write(_build_request_start(model, messages, kwargs))

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        _write(_build_record("success", kwargs, response_obj, start_time, end_time))

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        _write(_build_record("failure", kwargs, response_obj, start_time, end_time))


proxy_handler_instance = FortbenchLogger()
"""


def _upstream_served_model(row: dict) -> str:
    # The model id the upstream OpenAI-compatible server actually serves. The
    # local launcher exports LLAMACPP_SERVED_MODEL_NAME from this same value, so
    # the proxy must forward it rather than a hardcoded alias. llama.cpp ignores
    # the model field, but strict servers (mlx_lm.server, Rapid-MLX, vLLM)
    # reject a name they do not serve.
    model = os.path.expandvars(str(row.get("local_served_model_name") or "qwen"))
    if "$" in model:
        raise RuntimeError("served model references an unset environment variable")
    return model


def _config_yaml(row: dict) -> str:
    model_name = _proxy_model_name(row)
    upstream_model = _upstream_served_model(row)
    api_key = "dummy"
    if row.get("api_key_env"):
        api_key = "os.environ/" + str(row["api_key_env"])
    lines = [
        "model_list:",
        f"  - model_name: {json.dumps(model_name)}",
        "    litellm_params:",
        f"      model: {json.dumps('openai/' + upstream_model)}",
        f"      api_base: {json.dumps(_upstream_base_url(row))}",
        f"      api_key: {json.dumps(api_key)}",
        "litellm_settings:",
        "  telemetry: false",
        "  drop_params: true",
        f"  request_timeout: {proxy_request_timeout_seconds()}",
        f"  callbacks: [{json.dumps('fortbench_callback.proxy_handler_instance')}]",
    ]
    master_key = proxy_master_key()
    if master_key:
        lines.extend(
            [
                "general_settings:",
                f"  master_key: {json.dumps(master_key)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _wait_for_proxy_ready(
    expected_model: str,
    proc: subprocess.Popen[bytes] | None = None,
    timeout_seconds: int = 60,
) -> None:
    deadline = time.time() + timeout_seconds
    request = urllib.request.Request(_proxy_healthcheck_url(), headers=_proxy_auth_headers())
    last_error: str | None = None
    while time.time() < deadline:
        if proc is not None:
            rc = proc.poll()
            if rc is not None:
                last_error = f"proxy exited with code {rc}"
                break
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            model_ids = [item.get("id", "") for item in payload.get("data", [])]
            if expected_model in model_ids:
                return
            last_error = f"expected proxy model {expected_model!r}, got {model_ids!r}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"LiteLLM proxy not ready: {last_error or 'timed out'}")


def stop_proxy() -> None:
    pidfile = proxy_pid_path()
    pid = ""
    if pidfile.exists():
        try:
            pid = pidfile.read_text().strip()
        except Exception:
            pid = ""
    if pid:
        try:
            os.killpg(int(pid), signal.SIGTERM)
        except Exception:
            pass
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                os.kill(int(pid), 0)
            except OSError:
                break
            time.sleep(0.1)
        try:
            os.killpg(int(pid), signal.SIGKILL)
        except Exception:
            pass
    subprocess.run(["pkill", "-f", f"litellm.*--port {proxy_port()}"], check=False, capture_output=True)
    pidfile.unlink(missing_ok=True)


def start_proxy(row: dict) -> None:
    stop_proxy()
    root = proxy_root()
    root.mkdir(parents=True, exist_ok=True)
    proxy_callback_path().write_text(_callback_source())
    proxy_config_path().write_text(_config_yaml(row))
    proxy_log_path().write_text("")
    proxy_stdout_path().write_text("")

    for attempt in range(1, proxy_start_attempts() + 1):
        with proxy_stdout_path().open("ab", buffering=0) as log_handle:
            proc = subprocess.Popen(
                [
                    proxy_bin(),
                    "--config",
                    str(proxy_config_path()),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(proxy_port()),
                ],
                cwd=str(root),
                env={
                    **os.environ,
                    "FORTBENCH_LITELLM_LOG": str(proxy_log_path()),
                },
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        proxy_pid_path().write_text(f"{proc.pid}\n")
        try:
            _wait_for_proxy_ready(_proxy_model_name(row), proc=proc)
            return
        except Exception as exc:
            stop_proxy()
            if attempt >= proxy_start_attempts():
                tail = _proxy_stdout_tail()
                if tail:
                    raise RuntimeError(f"{exc}; proxy stdout tail: {tail}") from exc
                raise
            time.sleep(min(5.0, float(attempt)))


def snapshot_proxy_log() -> ProxyLogCursor:
    path = proxy_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return ProxyLogCursor(offset=path.stat().st_size)


def _parse_proxy_log_records(raw: str) -> tuple[list[dict[str, object]], int]:
    decoder = json.JSONDecoder()
    records: list[dict[str, object]] = []
    parse_errors = 0
    cursor = 0
    length = len(raw)

    while cursor < length:
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length:
            break
        try:
            record, next_cursor = decoder.raw_decode(raw, cursor)
        except json.JSONDecodeError:
            parse_errors += 1
            next_newline = raw.find("\n", cursor)
            next_object = raw.find("{", cursor + 1)
            candidates = [
                pos
                for pos in (
                    next_newline + 1 if next_newline != -1 else -1,
                    next_object if next_object != -1 else -1,
                )
                if pos > cursor
            ]
            if not candidates:
                break
            cursor = min(candidates)
            continue
        cursor = next_cursor
        if not isinstance(record, dict):
            parse_errors += 1
            continue
        records.append(record)

    return records, parse_errors


def collect_proxy_log(stage_dir: Path, started_at_epoch: float, cursor: ProxyLogCursor) -> dict[str, object]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = stage_dir / "protocol.jsonl"
    path = proxy_log_path()
    deadline = time.time() + proxy_log_quiet_timeout_seconds()
    stable_since: float | None = None
    last_size = -1
    drained_cleanly = False

    while True:
        size = path.stat().st_size if path.exists() else 0
        if size == last_size:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= proxy_log_quiet_period_seconds():
                drained_cleanly = True
                break
        else:
            stable_since = None
            last_size = size
        if time.time() >= deadline:
            break
        time.sleep(0.1)

    if not path.exists():
        raw = ""
    else:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(cursor.offset)
            raw = handle.read()

    records, parse_errors = _parse_proxy_log_records(raw)
    filtered_records: list[dict[str, object]] = []
    foreign_records = 0
    foreign_request_starts = 0
    foreign_finishes = 0
    for record in records:
        started = record.get("request_started_at_epoch")
        if isinstance(started, (int, float)) and float(started) + 1e-6 < started_at_epoch:
            foreign_records += 1
            if record.get("type") == "request_start":
                foreign_request_starts += 1
            elif record.get("type") in {"success", "failure"}:
                foreign_finishes += 1
            continue
        filtered_records.append(record)

    if filtered_records:
        protocol_path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in filtered_records)
        )

    request_start_records = [record for record in filtered_records if record.get("type") == "request_start"]
    finish_records = [record for record in filtered_records if record.get("type") in {"success", "failure"}]
    request_count = len(request_start_records)
    response_finish_count = len(finish_records)
    if response_finish_count > request_count:
        parse_errors += response_finish_count - request_count
    first_request_delay = None
    first_request_path = None
    first_request_method = None
    if request_start_records:
        first = request_start_records[0]
        first_request_path = first.get("route")
        if isinstance(first.get("request"), dict):
            first_request_method = first["request"].get("method")
        started = first.get("request_started_at_epoch")
        if isinstance(started, (int, float)):
            first_request_delay = max(0.0, float(started) - started_at_epoch)
    elif filtered_records:
        first = filtered_records[0]
        first_request_path = first.get("route")
        if isinstance(first.get("request"), dict):
            first_request_method = first["request"].get("method")
        started = first.get("request_started_at_epoch")
        if isinstance(started, (int, float)):
            first_request_delay = max(0.0, float(started) - started_at_epoch)
    total_upstream_seconds = 0.0
    for record in finish_records:
        duration = record.get("duration_seconds")
        if isinstance(duration, (int, float)):
            total_upstream_seconds += float(duration)

    summary = {
        "request_count": request_count,
        "response_finish_count": response_finish_count,
        "first_request_delay_seconds": first_request_delay,
        "first_request_method": first_request_method,
        "first_request_path": first_request_path,
        "total_upstream_seconds": round(total_upstream_seconds, 3),
        "log_write_errors": parse_errors,
        "drained_cleanly": drained_cleanly,
        "active_requests_at_stop": 0,
        "stream_event_count": 0,
        "foreign_record_count": foreign_records,
        "foreign_request_start_count": foreign_request_starts,
        "foreign_finish_count": foreign_finishes,
        "foreign_stream_event_count": 0,
    }
    (stage_dir / "protocol-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    path.write_text("")
    return summary
