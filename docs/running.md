# Running the suite

Fortbench performs three fresh agent invocations per task and stops as soon as
the deterministic acceptance commands pass. The twenty-task corpus therefore
represents up to sixty agent invocations.

## Recommended sequence

1. Install Fortbench in a virtual environment.
2. Verify one task oracle with `fortbench check-task`.
3. Start llama.cpp or configure a compatible endpoint.
4. Run the matching smoke suite.
5. Inspect the private output directory for adapter or compiler failures.
6. Run the complete `corpus20` suite.

## llama.cpp

`scripts/start-llamacpp.sh` binds only to loopback, uses a stable served-model
alias, and leaves GPU offload, cache quantization, sampling, and speculative
decoding to `FORTBENCH_LLAMA_ARGS`. The suite treats it as an external service,
so Fortbench never stops a server it did not start.

## Custom endpoints

Set `FORTBENCH_ENDPOINT` to the API root ending in `/v1` and
`FORTBENCH_SERVED_MODEL` to an identifier returned by `/v1/models`. If the
endpoint requires a bearer token, set `FORTBENCH_UPSTREAM_API_KEY`.

Suite files contain environment-variable references, not credentials. Missing
variables fail before the first task.

## Agent adapters

The supplied suites use OpenCode because it works with a generic
OpenAI-compatible model through Fortbench's isolated proxy. The runner also
contains Codex, Claude Code, Qwen Code, Mistral Vibe, and aider adapters for
private comparison suites.

## Output directories

Use `runs/<name>` or another ignored path. Raw output is private diagnostic
material: it contains agent text, worktree status, command output, durations,
and possibly local paths. Never publish it directly.
