from __future__ import annotations

import json
import subprocess
from pathlib import Path


JUDGE_RUBRIC_VERSION = "code_quality_v1"
DEFAULT_JUDGE_MODELS = {
    "claude": "opus",
    "codex": "gpt-5.4",
}
JUDGE_KEYS = {
    "overall_score",
    "correctness",
    "maintainability",
    "minimality",
    "issue_fit",
    "verification",
    "summary",
    "findings",
}


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _run_git_capture(cwd: Path, args: list[str], max_chars: int = 12000) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(git {' '.join(args)} failed: {exc})"
    output = proc.stdout.strip()
    if proc.returncode != 0:
        err = proc.stderr.strip()
        detail = err or output or f"exit {proc.returncode}"
        return f"(git {' '.join(args)} failed: {detail})"
    return _truncate(output, max_chars)


def build_code_evidence(cwd: Path) -> dict:
    changed_files_text = _run_git_capture(cwd, ["diff", "--name-only", "--find-renames"], max_chars=4000)
    changed_files = [line.strip() for line in changed_files_text.splitlines() if line.strip() and not line.startswith("(")]
    return {
        "workspace": str(cwd),
        "git_status_short": _run_git_capture(cwd, ["status", "--short"], max_chars=4000),
        "changed_files": changed_files,
        "diff_stat": _run_git_capture(cwd, ["diff", "--stat", "--find-renames"], max_chars=6000),
        "patch_excerpt": _run_git_capture(
            cwd,
            ["diff", "--find-renames", "--unified=1", "--no-ext-diff"],
            max_chars=20000,
        ),
    }


def select_stage_for_judging(row: dict) -> dict:
    stages = row.get("stage_results") or []
    solved_stage = row.get("solved_stage")
    if isinstance(solved_stage, int) and 1 <= solved_stage <= len(stages):
        return stages[solved_stage - 1]
    return stages[-1] if stages else {}


def validate_judge_result(result: dict) -> str | None:
    if set(result.keys()) != JUDGE_KEYS:
        return f"expected keys {sorted(JUDGE_KEYS)}, got {sorted(result.keys())}"
    for key in ["overall_score", "correctness", "maintainability", "minimality", "issue_fit", "verification"]:
        value = result.get(key)
        if not isinstance(value, int) or not (1 <= value <= 5):
            return f"{key} must be an integer from 1 to 5"
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        return "summary must be a non-empty string"
    findings = result.get("findings")
    if not isinstance(findings, list) or len(findings) > 3:
        return "findings must be a list with at most 3 items"
    if any(not isinstance(item, str) or not item.strip() for item in findings):
        return "each finding must be a non-empty string"
    return None


