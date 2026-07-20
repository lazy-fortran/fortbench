from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
import pwd
from dataclasses import dataclass
from pathlib import Path

from fortbench.litellm_proxy import collect_proxy_log, proxy_base_url, proxy_master_key, snapshot_proxy_log


@dataclass
class AgentResponse:
    ok: bool
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    text: str
    error: str | None = None
    artifacts: dict[str, str] | None = None
    protocol_summary: dict[str, object] | None = None


def _is_local_benchmark_row(row: dict) -> bool:
    return row.get("provider_class") == "local"


def _supports_reasoning(row: dict) -> bool:
    alias = (row.get("local_model_alias") or row.get("model") or "").lower()
    return (
        alias.startswith("qwen")
        or alias.startswith("gpt-oss")
        or alias.startswith("gemma-4")
        or alias.startswith("minimax")
    )


def _codex_reasoning_effort(row: dict) -> str | None:
    if row.get("reasoning_effort") is not None:
        return row.get("reasoning_effort")
    if row.get("provider_class") == "cloud":
        return None
    return "medium" if _supports_reasoning(row) else None


def _opencode_variant(row: dict) -> str | None:
    if row.get("variant") is not None:
        return row.get("variant")
    return "medium" if _supports_reasoning(row) else None


def _local_sampling_options(row: dict) -> dict[str, object]:
    alias = (row.get("local_model_alias") or row.get("model") or "").lower()
    if alias.startswith("qwen"):
        return {
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 20,
            "min_p": 0.0,
            "presence_penalty": 0.0,
            "repeat_penalty": 1.0,
        }
    if alias.startswith("gemma-4"):
        return {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
        }
    if alias.startswith("minimax"):
        return {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 40,
        }
    if alias.startswith("deepseek-v4"):
        # DeepSeek V4 official recommendation for local deployment.
        return {
            "temperature": 1.0,
            "top_p": 1.0,
        }
    if alias.startswith("devstral"):
        return {
            "temperature": 0.15,
        }
    if alias.startswith("mistral-small-4") or alias.startswith("mistral-large-3"):
        return {
            "temperature": 0.15,
            "top_p": 0.95,
        }
    if alias.startswith("nemotron"):
        return {
            "temperature": 1.0,
            "top_p": 0.95,
        }
    if alias.startswith("kimi") or alias.startswith("mimo") or alias.startswith("glm") or alias.startswith("trinity"):
        return {
            "temperature": 0.6,
            "top_p": 0.95,
        }
    if alias.startswith("gpt-oss"):
        return {}
    return {}


