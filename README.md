# Fortbench

Fortbench is a reproducible benchmark for real Fortran coding work. It checks
whether an agent can repair twenty frozen issues from public Fortran projects,
using deterministic build and acceptance commands rather than subjective pass
labels.

The repository contains the `corpus-20-v1` task suite, the runner, the
acceptance fixtures, and connection paths for llama.cpp and other
OpenAI-compatible endpoints. Each task is attempted in up to three fresh agent
invocations (attempt, self-review, final repair); see [Protocol](docs/protocol.md).

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

## Results

Nineteen of the twenty tasks are scored (one task's acceptance check passes on
both commits and is excluded). Several local and cloud models solve all 19; the
full table with hardware and average time per task is in
[Results](docs/results.md).

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

For sharing, `fortbench export-public` writes a hardware-free bundle with model
and weight identity, inference settings, model output and the deterministic
evaluation only; see [Publishing results](docs/publishing.md).

## Documentation

- [Running the suite](docs/running.md)
- [Corpus](docs/corpus.md) and [protocol](docs/protocol.md)
- [Results](docs/results.md)
- [Publishing results](docs/publishing.md)
- [Agent adapters](docs/agents.md)

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
