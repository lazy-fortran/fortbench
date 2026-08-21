# Fortbench

Fortbench is a reproducible benchmark for real Fortran coding work. It checks
whether an agent can repair twenty frozen issues from public Fortran projects,
using deterministic build and acceptance commands rather than subjective pass
labels.

This repository contains the complete modern `corpus-20-v1` suite, the runner,
the acceptance fixtures, and generic connection paths for llama.cpp and other
OpenAI-compatible endpoints. It intentionally contains no published hardware
inventory or performance measurements.

## What you need

- Python 3.11 or newer;
- Git and the compilers/build tools required by the selected tasks;
- one supported agent CLI (OpenCode is the simplest local-model path);
- either `llama-server` plus a GGUF, or an already-running compatible endpoint.

## Install

```bash
git clone https://github.com/lazy-fortran/fortbench.git
cd fortbench
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Install OpenCode and make sure `opencode` is on `PATH`. Fortbench creates an
isolated agent configuration for every stage; it does not reuse an interactive
chat session.

## Run with llama.cpp

Start any recent `llama-server` under the stable alias `fortbench-model`:

```bash
export FORTBENCH_MODEL_FILE=/path/to/model.gguf
scripts/start-llamacpp.sh
```

In a second terminal:

```bash
. .venv/bin/activate
fortbench run-suite suites/smoke-llamacpp.yaml --output-dir runs/smoke
fortbench run-suite suites/corpus20-llamacpp.yaml --output-dir runs/corpus20
```

The smoke suite runs one corpus task. Run it before committing the time and
compute required by the complete suite. Set `LLAMA_SERVER`,
`FORTBENCH_CONTEXT_SIZE`, or `FORTBENCH_LLAMA_ARGS` when the defaults do not fit
your local installation.

## Run with a custom endpoint

The endpoint must expose OpenAI-compatible `/v1/models` and chat-completion
routes. It may be local, self-hosted, or a private gateway.

```bash
export FORTBENCH_ENDPOINT=https://example.invalid/v1
export FORTBENCH_SERVED_MODEL=my-model-id
export FORTBENCH_UPSTREAM_API_KEY='...'
fortbench run-suite suites/smoke-custom-endpoint.yaml --output-dir runs/smoke
fortbench run-suite suites/corpus20-custom-endpoint.yaml --output-dir runs/corpus20
```

Credentials are read from the environment and must never be added to a suite
file. See [Running the suite](docs/running.md) for lifecycle, adapter, and
troubleshooting details.

## Latest scored results

The published suites score 19 valid tasks. The
`roots-fortran-26-itp-method-fix` task remains in the frozen inventory but is
excluded because its acceptance command passes on both pinned commits.

Models are ordered by quality first and speed second. Only one completed
full-suite model run is currently available in this checkout; private timing
data is intentionally not published.

| Model | Quality | Speed | Status |
|---|---:|---|---|
| Qwen3.8-27B via OpenCode/llama.cpp | 19/19 (100%) | Private | complete |

## Verify the corpus itself

Every task pins a failing base commit and a fixed commit. This command confirms
that the deterministic oracle rejects the former and accepts the latter:

```bash
fortbench check-task \
  tasks/corpus-20-v1/datetime-fortran-74-seconds-since-epoch/task.yaml \
  --output-dir runs/oracle-check
```

The complete task list is in [Corpus](docs/corpus.md); the three-stage repair
loop is documented in [Protocol](docs/protocol.md).

## Results and privacy

`runs/` is ignored. Local run directories contain diagnostic material and may
include paths, timestamps, durations, and provider logs. Treat them as private.
Do not commit a run directory.

Public Fortbench records contain only model and weight identity, inference
settings, model output, and deterministic evaluation. They exclude hardware,
hostnames, RAM, paths, timing, throughput, cost, raw logs, and environment
dumps. Create one with `fortbench export-public`; see
[Publishing results](docs/publishing.md).

## Development

```bash
python -m unittest discover -s tests -v
python -m py_compile fortbench/*.py
```

The active corpus manifests are published fixtures. Do not edit them in place;
introduce a versioned successor when a task contract must change.

## License

Fortbench is MIT licensed. The benchmark tasks reference third-party projects;
see [third-party notices](THIRD_PARTY_NOTICES.md).