def _local_benchmark_user() -> str:
    preferred = os.environ.get("FORTBENCH_LOCAL_USER", "").strip()
    candidates = [
        preferred,
        "fortbench",
        os.environ.get("SUDO_USER", "").strip(),
        os.environ.get("USER", "").strip(),
        os.environ.get("LOGNAME", "").strip(),
        pwd.getpwuid(os.getuid()).pw_name,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            pwd.getpwnam(candidate)
        except KeyError:
            continue
        return candidate
    return preferred or "fortbench"


def _current_user_name() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def _agent_base_path() -> str:
    parts: list[str] = []
    extra = os.environ.get("FORTBENCH_AGENT_PATH_PREFIX", "").strip()
    if extra:
        parts.extend(part for part in extra.split(":") if part)
    for tool in ("codex", "node", "npm"):
        resolved = shutil.which(tool)
        if resolved:
            parts.append(str(Path(resolved).resolve().parent))
    shared_bun = os.environ.get("FORTBENCH_SHARED_BUN_BIN", "").strip()
    if shared_bun:
        parts.append(str(Path(shared_bun).resolve().parent))
    parts.extend(
        [
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
    )
    deduped: list[str] = []
    for part in parts:
        if part and part not in deduped:
            deduped.append(part)
    return ":".join(deduped)


def _opencode_command() -> list[str]:
    dev_repo = os.environ.get("FORTBENCH_OPENCODE_DEV_REPO", "").strip()
    bun = (
        os.environ.get("FORTBENCH_SHARED_BUN_BIN", "").strip()
        or shutil.which("bun")
        or str(Path.home() / ".bun" / "bin" / "bun")
    )
    if dev_repo:
        return [bun, "run", "--cwd", str(Path(dev_repo) / "packages" / "opencode"), "src/index.ts"]
    return [os.environ.get("FORTBENCH_OPENCODE_BIN", "opencode")]


def _codex_command() -> list[str]:
    explicit = os.environ.get("FORTBENCH_CODEX_BIN", "").strip()
    if explicit:
        return [explicit]
    resolved = shutil.which("codex")
    if resolved:
        return [resolved]
    native = (
        Path("/opt/homebrew/lib/node_modules/@openai/codex")
        / "node_modules"
        / "@openai"
        / "codex-darwin-arm64"
        / "vendor"
        / "aarch64-apple-darwin"
        / "codex"
        / "codex"
    )
    if native.exists():
        return [str(native)]
    return [os.environ.get("FORTBENCH_CODEX_WRAPPER_BIN", "codex")]


def _minimal_agent_env(home_dir: Path, extra_env: dict[str, str]) -> dict[str, str]:
    home_dir.mkdir(parents=True, exist_ok=True)
    home_dir.chmod(0o775)
    env = {
        "PATH": _agent_base_path(),
        "HOME": str(home_dir),
        "USER": _local_benchmark_user(),
        "LOGNAME": _local_benchmark_user(),
        "SHELL": "/bin/zsh",
        "TERM": "xterm-256color",
        "TMPDIR": "/tmp",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    env.update(extra_env)
    return env


def _local_server_base_url(row: dict) -> str:
    _ = row
    return proxy_base_url()


def _sudo_local_command(
    command: list[str],
    remote_cwd: Path,
    env: dict[str, str],
) -> list[str]:
    if _local_benchmark_user() == _current_user_name():
        remote = f"cd {shlex.quote(str(remote_cwd))} && env {' '.join(f'{key}={shlex.quote(value)}' for key, value in sorted(env.items()))} {shlex.join(command)}"
        return ["/bin/zsh", "-lc", remote]
    exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in sorted(env.items()))
    remote = f"cd {shlex.quote(str(remote_cwd))} && env {exports} {shlex.join(command)}"
    return [
        "sudo",
        "-n",
        "-iu",
        _local_benchmark_user(),
        "/bin/zsh",
        "-lc",
        remote,
    ]


def _benchmark_agent_home(agent: str) -> Path:
    root = os.environ.get("FORTBENCH_AGENT_HOME_ROOT", "").strip()
    if root:
        return Path(root) / agent
    return Path.home() / ".cache" / "fortbench" / "homes" / agent


def _write_benchmark_git_config(home_dir: Path, workspace: Path) -> Path:
    home_dir.mkdir(parents=True, exist_ok=True)
    gitconfig_path = home_dir / ".gitconfig"
    gitconfig_path.write_text(
        "\n".join(
            [
                "[safe]",
                f'\tdirectory = "{workspace}"',
                "",
            ]
        )
    )
    return gitconfig_path


def _write_codex_benchmark_config(
    config_dir: Path,
    workspace: Path,
    row: dict,
    base_url: str | None = None,
    home_dir: Path | None = None,
) -> dict[str, str]:
    config_dir.mkdir(parents=True, exist_ok=True)
    home_dir = home_dir or _benchmark_agent_home("codex")
    gitconfig_path = _write_benchmark_git_config(home_dir, workspace)
    catalog_path = config_dir / "local-models.json"
    config_path = config_dir / "config.toml"
    model_name = row.get("model", "qwen")
    reasoning_effort = _codex_reasoning_effort(row)
    supported_reasoning_levels = (
        [
            {"effort": "low", "description": "Fast responses with lighter reasoning"},
            {"effort": "medium", "description": "Balances speed and reasoning depth"},
            {"effort": "high", "description": "Greater reasoning depth for complex problems"},
        ]
        if reasoning_effort
        else [
            {"effort": "low", "description": "Fast responses"},
        ]
    )
    catalog = {
        "models": [
            {
                "slug": model_name,
                "display_name": f"{model_name} (benchmark)",
                "base_instructions": (
                    "You are running inside a benchmark harness in the task workspace."
                ),
                "context_window": 131072,
                "auto_compact_token_limit": 78643,
                "default_reasoning_level": reasoning_effort or "low",
                "supported_reasoning_levels": supported_reasoning_levels,
                "shell_type": "shell_command",
                "visibility": "list",
                "supported_in_api": True,
                "priority": 0,
                "supports_reasoning_summaries": False,
                "support_verbosity": False,
                "truncation_policy": {"mode": "tokens", "limit": 10000},
                "supports_parallel_tool_calls": True,
                "experimental_supported_tools": [],
                "input_modalities": ["text"],
                "prefer_websockets": False,
            }
        ]
    }
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    config_path.write_text(
        "\n".join(
            [
                f'model_catalog_json = "{catalog_path}"',
                "",
                "[model_providers.local]",
                'name = "Local llama.cpp"',
                f'base_url = "{base_url or _local_server_base_url(row)}"',
                *([f'api_key = "{proxy_master_key()}"'] if proxy_master_key() else []),
                'wire_api = "responses"',
                'stream_idle_timeout_ms = 1800000',
                'stream_max_retries = 10',
                "",
                "[profiles.local]",
                'model_provider = "local"',
                f'model = "{model_name}"',
                *( [f'model_reasoning_effort = "{reasoning_effort}"'] if reasoning_effort else [] ),
                'web_search = "disabled"',
                "",
                f'[projects."{workspace}"]',
                'trust_level = "trusted"',
                "",
            ]
        )
    )
    return _minimal_agent_env(
        home_dir,
        {
            "CODEX_HOME": str(config_dir),
            "CODEX_CONFIG_PATH": str(config_path),
            "GIT_CONFIG_GLOBAL": str(gitconfig_path),
        },
    )


def _write_codex_cloud_config(
    config_dir: Path,
    workspace: Path,
    row: dict,
    home_dir: Path | None = None,
) -> dict[str, str]:
    config_dir.mkdir(parents=True, exist_ok=True)
    home_dir = home_dir or _benchmark_agent_home("codex-cloud")
    gitconfig_path = _write_benchmark_git_config(home_dir, workspace)
    config_path = config_dir / "config.toml"
    model_name = row.get("model", "gpt-5.4-mini")
    reasoning_effort = _codex_reasoning_effort(row)
    # codex-cli >= 0.x dropped legacy `[profiles.X]` + `--profile`; top-level keys
    # (loaded from CODEX_HOME/config.toml) replace the dedicated profile. Top-level
    # bare keys must precede any table header or TOML attributes them to that table.
    lines = [
        f'model = "{model_name}"',
        'web_search = "disabled"',
    ]
    if reasoning_effort:
        lines.append(f'model_reasoning_effort = "{reasoning_effort}"')
    lines += [
        "",
        f'[projects."{workspace}"]',
        'trust_level = "trusted"',
        "",
        "[history]",
        'persistence = "save-all"',
        "",
    ]
    config_path.write_text("\n".join(lines))
    auth_src = Path.home() / ".codex" / "auth.json"
    auth_dst = config_dir / "auth.json"
    if auth_src.exists():
        shutil.copy2(auth_src, auth_dst)
        auth_dst.chmod(0o600)
    return _minimal_agent_env(
        home_dir,
        {
            "CODEX_HOME": str(config_dir),
            "CODEX_CONFIG_PATH": str(config_path),
            "GIT_CONFIG_GLOBAL": str(gitconfig_path),
        },
    )


def _write_opencode_benchmark_config(
    config_dir: Path,
    row: dict,
    base_url: str | None = None,
    home_dir: Path | None = None,
) -> tuple[dict[str, str], str]:
    home_dir = home_dir or _benchmark_agent_home("opencode")
    xdg_root = home_dir / ".config"
    cache_root = home_dir / ".cache"
    data_root = home_dir / ".local" / "share"
    state_root = home_dir / ".local" / "state"
    config_path = xdg_root / "opencode" / "opencode.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)
    served_name = os.path.expandvars(str(row.get("local_served_model_name") or "qwen"))
    if "$" in served_name:
        raise RuntimeError("served model references an unset environment variable")
    provider_id = "local"
    model_id = f"{provider_id}/{served_name}"
    sampling_options = _local_sampling_options(row)
    model_config = {
        "name": served_name,
        "tool_call": True,
        "limit": {
            "context": 131072,
            "output": 32768,
        },
        "options": sampling_options,
    }
    if _supports_reasoning(row):
        model_config["reasoning"] = True
        model_config["interleaved"] = {"field": "reasoning_content"}
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": model_id,
        "share": "disabled",
        "autoupdate": False,
        "permission": "allow",
        "experimental": {"openTelemetry": False},
        "agent": {
            "title": {"disable": True},
        },
        "disabled_providers": ["exa", "openai", "anthropic", "google", "mistral", "groq", "xai", "ollama"],
        "provider": {
            provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "llama.cpp",
                "options": {
                    "baseURL": base_url or _local_server_base_url(row),
                },
                "models": {
                    served_name: model_config
                },
            }
        },
    }
    if proxy_master_key():
        config["provider"][provider_id]["options"]["apiKey"] = proxy_master_key()
    config_text = json.dumps(config, indent=2) + "\n"
    config_path.write_text(config_text)
    (config_dir / "opencode.json").write_text(config_text)
    return (
        _minimal_agent_env(
            home_dir,
            {
                "HOME": str(home_dir),
                "XDG_CONFIG_HOME": str(xdg_root),
                "XDG_CACHE_HOME": str(cache_root),
                "XDG_DATA_HOME": str(data_root),
                "XDG_STATE_HOME": str(state_root),
                "OPENCODE_CONFIG": str(config_path),
            },
        ),
        model_id,
    )


