from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import textwrap
import time
import traceback
import urllib.request
import socket
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from fortbench.adapters import AgentResponse, build_adapter, _local_benchmark_user
from fortbench.judges import run_claude_judge, run_codex_judge
from fortbench.litellm_proxy import prepare_proxy_root, proxy_root, start_proxy, stop_proxy
from fortbench.suite_config import excluded_task_ids, excluded_task_reasons

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVSTRAL_SCRIPTS = Path(os.environ.get("FORTBENCH_SCRIPTS_DIR", ""))
LOCAL_BACKEND_NAME = "llamacpp"
SYSTEM_CONFIG_FILENAME = "system-config.json"
ARCHIVE_SKIP_PREFIXES = (
    (".codex-home",),
    (".codex-cloud",),
    (".opencode-home",),
    (".launcher",),
    (".codex-benchmark", ".tmp"),
    (".codex-benchmark", "tmp"),
    (".codex-benchmark", "memories"),
    (".codex-benchmark", "shell_snapshots"),
    (".opencode-benchmark", ".tmp"),
    (".opencode-benchmark", "tmp"),
    (".opencode-benchmark", "node_modules"),
)


@dataclass
class AcceptanceResult:
    ok: bool
    command_results: list[dict]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def render_command(template: str, workspace: Path, task_dir: Path) -> str:
    return template.format(workspace=workspace, task_dir=task_dir)


def run_shell(command: str, cwd: Path, timeout_seconds: int = 600) -> dict:
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "duration_seconds": round(time.time() - started, 2),
        "ok": proc.returncode == 0,
    }


def clone_workspace(task: dict, workspace: Path) -> None:
    clone_workspace_at(task["repo_url"], task["base_commit"], workspace)