def judge_prompt(
    task: dict,
    final_stage: dict,
    acceptance: dict,
    code_evidence: dict | None = None,
    rubric_name: str = JUDGE_RUBRIC_VERSION,
    retry_error: str | None = None,
    previous_output: str | None = None,
) -> str:
    compact_acceptance = {
        "ok": acceptance.get("ok"),
        "command_results": [
            {
                "command": item.get("command"),
                "returncode": item.get("returncode"),
                "stdout": (item.get("stdout") or "")[:2000],
                "stderr": (item.get("stderr") or "")[:2000],
                "duration_seconds": item.get("duration_seconds"),
                "ok": item.get("ok"),
            }
            for item in acceptance.get("command_results", [])
        ],
    }
    compact_final_stage = {
        "stage": final_stage.get("stage"),
        "agent_ok": final_stage.get("agent_ok"),
        "agent_error": final_stage.get("agent_error"),
        "agent_duration_seconds": final_stage.get("agent_duration_seconds"),
        "agent_text": (final_stage.get("agent_text") or "")[:12000],
        "setup_results": [
            {
                "command": item.get("command"),
                "returncode": item.get("returncode"),
                "stdout": (item.get("stdout") or "")[:1000],
                "stderr": (item.get("stderr") or "")[:1000],
                "duration_seconds": item.get("duration_seconds"),
                "ok": item.get("ok"),
            }
            for item in final_stage.get("setup_results", [])
        ],
        "acceptance_ok": final_stage.get("acceptance_ok"),
    }
    retry_block = ""
    if retry_error:
        retry_block = f"""

Your previous response was invalid.

Validation error:
{retry_error}

Previous response:
{previous_output or ""}
"""
    return f"""You are grading a Fortran coding benchmark run from archived artifacts.

Task id: {task["id"]}
Issue: {task["issue_url"]}
Title: {task["title"]}
Rubric version: {rubric_name}

Scoring rubric:
- correctness: does the final patch satisfy the intended behavior and the observed acceptance evidence?
- maintainability: is the final patch understandable, coherent, and unlikely to create future maintenance debt?
- minimality: does the final patch avoid unnecessary churn, stray files, build artifacts, or unrelated edits?
- issue_fit: does it solve the intended issue rather than only gaming the validator or addressing the wrong root cause?
- verification: do the archived stage evidence and acceptance results show adequate local verification for the claim?
- overall_score: holistic score, weighted primarily by correctness and issue_fit.

Scoring scale:
- 5 = excellent
- 4 = good
- 3 = mixed / partial
- 2 = weak
- 1 = poor

Judging rules:
- Judge the final archived workspace state, not the agent's intent.
- Prefer concrete code evidence and acceptance outputs over agent self-reporting.
- Penalize unrelated churn, lingering build products, or edits that appear broader than necessary.
- A failed acceptance run should usually imply low correctness and low overall_score.

Acceptance summary:
{json.dumps(compact_acceptance, indent=2)}

Final stage summary:
{json.dumps(compact_final_stage, indent=2)}

Code evidence from archived workspace:
{json.dumps(code_evidence or {}, indent=2)}

Return exactly one JSON object with no markdown and no extra keys.
Use this exact schema:
{{
  "overall_score": 1,
  "correctness": 1,
  "maintainability": 1,
  "minimality": 1,
  "issue_fit": 1,
  "verification": 1,
  "summary": "short paragraph",
  "findings": ["finding 1", "finding 2"]
}}

Rules:
- All numeric fields must be integers from 1 to 5.
- `findings` must contain at most 3 short strings.
- If the run is strong, `findings` may be an empty list.
- Do not rename keys.
- Do not add keys.
- Do not wrap the JSON in code fences.
{retry_block}
"""


def _judge_metadata(engine: str, model: str, rubric_name: str) -> dict:
    return {
        "engine": engine,
        "model": model,
        "rubric": rubric_name,
    }