def _prepare_shared_run_tree(run_dir: Path) -> None:
    subprocess.run(["chgrp", "-R", "staff", str(run_dir)], check=False, capture_output=True)
    subprocess.run(["chmod", "-R", "g+rwX", str(run_dir)], check=False, capture_output=True)

def _run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
    process_cwd: Path | None = None,
    stdin_text: str | None = None,
) -> AgentResponse:
    started = time.time()
    launch_cwd = process_cwd or cwd
    proc = subprocess.Popen(
        command,
        cwd=str(launch_cwd),
        env=env,
        text=True,
        errors="replace",
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = started + timeout_seconds
    while True:
        remaining = max(0.0, deadline - time.time())
        if remaining <= 0:
            termination_note = _terminate_process(proc)
            stdout, stderr = proc.communicate(stdin_text)
            duration = time.time() - started
            return AgentResponse(
                ok=False,
                command=command,
                returncode=124,
                stdout=stdout,
                stderr=_append_note(stderr, termination_note),
                duration_seconds=duration,
                text=_extract_text(command[0], stdout, _append_note(stderr, termination_note)),
                error=_append_error(f"timed out after {timeout_seconds} seconds", termination_note),
            )
        try:
            stdout, stderr = proc.communicate(stdin_text, timeout=min(5, remaining))
            duration = time.time() - started
            return AgentResponse(
                ok=proc.returncode == 0,
                command=command,
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                text=_extract_text(command[0], stdout, stderr),
                error=None if proc.returncode == 0 else f"command failed with exit code {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            continue


def _append_note(stderr: str, note: str | None) -> str:
    if not note:
        return stderr
    if stderr:
        return f"{stderr.rstrip()}\n{note}\n"
    return f"{note}\n"


def _append_error(error: str, note: str | None) -> str:
    if not note:
        return error
    return f"{error}; {note}"
def _write_stage_files(
    run_dir: Path,
    stage_index: int,
    prompt: str,
    response: AgentResponse,
    protocol_summary: dict[str, object] | None = None,
) -> dict[str, str]:
    stage_dir = run_dir / "stages" / f"stage-{stage_index}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "prompt.txt").write_text(prompt)
    (stage_dir / "command.json").write_text(json.dumps(response.command, indent=2) + "\n")
    (stage_dir / "stdout.log").write_text(response.stdout)
    (stage_dir / "stderr.log").write_text(response.stderr)
    if protocol_summary is not None:
        (stage_dir / "protocol-summary.json").write_text(json.dumps(response.protocol_summary, indent=2) + "\n")
    archive_prefix = "row-artifacts.tar.zst::"
    artifacts = {
        "prompt_path": f"{archive_prefix}stages/stage-{stage_index}/prompt.txt",
        "command_path": f"{archive_prefix}stages/stage-{stage_index}/command.json",
        "stdout_path": f"{archive_prefix}stages/stage-{stage_index}/stdout.log",
        "stderr_path": f"{archive_prefix}stages/stage-{stage_index}/stderr.log",
    }
    protocol_log = stage_dir / "protocol.jsonl"
    if protocol_log.exists():
        artifacts["protocol_path"] = f"{archive_prefix}stages/stage-{stage_index}/protocol.jsonl"
    if protocol_summary is not None:
        artifacts["protocol_summary_path"] = f"{archive_prefix}stages/stage-{stage_index}/protocol-summary.json"
    return artifacts


def _write_json_protocol_log(stage_dir: Path, records: list[dict]) -> None:
    if not records:
        return
    stage_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = stage_dir / "protocol.jsonl"
    with protocol_path.open("w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _summarize_codex_protocol(records: list[dict], log_write_errors: int) -> dict[str, object]:
    assistant_messages = 0
    reasoning_items = 0
    function_calls = 0
    result_events = 0
    event_types: list[str] = []
    for record in records:
        event = record.get("event")
        if isinstance(event, dict):
            event_type = event.get("type")
            if isinstance(event_type, str):
                event_types.append(event_type)
            if event_type == "response_item":
                payload = event.get("payload")
                if isinstance(payload, dict):
                    payload_type = payload.get("type")
                    if payload_type == "reasoning":
                        reasoning_items += 1
                    elif payload_type == "function_call":
                        function_calls += 1
                    elif payload_type == "message":
                        assistant_messages += 1
            elif event_type == "event_msg":
                payload = event.get("payload")
                if isinstance(payload, dict) and payload.get("type") == "agent_message":
                    assistant_messages += 1
            elif event_type == "result":
                result_events += 1
    return {
        "kind": "codex-cli",
        "record_count": len(records),
        "assistant_message_count": assistant_messages,
        "reasoning_item_count": reasoning_items,
        "function_call_count": function_calls,
        "result_event_count": result_events,
        "first_event_type": event_types[0] if event_types else "",
        "last_event_type": event_types[-1] if event_types else "",
        "log_write_errors": log_write_errors,
    }


def _collect_codex_cli_protocol(stage_dir: Path, stdout: str, stderr: str) -> dict[str, object]:
    records: list[dict] = []
    parse_errors = 0
    for index, line in enumerate(stdout.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            parse_errors += 1
            records.append({"record_type": "parse_error", "stream": "stdout", "line_number": index, "raw": stripped})
            continue
        records.append({"record_type": "event", "stream": "stdout", "line_number": index, "event": event})
    if stderr.strip():
        records.append({"record_type": "stderr_excerpt", "text": stderr.strip()})
    _write_json_protocol_log(stage_dir, records)
    return _summarize_codex_protocol(records, parse_errors)


def _collect_claude_cli_protocol(stage_dir: Path, stdout: str, stderr: str) -> dict[str, object]:
    records: list[dict] = []
    parse_errors = 0
    payload: dict | None = None
    stripped = stdout.strip()
    if stripped:
        try:
            payload = json.loads(stripped)
            records.append({"record_type": "result", "payload": payload})
        except json.JSONDecodeError:
            parse_errors += 1
            records.append({"record_type": "parse_error", "stream": "stdout", "raw": stripped})
    if stderr.strip():
        records.append({"record_type": "stderr_excerpt", "text": stderr.strip()})
    _write_json_protocol_log(stage_dir, records)
    usage = payload.get("usage") if isinstance(payload, dict) else None
    result_text = payload.get("result") if isinstance(payload, dict) else None
    return {
        "kind": "claude-cli",
        "record_count": len(records),
        "log_write_errors": parse_errors,
        "is_error": bool(payload.get("is_error")) if isinstance(payload, dict) else False,
        "stop_reason": payload.get("stop_reason", "") if isinstance(payload, dict) else "",
        "duration_ms": payload.get("duration_ms") if isinstance(payload, dict) else None,
        "num_turns": payload.get("num_turns") if isinstance(payload, dict) else None,
        "result_length": len(result_text) if isinstance(result_text, str) else 0,
        "input_tokens": usage.get("input_tokens") if isinstance(usage, dict) else None,
        "output_tokens": usage.get("output_tokens") if isinstance(usage, dict) else None,
    }


def _iter_json_nodes(value):
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_nodes(item)


def _codex_event_text(event: dict) -> str | None:
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "agent_message":
        text = item.get("text")
        if isinstance(text, str):
            return text

    if event.get("type") == "event_msg":
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("type") == "agent_message":
            text = payload.get("message")
            if isinstance(text, str):
                return text

    if event.get("type") == "response_item":
        payload = event.get("payload")
        if isinstance(payload, dict):
            if payload.get("type") == "message":
                content = payload.get("content", [])
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                            text = part.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                    if parts:
                        return "\n".join(parts)
            elif payload.get("type") == "reasoning":
                content = payload.get("content", [])
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "reasoning_text":
                            text = part.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                    if parts:
                        return "\n".join(parts)
    return None


def _terminate_process(
    proc: subprocess.Popen,
) -> str | None:
    notes: list[str] = []
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        notes.append("sent local SIGTERM")
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        note = f"killpg fallback after PermissionError: {exc}"
        try:
            proc.terminate()
        except ProcessLookupError:
            notes.append(note)
            pass
        except Exception as fallback_exc:
            notes.append(f"{note}; terminate fallback failed: {fallback_exc}")
        else:
            notes.append(note)
        try:
            proc.wait(timeout=5)
            return "; ".join(notes) if notes else None
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                notes.append("used proc.kill fallback")
            except ProcessLookupError:
                pass
            except Exception as kill_exc:
                notes.append(f"proc.kill fallback failed: {kill_exc}")
    return "; ".join(notes) if notes else None


def _extract_text(agent: str, stdout: str, stderr: str) -> str:
    if agent == "opencode":
        try:
            last = None
            for line in stdout.splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("type") == "text":
                    last = event["part"]["text"]
                elif event.get("type") == "result":
                    last = event.get("result", last)
            return last or stdout.strip()
        except Exception:
            return stdout.strip() or stderr.strip()
    if agent == "qwen":
        try:
            events = json.loads(stdout)
            last = ""
            for event in events:
                if event.get("type") == "assistant":
                    content = event.get("message", {}).get("content", [])
                    for part in content:
                        if part.get("type") == "text":
                            last = part.get("text", last)
                elif event.get("type") == "result":
                    last = event.get("result", last)
            return last or stdout.strip()
        except Exception:
            return stdout.strip() or stderr.strip()
    if agent == "claude":
        try:
            payload = json.loads(stdout)
            return payload.get("result", stdout.strip())
        except Exception:
            return stdout.strip() or stderr.strip()
    if agent == "codex":
        last = ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            for node in _iter_json_nodes(event):
                text = _codex_event_text(node)
                if text:
                    last = text
        return last or stdout.strip() or stderr.strip()
    return stdout.strip() or stderr.strip()


class BaseAdapter:
    name: str

    def stage(self, stage_index: int, prompt: str, workspace: Path, run_dir: Path, row: dict, timeout_seconds: int) -> AgentResponse:
        raise NotImplementedError


class OpenCodeAdapter(BaseAdapter):
    name = "opencode"

    def stage(self, stage_index: int, prompt: str, workspace: Path, run_dir: Path, row: dict, timeout_seconds: int) -> AgentResponse:
        env = None
        launcher_dir = run_dir / ".launcher"
        launcher_dir.mkdir(parents=True, exist_ok=True)
        command = [*_opencode_command(), "run", "--dir", str(workspace), "--format", "json"]
        model = row.get("model")
        stage_dir = run_dir / "stages" / f"stage-{stage_index}"
        if _is_local_benchmark_row(row):
            env, model = _write_opencode_benchmark_config(
                run_dir / ".opencode-benchmark",
                row,
                home_dir=run_dir / ".opencode-home",
            )
            _prepare_shared_run_tree(run_dir)
        if model:
            command.extend(["--model", model])
        variant = _opencode_variant(row)
        if variant:
            command.extend(["--variant", variant])
        command.append(prompt)
        if _is_local_benchmark_row(row) and env is not None:
            command = _sudo_local_command(command, launcher_dir, env)
            env = None
        trace_started = time.time()
        trace_cursor = snapshot_proxy_log() if _is_local_benchmark_row(row) else None
        response = _run_command(
            command,
            workspace,
            timeout_seconds,
            env=env,
            process_cwd=launcher_dir,
        )
        summary = collect_proxy_log(stage_dir, trace_started, trace_cursor) if _is_local_benchmark_row(row) else None
        response.protocol_summary = summary
        response.artifacts = _write_stage_files(run_dir, stage_index, prompt, response, summary)
        return response


class QwenCodeAdapter(BaseAdapter):
    name = "qwen"

    def stage(self, stage_index: int, prompt: str, workspace: Path, run_dir: Path, row: dict, timeout_seconds: int) -> AgentResponse:
        command = [
            "qwen",
            "--approval-mode",
            "yolo",
            "--output-format",
            "json",
        ]
        model = row.get("model")
        if model and not _is_local_benchmark_row(row):
            command.extend(["--model", model])
        openai_base_url = row.get("openai_base_url")
        if openai_base_url:
            command.extend(["--openai-base-url", openai_base_url, "--openai-api-key", row.get("openai_api_key", "dummy")])
        command.append(prompt)
        response = _run_command(command, workspace, timeout_seconds)
        response.artifacts = _write_stage_files(run_dir, stage_index, prompt, response)
        return response


class ClaudeCodeAdapter(BaseAdapter):
    name = "claude"

    def stage(self, stage_index: int, prompt: str, workspace: Path, run_dir: Path, row: dict, timeout_seconds: int) -> AgentResponse:
        launcher_dir = run_dir / ".launcher"
        launcher_dir.mkdir(parents=True, exist_ok=True)
        stage_dir = run_dir / "stages" / f"stage-{stage_index}"
        command = [
            "claude",
            "--print",
            "--output-format",
            "json",
            "--setting-sources",
            "user",
            "--permission-mode",
            "bypassPermissions",
            "--add-dir",
            str(workspace),
        ]
        model = row.get("model")
        if model:
            command.extend(["--model", model])
        effort = row.get("effort")
        if effort:
            command.extend(["--effort", effort])
        response = _run_command(
            command,
            workspace,
            timeout_seconds,
            process_cwd=launcher_dir,
            stdin_text=prompt,
        )
        summary = _collect_claude_cli_protocol(stage_dir, response.stdout, response.stderr)
        response.protocol_summary = summary
        response.artifacts = _write_stage_files(run_dir, stage_index, prompt, response, summary)
        return response


class CodexAdapter(BaseAdapter):
    name = "codex"

    def stage(self, stage_index: int, prompt: str, workspace: Path, run_dir: Path, row: dict, timeout_seconds: int) -> AgentResponse:
        env = None
        launcher_dir = run_dir / ".launcher"
        launcher_dir.mkdir(parents=True, exist_ok=True)
        stage_dir = run_dir / "stages" / f"stage-{stage_index}"
        if _is_local_benchmark_row(row):
            env = _write_codex_benchmark_config(
                run_dir / ".codex-benchmark",
                workspace,
                row,
                home_dir=run_dir / ".codex-home",
            )
            _prepare_shared_run_tree(run_dir)
        else:
            env = _write_codex_cloud_config(
                run_dir / ".codex-cloud" / f"stage-{stage_index}",
                workspace,
                row,
                home_dir=run_dir / ".codex-home",
            )
            _prepare_shared_run_tree(run_dir)
        command = _codex_command()
        if _is_local_benchmark_row(row):
            command.extend(
                [
                    "-c",
                    'model_provider="local"',
                    "-c",
                    f'model="{row.get("model", "qwen")}"',
                    "-c",
                    f'model_providers.local.base_url="{_local_server_base_url(row)}"',
                    "-c",
                    'model_providers.local.wire_api="responses"',
                    "-c",
                    'web_search="disabled"',
                    "-c",
                    'shell_environment_policy.inherit="none"',
                ]
            )
            if proxy_master_key():
                command.extend(["-c", f'model_providers.local.api_key="{proxy_master_key()}"'])
        # cloud rows: model/web_search/reasoning load from CODEX_HOME/config.toml
        # (written by _write_codex_cloud_config) plus the --model flag below; the
        # legacy --profile selector was removed in codex-cli 0.x.
        model_provider = row.get("model_provider")
        if model_provider:
            command.extend(["-c", f'model_provider="{model_provider}"'])
        reasoning_effort = _codex_reasoning_effort(row)
        if reasoning_effort:
            command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        command.extend([
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--cd",
            str(workspace),
            "--ephemeral",
            "--json",
        ])
        model = row.get("model")
        if model and not _is_local_benchmark_row(row):
            command.extend(["--model", model])
        command.append("--")
        command.append(prompt)
        if env is not None:
            command = _sudo_local_command(command, launcher_dir, env)
            env = None
        trace_started = time.time()
        trace_cursor = snapshot_proxy_log() if _is_local_benchmark_row(row) else None
        response = _run_command(
            command,
            workspace,
            timeout_seconds,
            env=env,
            process_cwd=launcher_dir,
        )
        summary = collect_proxy_log(stage_dir, trace_started, trace_cursor) if _is_local_benchmark_row(row) else _collect_codex_cli_protocol(stage_dir, response.stdout, response.stderr)
        response.protocol_summary = summary
        response.artifacts = _write_stage_files(run_dir, stage_index, prompt, response, summary)
        return response


class MistralVibeAdapter(BaseAdapter):
    name = "vibe"

    def stage(self, stage_index: int, prompt: str, workspace: Path, run_dir: Path, row: dict, timeout_seconds: int) -> AgentResponse:
        vibe_model = row.get("vibe_model")
        if vibe_model:
            _set_vibe_active_model(vibe_model)
        command = [
            "vibe",
            "-p",
            prompt,
            "--auto-approve",
            "--output",
            "json",
        ]
        response = _run_command(command, workspace, timeout_seconds)
        response.artifacts = _write_stage_files(run_dir, stage_index, prompt, response)
        return response


def _set_vibe_active_model(model_alias: str) -> None:
    import re
    config_path = Path.home() / ".vibe" / "config.toml"
    if not config_path.exists():
        return
    text = config_path.read_text()
    text = re.sub(r'^active_model\s*=\s*"[^"]*"', f'active_model = "{model_alias}"', text, count=1, flags=re.MULTILINE)
    config_path.write_text(text)


class AiderAdapter(BaseAdapter):
    name = "aider"

    def stage(self, stage_index: int, prompt: str, workspace: Path, run_dir: Path, row: dict, timeout_seconds: int) -> AgentResponse:
        history = run_dir / "aider.chat.history.md"
        command = [
            "aider",
            "--yes-always",
            "--no-pretty",
            "--no-fancy-input",
            "--no-auto-commits",
            "--no-dirty-commits",
            "--no-show-model-warnings",
            "--no-check-model-accepts-settings",
            "--message",
            prompt,
            "--exit",
            "--chat-history-file",
            str(history),
        ]
        model = row.get("model") or "openai/qwen"
        command.extend(["--model", model])
        api_base = row.get("openai_api_base")
        if api_base:
            command.extend(["--openai-api-base", api_base, "--openai-api-key", row.get("openai_api_key", "dummy")])
        return _run_command(command, workspace, timeout_seconds)


def build_adapter(name: str) -> BaseAdapter:
    mapping = {
        "opencode": OpenCodeAdapter,
        "aider": AiderAdapter,
        "qwen": QwenCodeAdapter,
        "claude": ClaudeCodeAdapter,
        "codex": CodexAdapter,
        "vibe": MistralVibeAdapter,
    }
    adapter_cls = mapping.get(name)
    if adapter_cls is None:
        raise ValueError(f"unsupported adapter: {name}")
    return adapter_cls()