def clone_workspace_at(repo_url: str, commit: str, workspace: Path) -> None:
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, 4):
        shutil.rmtree(workspace, ignore_errors=True)
        try:
            subprocess.run(["git", "clone", repo_url, str(workspace)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", commit], cwd=str(workspace), check=True, capture_output=True, text=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            shutil.rmtree(workspace, ignore_errors=True)
            if attempt < 3:
                time.sleep(2)
    if last_error is None:
        raise RuntimeError(f"failed to clone {repo_url} at {commit}")
    stderr = (last_error.stderr or "").strip()
    stdout = (last_error.stdout or "").strip()
    detail = stderr or stdout or str(last_error)
    raise RuntimeError(
        f"git workspace bootstrap failed for {repo_url} at {commit} after 3 attempts: {detail}"
    )


def run_setup(task: dict, workspace: Path, task_dir: Path) -> list[dict]:
    results = []
    for command in task.get("setup_commands", []):
        rendered = render_command(command, workspace, task_dir)
        results.append(run_shell(rendered, workspace))
    return results


def run_acceptance(task: dict, workspace: Path, task_dir: Path) -> AcceptanceResult:
    results = []
    for command in task["acceptance_commands"]:
        rendered = render_command(command, workspace, task_dir)
        results.append(run_shell(rendered, workspace))
    return AcceptanceResult(ok=all(item["ok"] for item in results), command_results=results)


def _short_text_block(text: str, max_lines: int = 12, max_chars: int = 700) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return "(no output)"
    clipped = "\n".join(lines[:max_lines])
    if len(clipped) > max_chars:
        clipped = clipped[: max_chars - 3].rstrip() + "..."
    return clipped


def _format_acceptance_feedback(acceptance: AcceptanceResult | None) -> str:
    if acceptance is None:
        return "No prior acceptance feedback."
    lines = [f"Overall acceptance: {'pass' if acceptance.ok else 'fail'}"]
    for idx, result in enumerate(acceptance.command_results, start=1):
        lines.append(
            f"Command {idx}: `{result['command']}` -> exit {result['returncode']} in {result['duration_seconds']:.2f}s"
        )
        excerpt = _short_text_block(f"{result.get('stdout', '')}\n{result.get('stderr', '')}")
        lines.append("Output excerpt:")
        lines.append(textwrap.indent(excerpt, "    "))
    return "\n".join(lines)


def _format_previous_attempt(previous_stage: dict | None) -> str:
    if previous_stage is None:
        return "No previous attempt."
    agent_status = "ok" if previous_stage.get("agent_ok") else "failed"
    agent_error = previous_stage.get("agent_error") or "none"
    acceptance_status = "pass" if previous_stage.get("acceptance_ok") else "fail"
    return "\n".join(
        [
            f"- Agent status: {agent_status}",
            f"- Agent error: {agent_error}",
            f"- Acceptance after that attempt: {acceptance_status}",
        ]
    )


def stage_prompt(
    task: dict,
    stage_index: int,
    acceptance: AcceptanceResult | None,
    previous_stage: dict | None = None,
) -> str:
    header = f"""You are working on a frozen benchmark task in a git worktree.

Task id: {task["id"]}
Issue URL: {task["issue_url"]}
Title: {task["title"]}

Issue body:
{task["issue_body"]}

Acceptance rubric for this benchmark task:
{task.get("acceptance_hint", "No extra acceptance hint provided.")}
"""
    if stage_index == 1:
        return header + """

Stage 1:
- Apply the smallest direct fix that matches the stated issue and expected behavior.
- Modify only the task repository in the current working directory.
- Use only local commands, and prefer one-shot commands over interactive sessions.
- Do not create git commits or add new tests unless the task explicitly requires them.
- If there is a cheap direct command that specifically checks the stated regression, run it once before exiting.
- Do not run the full project test suite.
- Explain briefly what changed, then exit. FortBench will run the full deterministic acceptance checks after you exit.
"""
    previous_attempt = _format_previous_attempt(previous_stage)
    feedback = _format_acceptance_feedback(acceptance)
    if stage_index == 2:
        return header + f"""

Previous attempt summary:
{previous_attempt}

Stage 2: targeted recovery.

- Do not restart from scratch.
- Identify the single concrete mismatch still blocking acceptance.
- Change only the code path most directly responsible for that mismatch.
- If there is a cheap direct command that checks that exact blocker, run it once.
- Do not refactor, broaden scope, or add unrelated cleanup.
- Explain briefly what changed, then exit.

Acceptance feedback summary:
{feedback}
"""
    return header + f"""

Previous attempt summary:
{previous_attempt}

Stage 3: final recovery pass.

- Focus on the narrowest still-failing acceptance condition.
- Assume the remaining blocker is an incomplete or misdiagnosed root cause.
- Make the smallest final repair that directly addresses the current deterministic failure.
- If there is a cheap direct command that checks that exact blocker, run it once.
- Prefer surgical edits over new scaffolding.
- Preserve already-working behavior.
- Do not repeat a broad exploratory approach.
- Explain briefly what changed, then exit.

Acceptance feedback summary:
{feedback}
"""


def stage_record(stage_index: int, response: AgentResponse, setup_results: list[dict], acceptance: AcceptanceResult) -> dict:
    return {
        "stage": stage_index,
        "agent_ok": response.ok,
        "agent_error": response.error,
        "agent_text": response.text,
        "agent_stdout_excerpt": _short_text_block(response.stdout),
        "agent_stderr_excerpt": _short_text_block(response.stderr),
        "agent_artifacts": response.artifacts or {},
        "agent_command": response.command,
        "agent_duration_seconds": round(response.duration_seconds, 2),
        "protocol_summary": response.protocol_summary or {},
        "setup_results": setup_results,
        "acceptance_ok": acceptance.ok,
        "acceptance": asdict(acceptance),
    }


def assert_local_stage_healthy(row: dict, stage_index: int, response: AgentResponse) -> None:
    summary = response.protocol_summary or {}
    if row.get("provider_class") == "local" and not summary:
        raise RuntimeError(f"local stage {stage_index} for {row['name']} is missing protocol summary")
    if summary and summary.get("log_write_errors", 0):
        raise RuntimeError(
            f"{row.get('provider_class', 'unknown')} stage {stage_index} for {row['name']} "
            f"had {summary['log_write_errors']} protocol log write errors"
        )
    if row.get("provider_class") != "local":
        return
    if summary.get("request_count", 0) <= 0:
        raise RuntimeError(f"local stage {stage_index} for {row['name']} made zero backend requests")
    if summary.get("drained_cleanly") is False:
        raise RuntimeError(
            f"local stage {stage_index} for {row['name']} did not drain cleanly "
            f"(active_requests_at_stop={summary.get('active_requests_at_stop')})"
        )
    foreign_request_starts = summary.get("foreign_request_start_count")
    if foreign_request_starts is None:
        foreign_request_starts = summary.get("foreign_record_count", 0)
    if foreign_request_starts:
        raise RuntimeError(
            f"local stage {stage_index} for {row['name']} captured {foreign_request_starts} "
            "foreign request-start trace records"
        )


def write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _parse_key_value_lines(text: str, separator: str = ":") -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if separator not in line:
            continue
        key, value = line.split(separator, 1)
        key = key.strip()
        value = value.strip()
        if key:
            data[key] = value
    return data


def _run_text(command: list[str]) -> dict[str, object]:
    try:
        proc = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _run_json(command: list[str]) -> dict[str, object]:
    result = _run_text(command)
    stdout = str(result.get("stdout", ""))
    parsed: dict[str, object] = {}
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = {}
    result["json"] = parsed
    return result


def _extract_mib(text: str) -> int | None:
    match = re.search(r"(\d+)\s*MiB", text)
    if not match:
        return None
    return int(match.group(1))


def collect_linux_system_config() -> dict[str, object]:
    os_release_path = Path("/etc/os-release")
    os_release: dict[str, str] = {}
    if os_release_path.exists():
        for line in os_release_path.read_text().splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os_release[key] = value.strip().strip('"')

    lscpu_raw = _run_text(["lscpu"])
    cpu_fields = _parse_key_value_lines(str(lscpu_raw["stdout"]))

    mem_total_kib = 0
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        for line in meminfo_path.read_text().splitlines():
            if not line.startswith("MemTotal:"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                mem_total_kib = int(parts[1])
            break

    nvidia_version_path = Path("/proc/driver/nvidia/version")
    nvidia_version = nvidia_version_path.read_text().strip() if nvidia_version_path.exists() else ""
    driver_match = re.search(r"Kernel Module\s+([0-9.]+)", nvidia_version)
    driver_version = driver_match.group(1) if driver_match else ""

    gpu_infos: list[dict[str, str]] = []
    gpu_root = Path("/proc/driver/nvidia/gpus")
    if gpu_root.exists():
        for info_path in sorted(gpu_root.glob("*/information")):
            gpu_infos.append(_parse_key_value_lines(info_path.read_text()))

    nvidia_smi_query = _run_text(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    vram_total_mib = None
    for line in str(nvidia_smi_query.get("stdout", "")).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            vram_total_mib = _extract_mib(parts[2])
            break

    return {
        "platform": platform.system().lower(),
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "os_release": {
            key.lower(): value
            for key, value in os_release.items()
            if key in {"PRETTY_NAME", "NAME", "VERSION", "VERSION_ID", "VERSION_CODENAME", "ID", "DEBIAN_VERSION_FULL"}
        },
        "cpu": {
            "architecture": cpu_fields.get("Architecture", ""),
            "cpu_count": int(cpu_fields.get("CPU(s)", "0") or 0),
            "model_name": cpu_fields.get("Model name", ""),
            "threads_per_core": int(cpu_fields.get("Thread(s) per core", "0") or 0),
            "cores_per_socket": int(cpu_fields.get("Core(s) per socket", "0") or 0),
            "sockets": int(cpu_fields.get("Socket(s)", "0") or 0),
            "vendor_id": cpu_fields.get("Vendor ID", ""),
        },
        "memory": {
            "mem_total_kib": mem_total_kib,
            "mem_total_gib": round(mem_total_kib / 1024 / 1024, 2) if mem_total_kib else 0.0,
        },
        "gpu": {
            "driver_version": driver_version,
            "devices": gpu_infos,
            "nvidia_smi": _run_text(["nvidia-smi"]),
            "nvidia_smi_query": nvidia_smi_query,
            "nvidia_smi_list": _run_text(["nvidia-smi", "-L"]),
            "vram_total_mib": vram_total_mib,
            "vram_total_gib": round(vram_total_mib / 1024, 2) if vram_total_mib else None,
        },
    }


def collect_macos_system_config() -> dict[str, object]:
    sw_vers = _parse_key_value_lines(_run_text(["sw_vers"])["stdout"])
    hardware_raw = _run_json(["system_profiler", "SPHardwareDataType", "-json"])
    display_raw = _run_json(["system_profiler", "SPDisplaysDataType", "-json"])
    hardware_data = hardware_raw.get("json", {}).get("SPHardwareDataType", [{}])
    display_data = display_raw.get("json", {}).get("SPDisplaysDataType", [{}])
    hardware = hardware_data[0] if isinstance(hardware_data, list) and hardware_data else {}
    display = display_data[0] if isinstance(display_data, list) and display_data else {}

    logical_cpu = int(_run_text(["sysctl", "-n", "hw.logicalcpu"])["stdout"] or 0)
    physical_cpu = int(_run_text(["sysctl", "-n", "hw.physicalcpu"])["stdout"] or 0)
    mem_total_kib = int(int(_run_text(["sysctl", "-n", "hw.memsize"])["stdout"] or 0) / 1024)
    brand_string = _run_text(["sysctl", "-n", "machdep.cpu.brand_string"])["stdout"]
    architecture = _run_text(["sysctl", "-n", "hw.machine"])["stdout"] or platform.machine()
    gpu_cores = int(display.get("sppci_cores", "0") or 0)
    gpu_name = display.get("sppci_model") or display.get("_name") or hardware.get("chip_type", "")
    gpu_vendor = display.get("spdisplays_vendor", "")
    memory_mode = "unified" if str(hardware.get("chip_type", "")).startswith("Apple") else "unknown"
    shared_memory_gib = round(mem_total_kib / 1024 / 1024, 2) if mem_total_kib else 0.0

    return {
        "platform": platform.system().lower(),
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "os_release": {
            "product_name": sw_vers.get("ProductName", ""),
            "product_version": sw_vers.get("ProductVersion", ""),
            "product_version_extra": sw_vers.get("ProductVersionExtra", ""),
            "build_version": sw_vers.get("BuildVersion", ""),
        },
        "cpu": {
            "architecture": architecture,
            "cpu_count": logical_cpu,
            "model_name": hardware.get("chip_type", "") or brand_string,
            "threads_per_core": 1,
            "cores_per_socket": physical_cpu,
            "sockets": 1,
            "vendor_id": "Apple",
            "logical_cpu_count": logical_cpu,
            "physical_cpu_count": physical_cpu,
            "brand_string": brand_string,
            "chip_type": hardware.get("chip_type", ""),
            "machine_name": hardware.get("machine_name", ""),
            "machine_model": hardware.get("machine_model", ""),
            "model_number": hardware.get("model_number", ""),
            "number_processors": hardware.get("number_processors", ""),
        },
        "memory": {
            "mem_total_kib": mem_total_kib,
            "mem_total_gib": round(mem_total_kib / 1024 / 1024, 2) if mem_total_kib else 0.0,
            "physical_memory": hardware.get("physical_memory", ""),
        },
        "gpu": {
            "driver_version": hardware.get("boot_rom_version", ""),
            "devices": [
                {
                    "Model": gpu_name,
                    "GPU Cores": gpu_cores,
                    "Vendor": gpu_vendor,
                    "Bus": display.get("sppci_bus", ""),
                    "Device Type": display.get("sppci_device_type", ""),
                    "Metal Support": display.get("spdisplays_mtlgpufamilysupport", ""),
                    "Memory Mode": memory_mode,
                    "Shared Memory GiB": shared_memory_gib,
                }
            ],
            "model": gpu_name,
            "cores": gpu_cores,
            "vendor": gpu_vendor,
            "bus": display.get("sppci_bus", ""),
            "device_type": display.get("sppci_device_type", ""),
            "metal_support": display.get("spdisplays_mtlgpufamilysupport", ""),
            "memory_mode": memory_mode,
            "shared_memory_gib": shared_memory_gib,
            "vram_total_mib": None,
            "vram_total_gib": None,
        },
        "hardware": hardware,
        "display": display,
        "system_profiler_hardware": hardware_raw,
        "system_profiler_displays": display_raw,
    }


def collect_host_system_config() -> dict[str, object] | None:
    if platform.system() == "Linux":
        return collect_linux_system_config()
    if platform.system() == "Darwin":
        return collect_macos_system_config()
    return None


def collect_system_config(suite: dict) -> dict[str, object] | None:
    # The public runner never writes a host inventory. Private performance
    # tooling may collect one outside this repository.
    return None


def _os_release_summary(system_config: dict[str, object]) -> str:
    os_release = system_config.get("os_release", {})
    if not isinstance(os_release, dict):
        return ""
    if os_release.get("pretty_name"):
        return str(os_release["pretty_name"])
    if os_release.get("product_name"):
        product = str(os_release.get("product_name", ""))
        version = str(os_release.get("product_version", ""))
        extra = str(os_release.get("product_version_extra", ""))
        build = str(os_release.get("build_version", ""))
        version_bits = [bit for bit in [version, extra] if bit]
        summary = product
        if version_bits:
            summary = f"{summary} {' '.join(version_bits)}"
        if build:
            summary = f"{summary} ({build})"
        return summary
    return ""


def _cpu_summary(system_config: dict[str, object]) -> str:
    cpu = system_config.get("cpu", {})
    if not isinstance(cpu, dict):
        return ""
    if cpu.get("model_name"):
        model_name = str(cpu.get("model_name", ""))
        cpu_count = cpu.get("cpu_count", "")
        threads_per_core = cpu.get("threads_per_core", "")
        if cpu_count and threads_per_core:
            return f"{model_name} ({cpu_count} cores / {threads_per_core} threads per core)"
        return model_name
    if cpu.get("chip_type"):
        chip_type = str(cpu.get("chip_type", ""))
        logical = cpu.get("logical_cpu_count", cpu.get("cpu_count", ""))
        physical = cpu.get("physical_cpu_count", cpu.get("cores_per_socket", ""))
        if logical and physical:
            return f"{chip_type} ({logical} logical / {physical} physical cores)"
        return chip_type
    return ""


def _memory_summary(system_config: dict[str, object]) -> str:
    memory = system_config.get("memory", {})
    if not isinstance(memory, dict):
        return ""
    physical = str(memory.get("physical_memory", ""))
    gib = memory.get("mem_total_gib", "")
    if physical and gib:
        return f"{physical} ({gib} GiB)"
    if physical:
        return physical
    if gib:
        return f"{gib} GiB"
    return ""


def _gpu_summary(system_config: dict[str, object]) -> str:
    gpu = system_config.get("gpu", {})
    if not isinstance(gpu, dict):
        return ""
    platform_name = str(system_config.get("platform", "")).lower()
    if platform_name == "darwin":
        devices = gpu.get("devices", [])
        first_gpu = devices[0] if isinstance(devices, list) and devices else {}
        model = str(gpu.get("model", "") or first_gpu.get("Model", ""))
        parts = []
        if gpu.get("cores"):
            parts.append(f"{gpu['cores']} GPU cores")
        if gpu.get("shared_memory_gib"):
            parts.append(f"{gpu['shared_memory_gib']} GiB unified memory")
        if gpu.get("driver_version"):
            parts.append(f"boot ROM {gpu['driver_version']}")
        if model and parts:
            return f"{model} ({', '.join(parts)})"
        return model or ", ".join(parts)
    devices = gpu.get("devices", [])
    first_gpu = devices[0] if isinstance(devices, list) and devices else {}
    model = str(first_gpu.get("Model", "") or gpu.get("model", ""))
    parts = []
    if gpu.get("vram_total_gib"):
        parts.append(f"{gpu['vram_total_gib']} GiB VRAM")
    if gpu.get("driver_version"):
        parts.append(f"driver {gpu['driver_version']}")
    if model and parts:
        return f"{model} ({', '.join(parts)})"
    return model or ", ".join(parts)


def _system_summary_lines(system_config: dict[str, object]) -> list[str]:
    return [
        "## System Configuration",
        "",
        f"- Host: `{system_config.get('hostname', '')}`",
        f"- Platform: `{system_config.get('platform', '')}`",
        f"- Kernel: `{system_config.get('kernel', '')}`",
        f"- OS: `{_os_release_summary(system_config)}`",
        f"- CPU: `{_cpu_summary(system_config)}`",
        f"- Memory: `{_memory_summary(system_config)}`",
        f"- GPU: `{_gpu_summary(system_config)}`",
        f"- Details: `{SYSTEM_CONFIG_FILENAME}`",
        "",
    ]


def write_markdown_summary(
    report_path: Path,
    suite: dict,
    run_rows: list[dict],
    system_config: dict[str, object] | None = None,
) -> None:
    lines = [
        f"# FortBench Report: {suite['name']}",
        "",
        f"- Generated: `{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        "",
    ]
    excluded = excluded_task_reasons(suite)
    if excluded:
        scored_count = len(suite["tasks"]) - len(excluded)
        lines.extend([f"- Scored tasks: `{scored_count}`", ""])
        for task_id, reason in excluded.items():
            detail = f": {reason}" if reason else ""
            lines.append(f"- Excluded from scoring: `{task_id}`{detail}")
        lines.append("")
    if system_config is not None:
        lines.extend(_system_summary_lines(system_config))
    lines.extend(
        [
            "| Task | Agent | Budget | Final Status | Solved Stage | Runtime (s) |",
            "|---|---|---:|---|---:|---:|",
        ]
    )
    for row in run_rows:
        lines.append(
            f"| {row['task_id']} | {row['row_name']} | {row['budget_tier']} | "
            f"{row['final_status']} | {row['solved_stage'] or '-'} | {row['runtime_seconds_total']:.2f} |"
        )
    report_path.write_text("\n".join(lines) + "\n")


def write_csv_summary(report_path: Path, run_rows: list[dict]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "task_id",
        "row_name",
        "agent",
        "model_alias",
        "budget_tier",
        "provider_class",
        "local_backend",
        "final_status",
        "solved_stage",
        "runtime_seconds_total",
        "local_model_switch_seconds",
    ]
    lines = [",".join(headers)]
    for row in run_rows:
        values = [
            str(row.get("task_id", "")),
            str(row.get("row_name", "")),
            str(row.get("agent", "")),
            str(row.get("model_alias", "")),
            str(row.get("budget_tier", "")),
            str(row.get("provider_class", "")),
            str(row.get("local_backend", "")),
            str(row.get("final_status", "")),
            str(row.get("solved_stage") or ""),
            str(row.get("runtime_seconds_total", "")),
            str(row.get("local_model_switch_seconds", "")),
        ]
        lines.append(",".join(value.replace(",", ";") for value in values))
    report_path.write_text("\n".join(lines) + "\n")


def write_suite_artifacts(output_dir: Path, suite: dict, run_rows: list[dict]) -> None:
    system_config = collect_system_config(suite)
    if system_config is not None:
        write_json(output_dir / SYSTEM_CONFIG_FILENAME, system_config)
    excluded_reasons = excluded_task_reasons(suite)
    stored_rows = []
    for row in run_rows:
        if row.get("task_id") not in excluded_reasons:
            stored_rows.append(row)
            continue
        annotated = dict(row)
        annotated["excluded_from_score"] = True
        annotated["exclusion_reason"] = excluded_reasons[row["task_id"]]
        stored_rows.append(annotated)
    write_json(output_dir / "results.json", stored_rows)
    scored_rows = [row for row in stored_rows if not row.get("excluded_from_score")]
    write_markdown_summary(output_dir / "summary.md", suite, scored_rows, system_config)
    write_csv_summary(output_dir / "summary.csv", scored_rows)


def _archive_rel_parts(path: Path, run_dir: Path) -> tuple[str, ...]:
    return path.relative_to(run_dir).parts


def _should_skip_archive_path(path: Path, run_dir: Path) -> bool:
    rel_parts = _archive_rel_parts(path, run_dir)
    return any(rel_parts[: len(prefix)] == prefix for prefix in ARCHIVE_SKIP_PREFIXES)


def _ensure_archive_readable(path: Path) -> bool:
    result = subprocess.run(
        ["sudo", "-n", "chmod", "a+rX", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def _add_path_to_archive(tar: tarfile.TarFile, path: Path, run_dir: Path) -> None:
    if _should_skip_archive_path(path, run_dir):
        return
    rel_name = path.relative_to(run_dir).as_posix()
    try:
        tar.add(path, arcname=rel_name, recursive=False)
    except PermissionError:
        if not _ensure_archive_readable(path):
            raise
        tar.add(path, arcname=rel_name, recursive=False)
    if not path.is_dir():
        return
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name)
    except PermissionError:
        if not _ensure_archive_readable(path):
            raise
        children = sorted(path.iterdir(), key=lambda item: item.name)
    for child in children:
        _add_path_to_archive(tar, child, run_dir)


def _remove_path_best_effort(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    if not path.exists():
        return
    benchmark_user = _local_benchmark_user()
    if benchmark_user:
        subprocess.run(
            ["sudo", "-n", "-u", benchmark_user, "rm", "-rf", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def archive_row_artifacts(run_dir: Path) -> str:
    archive_name = "row-artifacts.tar.zst"
    items = [path for path in run_dir.iterdir() if path.name not in {archive_name, "result.json"}]
    if not items:
        return archive_name
    tmp_tar = run_dir / "row-artifacts.tar"
    if tmp_tar.exists():
        tmp_tar.unlink()
    with tarfile.open(tmp_tar, "w") as tar:
        for item in items:
            _add_path_to_archive(tar, item, run_dir)
    subprocess.run(
        ["zstd", "-q", "-T0", "-1", "--rm", str(tmp_tar)],
        check=True,
        capture_output=True,
        text=True,
    )
    for item in items:
        _remove_path_best_effort(item)
    return archive_name


def normalize_result_row(row: dict) -> tuple[dict, bool]:
    normalized = json.loads(json.dumps(row))
    solved_stage = None
    for stage in normalized.get("stage_results", []):
        if stage.get("acceptance_ok"):
            solved_stage = stage.get("stage")
            break

    changed = False
    had_solved_stage = "solved_stage" in normalized
    if not had_solved_stage:
        normalized["solved_stage"] = solved_stage
        changed = True

    had_final_status = "final_status" in normalized
    if not had_final_status:
        final_status = "solved" if solved_stage else "failed"
        normalized["final_status"] = final_status
        changed = True

    return normalized, changed


def load_existing_results(output_dir: Path) -> list[dict]:
    results_path = output_dir / "results.json"
    if not results_path.exists():
        return []
    data = json.loads(results_path.read_text())
    if not isinstance(data, list):
        raise ValueError(f"expected list rows in {results_path}")
    normalized_rows = []
    changed = False
    for row in data:
        normalized_row, row_changed = normalize_result_row(row)
        normalized_rows.append(normalized_row)
        changed = changed or row_changed
    if changed:
        write_json(results_path, normalized_rows)
    return normalized_rows


def write_task_check_summary(report_path: Path, task: dict, base_setup: list[dict], base_acceptance: AcceptanceResult, fixed_setup: list[dict], fixed_acceptance: AcceptanceResult) -> None:
    lines = [
        f"# FortBench Task Check: {task['id']}",
        "",
        f"- Title: `{task['title']}`",
        f"- Repo: `{task['repo_url']}`",
        f"- Base commit: `{task['base_commit']}`",
        f"- Fixed commit: `{task['fixed_commit']}`",
        f"- Base acceptance: `{'pass' if base_acceptance.ok else 'fail'}`",
        f"- Fixed acceptance: `{'pass' if fixed_acceptance.ok else 'fail'}`",
        "",
        "## Base Commands",
        "",
    ]
    for item in [*base_setup, *base_acceptance.command_results]:
        lines.append(f"- `{item['command']}` -> `{item['returncode']}` in `{item['duration_seconds']:.2f}s`")
    lines.extend(["", "## Fixed Commands", ""])
    for item in [*fixed_setup, *fixed_acceptance.command_results]:
        lines.append(f"- `{item['command']}` -> `{item['returncode']}` in `{item['duration_seconds']:.2f}s`")
    report_path.write_text("\n".join(lines) + "\n")


def run_task_row(task: dict, row: dict, reports_dir: Path, local_model_switch_seconds: float = 0.0) -> dict:
    task_dir = Path(task["_task_dir"])
    run_id = f"{task['id']}__{row['name']}"
    run_dir = reports_dir / "artifacts" / run_id
    workspace = run_dir / "workspace"
    if run_dir.exists():
        _remove_path_best_effort(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    clone_workspace(task, workspace)
    started = time.time()
    setup_results = run_setup(task, workspace, task_dir)
    baseline_acceptance = run_acceptance(task, workspace, task_dir)
    if baseline_acceptance.ok:
        result = {
            "task_id": task["id"],
            "task_title": task["title"],
            "row_name": row["name"],
            "agent": row["adapter"],
            "model_alias": row.get("model", ""),
            "budget_tier": row.get("budget_tier", "fixed/default"),
            "provider_class": row.get("provider_class", "cloud"),
            "local_backend": LOCAL_BACKEND_NAME if row.get("provider_class") == "local" else "",
            "local_model_alias": row.get("local_model_alias", ""),
            "local_model_switch_seconds": round(local_model_switch_seconds, 2),
            "setup_results": setup_results,
            "baseline_acceptance": asdict(baseline_acceptance),
            "solved_stage": None,
            "final_status": "error",
            "runtime_seconds_total": round(time.time() - started, 2),
            "stage_results": [],
            "error": "task baseline acceptance already passes on frozen base commit",
            "judges": {},
        }
        archive_name = archive_row_artifacts(run_dir)
        result["artifact_archive"] = archive_name
        write_json(run_dir / "result.json", result)
        return result

    adapter = build_adapter(row["adapter"])
    stage_budget_seconds = row.get("stage_budget_seconds", [600, 600, 600])
    stage_results: list[dict] = []
    acceptance: AcceptanceResult | None = None
    solved_stage = None

    for idx, budget in enumerate(stage_budget_seconds, start=1):
        previous_stage = stage_results[-1] if stage_results else None
        prompt = stage_prompt(task, idx, acceptance, previous_stage)
        response = adapter.stage(idx, prompt, workspace, run_dir, row, budget)
        assert_local_stage_healthy(row, idx, response)
        stage_setup_results = run_setup(task, workspace, task_dir)
        acceptance = run_acceptance(task, workspace, task_dir)
        record = stage_record(idx, response, stage_setup_results, acceptance)
        stage_results.append(record)
        if acceptance.ok and solved_stage is None:
            solved_stage = idx
            break

    final_status = "solved" if solved_stage else "failed"
    final_stage = stage_results[-1]
    judges = {}
    if final_status == "solved" and row.get("run_judges", True):
        for judge_engine in row.get("judge_engines", ["codex"]):
            if judge_engine == "claude":
                judges["claude"] = run_claude_judge(task, final_stage, asdict(acceptance), workspace)
            elif judge_engine == "codex":
                judges["codex"] = run_codex_judge(task, final_stage, asdict(acceptance), workspace)
    result = {
        "task_id": task["id"],
        "task_title": task["title"],
        "row_name": row["name"],
        "agent": row["adapter"],
        "model_alias": row.get("model", ""),
        "budget_tier": row.get("budget_tier", "fixed/default"),
        "provider_class": row.get("provider_class", "cloud"),
        "local_backend": LOCAL_BACKEND_NAME if row.get("provider_class") == "local" else "",
        "local_model_alias": row.get("local_model_alias", ""),
        "local_model_switch_seconds": round(local_model_switch_seconds, 2),
        "setup_results": setup_results,
        "baseline_acceptance": asdict(baseline_acceptance),
        "solved_stage": solved_stage,
        "final_status": final_status,
        "runtime_seconds_total": round(time.time() - started, 2),
        "stage_results": stage_results,
        "judges": judges,
    }
    archive_name = archive_row_artifacts(run_dir)
    result["artifact_archive"] = archive_name
    write_json(run_dir / "result.json", result)
    return result


def load_suite(path: Path) -> tuple[dict, list[dict]]:
    suite = load_yaml(path)
    task_defs = []
    for task_path in suite["tasks"]:
        full = (path.parent.parent / task_path).resolve()
        task = load_yaml(full)
        task["_task_dir"] = str(full.parent)
        task_defs.append(task)
    excluded = excluded_task_ids(suite)
    unknown = excluded - {task["id"] for task in task_defs}
    if unknown:
        raise ValueError(f"suite excludes unknown task IDs: {sorted(unknown)}")
    return suite, task_defs


def load_task(path: Path) -> dict:
    full = path.resolve()
    task = load_yaml(full)
    task["_task_dir"] = str(full.parent)
    return task


def local_served_model_name(row: dict) -> str:
    override = row.get("local_served_model_name")
    if override:
        model = os.path.expandvars(str(override))
        if "$" in model:
            raise RuntimeError("served model references an unset environment variable")
        return model
    return "qwen"


def local_model_env(row: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["LLAMACPP_MODEL_ALIAS"] = row["local_model_alias"]
    env["LLAMACPP_SERVED_MODEL_NAME"] = local_served_model_name(row)
    env.setdefault("LLAMACPP_START_TIMEOUT", "1800")
    env.setdefault("LLAMACPP_SMOKE_TEST", "false")
    extra_flags = env.get("LLAMACPP_EXTRA_FLAGS", "")
    if " -ctk " not in f" {extra_flags} " and " --cache-type-k " not in f" {extra_flags} ":
        extra_flags = f"{extra_flags} -ctk q8_0".strip()
    if " -ctv " not in f" {extra_flags} " and " --cache-type-v " not in f" {extra_flags} ":
        extra_flags = f"{extra_flags} -ctv q8_0".strip()
    env["LLAMACPP_EXTRA_FLAGS"] = extra_flags
    return env


def local_profile_key(row: dict) -> tuple[str, str, str]:
    return (
        row.get("local_instance", "local"),
        row.get("local_model_alias", ""),
        local_served_model_name(row),
    )


def local_models_url(row: dict) -> str:
    endpoint = os.path.expandvars(str(row.get("endpoint", ""))).strip()
    if endpoint:
        if "$" in endpoint:
            raise RuntimeError("endpoint references an unset environment variable")
        return endpoint.rstrip("/") + "/models"
    port = int(row.get("local_port") or (8081 if row.get("local_instance") == "fast" else 8080))
    return f"http://127.0.0.1:{port}/v1/models"


def assert_local_server_model(row: dict) -> None:
    expected = local_served_model_name(row)
    models_url = local_models_url(row)
    api_key_env = str(row.get("api_key_env") or "").strip()
    if api_key_env:
        api_key = os.environ.get(api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"upstream API key environment variable is unset: {api_key_env}")
        request = urllib.request.Request(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    else:
        request = models_url
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    model_ids = [item.get("id", "") for item in payload.get("data", [])]
    if expected not in model_ids:
        raise RuntimeError(
            f"{LOCAL_BACKEND_NAME} served model mismatch for {row['name']}: "
            f"expected {expected!r}, got {model_ids!r}"
        )


def _kill_port(port: int) -> None:
    """Kill any process listening on the given port (fallback when PID files are stale)."""
    result = subprocess.run(
        ["lsof", "-ti", f":{port}"],
        capture_output=True, text=True, check=False,
    )
    pids = result.stdout.strip().split()
    for pid in pids:
        if pid:
            subprocess.run(["kill", "-9", pid], check=False, capture_output=True)
    if pids:
        time.sleep(2)


def switch_local_model(row: dict) -> float:
    if row.get("local_lifecycle") == "external":
        return 0.0
    if not row.get("local_model_alias"):
        return 0.0
    if not os.environ.get("FORTBENCH_SCRIPTS_DIR"):
        raise RuntimeError(
            "managed local lifecycle requires FORTBENCH_SCRIPTS_DIR; "
            "use local_lifecycle: external for llama.cpp or custom endpoints"
        )
    instance = row.get("local_instance")
    started = time.time()
    subprocess.run(
        ["bash", str(DEVSTRAL_SCRIPTS / "server_stop_llamacpp.sh"), "all"],
        check=False, capture_output=True, text=True,
    )
    # Wait for ports to be released after stop
    time.sleep(3)
    start_args = ["bash", str(DEVSTRAL_SCRIPTS / "server_start_llamacpp.sh")]
    if instance:
        start_args.append(instance)
    subprocess.run(
        start_args,
        check=True,
        capture_output=True,
        text=True,
        env=local_model_env(row),
    )
    port = 8081 if instance == "fast" else 8080
    url = f"http://127.0.0.1:{port}/v1/models"
    for attempt in range(360):
        try:
            urllib.request.urlopen(url, timeout=5)
            break
        except Exception:
            time.sleep(5)
    else:
        raise RuntimeError(f"{LOCAL_BACKEND_NAME} server not responding on port {port} after 1800s")
    return time.time() - started


def stop_local_server() -> None:
    subprocess.run(
        ["bash", str(DEVSTRAL_SCRIPTS / "server_stop_llamacpp.sh"), "all"],
        check=False,
        capture_output=True,
        text=True,
    )


def failure_result(task: dict, row: dict, exc: Exception) -> dict:
    return {
        "task_id": task["id"],
        "task_title": task["title"],
        "row_name": row["name"],
        "agent": row["adapter"],
        "model_alias": row.get("model", ""),
        "budget_tier": row.get("budget_tier", "fixed/default"),
        "provider_class": row.get("provider_class", "cloud"),
        "local_backend": LOCAL_BACKEND_NAME if row.get("provider_class") == "local" else "",
        "local_model_alias": row.get("local_model_alias", ""),
        "local_model_switch_seconds": 0.0,
        "solved_stage": None,
        "final_status": "error",
        "runtime_seconds_total": 0.0,
        "stage_results": [],
        "error": str(exc),
        "error_traceback": traceback.format_exc(),
        "judges": {},
    }


def collect_completed_futures(
    future_map: dict,
    run_rows: list[dict],
    suite: dict,
    output_dir: Path,
    continue_on_error: bool,
) -> int:
    done_futures = [future for future in future_map if future.done()]
    for future in done_futures:
        task, row = future_map.pop(future)
        try:
            run_rows.append(future.result())
            write_suite_artifacts(output_dir, suite, run_rows)
        except Exception as exc:
            run_rows.append(failure_result(task, row, exc))
            write_suite_artifacts(output_dir, suite, run_rows)
            if not continue_on_error:
                return 1
    return 0


def run_suite(suite_path: Path, output_dir: Path, continue_on_error: bool, resume: bool = False) -> int:
    suite, tasks = load_suite(suite_path)
    tasks = [task for task in tasks if task["id"] not in excluded_task_ids(suite)]
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_proxy_root = os.environ.get("FORTBENCH_LITELLM_PROXY_ROOT")
    os.environ["FORTBENCH_LITELLM_PROXY_ROOT"] = str(output_dir / ".litellm-proxy")
    prepare_proxy_root(proxy_root())
    run_rows = load_existing_results(output_dir) if resume else []
    completed_keys = {(row.get("task_id"), row.get("row_name")) for row in run_rows}
    local_rows = [row for row in suite["rows"] if row.get("provider_class") == "local"]
    cloud_rows = [row for row in suite["rows"] if row.get("provider_class") != "local"]
    requested_cloud_workers = int(suite.get("cloud_parallelism", 2))
    cloud_workers = 1 if requested_cloud_workers <= 0 else requested_cloud_workers
    cloud_executor: ThreadPoolExecutor | None = None
    local_executor: ThreadPoolExecutor | None = None
    future_map = {}
    # Run local suites model-major to avoid unnecessary local backend restarts.
    local_work_items = [
        (task, row)
        for row in local_rows
        for task in tasks
        if (task["id"], row["name"]) not in completed_keys
    ]
    next_local_index = 0
    current_local_profile: tuple[str, str, str] | None = None
    current_local_row_name: str | None = None
    suite_rc = 0

    def run_local_item(task: dict, row: dict) -> dict:
        nonlocal current_local_profile, current_local_row_name
        switch_seconds = 0.0
        target_profile = local_profile_key(row)
        if target_profile != current_local_profile:
            stop_proxy()
            switch_seconds = switch_local_model(row)
            assert_local_server_model(row)
            current_local_profile = target_profile
            current_local_row_name = None
        if row["name"] != current_local_row_name:
            stop_proxy()
            start_proxy(row)
            current_local_row_name = row["name"]
        return run_task_row(task, row, output_dir, local_model_switch_seconds=switch_seconds)

    def submit_next_local() -> None:
        nonlocal next_local_index
        if local_executor is None or next_local_index >= len(local_work_items):
            return
        task, row = local_work_items[next_local_index]
        next_local_index += 1
        future_map[local_executor.submit(run_local_item, task, row)] = (task, row)

    try:
        cloud_work_items = [
            (task, row)
            for task in tasks
            for row in cloud_rows
            if (task["id"], row["name"]) not in completed_keys
        ]
        if cloud_work_items:
            cloud_executor = ThreadPoolExecutor(max_workers=cloud_workers)
            for task, row in cloud_work_items:
                future_map[cloud_executor.submit(run_task_row, task, row, output_dir)] = (task, row)

        if local_work_items:
            local_executor = ThreadPoolExecutor(max_workers=1)
            submit_next_local()

        while future_map:
            done, _ = wait(future_map.keys(), return_when=FIRST_COMPLETED)
            for future in done:
                task, row = future_map.pop(future)
                try:
                    run_rows.append(future.result())
                    write_suite_artifacts(output_dir, suite, run_rows)
                    if row.get("provider_class") == "local":
                        submit_next_local()
                except Exception as exc:
                    run_rows.append(failure_result(task, row, exc))
                    write_suite_artifacts(output_dir, suite, run_rows)
                    suite_rc = 1
                    if cloud_executor:
                        cloud_executor.shutdown(cancel_futures=True)
                        cloud_executor = None
                    if local_executor:
                        local_executor.shutdown(cancel_futures=True)
                        local_executor = None
                    future_map.clear()
                    break
            if suite_rc:
                break
    finally:
        if local_rows:
            stop_proxy()
            if any(row.get("local_lifecycle") != "external" for row in local_rows):
                stop_local_server()
        if cloud_executor:
            cloud_executor.shutdown(wait=True, cancel_futures=False)
        if local_executor:
            local_executor.shutdown(wait=True, cancel_futures=False)
        if previous_proxy_root is None:
            os.environ.pop("FORTBENCH_LITELLM_PROXY_ROOT", None)
        else:
            os.environ["FORTBENCH_LITELLM_PROXY_ROOT"] = previous_proxy_root

    if suite_rc:
        return suite_rc
    write_suite_artifacts(output_dir, suite, run_rows)
    return 0


def check_task(task_path: Path, output_dir: Path) -> int:
    task = load_task(task_path)
    task_dir = Path(task["_task_dir"])
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    artifact_dir = output_dir / "artifacts"
    base_dir = artifact_dir / "base-workspace"
    fixed_dir = artifact_dir / "fixed-workspace"
    if base_dir.exists():
        shutil.rmtree(base_dir)
    if fixed_dir.exists():
        shutil.rmtree(fixed_dir)

    clone_workspace_at(task["repo_url"], task["base_commit"], base_dir)
    clone_workspace_at(task["repo_url"], task["fixed_commit"], fixed_dir)

    base_setup = run_setup(task, base_dir, task_dir)
    fixed_setup = run_setup(task, fixed_dir, task_dir)
    base_acceptance = run_acceptance(task, base_dir, task_dir)
    fixed_acceptance = run_acceptance(task, fixed_dir, task_dir)

    report = {
        "task_id": task["id"],
        "title": task["title"],
        "repo_url": task["repo_url"],
        "base_commit": task["base_commit"],
        "fixed_commit": task["fixed_commit"],
        "base_setup": base_setup,
        "base_acceptance": asdict(base_acceptance),
        "fixed_setup": fixed_setup,
        "fixed_acceptance": asdict(fixed_acceptance),
        "ok": (not base_acceptance.ok) and fixed_acceptance.ok,
    }
    write_json(output_dir / "oracle.json", report)
    write_task_check_summary(output_dir / "summary.md", task, base_setup, base_acceptance, fixed_setup, fixed_acceptance)
    return 0 if report["ok"] else 1