def run_claude_judge(
    task: dict,
    final_stage: dict,
    acceptance: dict,
    cwd: Path,
    *,
    model: str | None = None,
    rubric_name: str = JUDGE_RUBRIC_VERSION,
    code_evidence: dict | None = None,
) -> dict:
    schema = json.dumps(
        {
            "type": "object",
            "properties": {
                "overall_score": {"type": "integer", "minimum": 1, "maximum": 5},
                "correctness": {"type": "integer", "minimum": 1, "maximum": 5},
                "maintainability": {"type": "integer", "minimum": 1, "maximum": 5},
                "minimality": {"type": "integer", "minimum": 1, "maximum": 5},
                "issue_fit": {"type": "integer", "minimum": 1, "maximum": 5},
                "verification": {"type": "integer", "minimum": 1, "maximum": 5},
                "summary": {"type": "string"},
                "findings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                },
            },
            "required": [
                "overall_score",
                "correctness",
                "maintainability",
                "minimality",
                "issue_fit",
                "verification",
                "summary",
                "findings",
            ],
            "additionalProperties": False,
        }
    )
    resolved_model = model or DEFAULT_JUDGE_MODELS["claude"]
    prompt = judge_prompt(
        task,
        final_stage,
        acceptance,
        code_evidence=code_evidence or build_code_evidence(cwd),
        rubric_name=rubric_name,
    )
    meta = _judge_metadata("claude", resolved_model, rubric_name)
    try:
        proc = subprocess.run(
            [
                "claude",
                "--print",
                "--output-format",
                "json",
                "--json-schema",
                schema,
                "--dangerously-skip-permissions",
                "--model",
                resolved_model,
                prompt,
            ],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=300,
        )
    except OSError as exc:
        return {"ok": False, **meta, "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"ok": False, **meta, "error": "judge timed out after 300 seconds"}
    if proc.returncode != 0:
        return {"ok": False, **meta, "error": proc.stderr.strip() or proc.stdout.strip()}
    raw = proc.stdout.strip()
    try:
        parsed_envelope = json.loads(raw)
    except Exception:
        return {"ok": False, **meta, "error": "response was not valid JSON", "raw": raw}
    parsed = parsed_envelope.get("structured_output")
    if not isinstance(parsed, dict):
        return {"ok": False, **meta, "error": "missing structured_output in claude judge response", "raw": raw}
    validation_error = validate_judge_result(parsed)
    if validation_error is not None:
        return {"ok": False, **meta, "error": validation_error, "raw": raw}
    return {"ok": True, **meta, "result": parsed}


def run_codex_judge(
    task: dict,
    final_stage: dict,
    acceptance: dict,
    cwd: Path,
    *,
    model: str | None = None,
    rubric_name: str = JUDGE_RUBRIC_VERSION,
    code_evidence: dict | None = None,
) -> dict:
    resolved_model = model or DEFAULT_JUDGE_MODELS["codex"]
    shared_code_evidence = code_evidence or build_code_evidence(cwd)
    meta = _judge_metadata("codex", resolved_model, rubric_name)
    retry_error = None
    previous_output = None
    for _ in range(2):
        prompt = judge_prompt(
            task,
            final_stage,
            acceptance,
            code_evidence=shared_code_evidence,
            rubric_name=rubric_name,
            retry_error=retry_error,
            previous_output=previous_output,
        )
        try:
            proc = subprocess.run(
                [
                    "codex",
                    "exec",
                    "--json",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--model",
                    resolved_model,
                    prompt,
                ],
                cwd=str(cwd),
                text=True,
                capture_output=True,
                timeout=300,
            )
        except OSError as exc:
            return {"ok": False, **meta, "error": str(exc)}
        except subprocess.TimeoutExpired:
            return {"ok": False, **meta, "error": "judge timed out after 300 seconds"}
        if proc.returncode != 0:
            return {"ok": False, **meta, "error": proc.stderr.strip() or proc.stdout.strip()}
        last = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except Exception:
                continue
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                last = item.get("text")
        if not last:
            return {"ok": False, **meta, "error": "missing codex judge output"}
        try:
            parsed = json.loads(last)
        except Exception:
            retry_error = "response was not valid JSON"
            previous_output = last
            continue
        validation_error = validate_judge_result(parsed)
        if validation_error is None:
            return {"ok": True, **meta, "result": parsed}
        retry_error = validation_error
        previous_output = json.dumps(parsed, indent=2)
    return {"ok": False, **meta, "error": f"invalid codex judge output after retry: {retry_error}", "raw": previous_output}


def run_judge(
    engine: str,
    task: dict,
    final_stage: dict,
    acceptance: dict,
    cwd: Path,
    *,
    model: str | None = None,
    rubric_name: str = JUDGE_RUBRIC_VERSION,
    code_evidence: dict | None = None,
) -> dict:
    if engine == "claude":
        return run_claude_judge(
            task,
            final_stage,
            acceptance,
            cwd,
            model=model,
            rubric_name=rubric_name,
            code_evidence=code_evidence,
        )
    if engine == "codex":
        return run_codex_judge(
            task,
            final_stage,
            acceptance,
            cwd,
            model=model,
            rubric_name=rubric_name,
            code_evidence=code_evidence,
        )
    raise ValueError(f"unsupported judge engine: {engine}")
