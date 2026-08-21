# Fortbench

Fortbench is a reproducible benchmark for real Fortran coding work. It checks
whether an agent can repair twenty frozen issues from public Fortran projects,
using deterministic build and acceptance commands rather than subjective pass
labels.

This repository contains the complete modern `corpus-20-v1` suite, the runner,
the acceptance fixtures, and generic connection paths for llama.cpp and other
OpenAI-compatible endpoints. The results summary records selected historical
hardware and average runtimes; raw run artifacts remain private.

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

Models are ordered by quality first and speed second. Speed is average minutes
per scored task. The current Qwen and DeepSeek rows and the adjusted Cloud/M3
Ultra rows use the 19-task denominator; the four archived scluster 20/20 rows
are also shown as 19/19 because the excluded task was among their solved
tasks.

| Model | Quality | Speed | Hardware | Status |
|---|---:|---:|---|---|
| Qwen 3.6 27B Q4 (scluster) | 19/19 (100%) | 10.6 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB | archived |
| Qwen 3.5 122B A10B UD-Q4 (scluster) | 19/19 (100%) | 11.3 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB | archived |
| DeepSeek V4 Flash via custom endpoint | 19/19 (100%) | 14.3 min/task | Private endpoint, hardware unavailable | complete |
| Qwen3.8-27B via OpenCode/llama.cpp | 19/19 (100%) | 15.4 min/task | 2x NVIDIA RTX 5060 Ti, 16 GB each | complete |
| Mistral Medium 3.5 UD-Q4 (scluster) | 19/19 (100%) | 30.4 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB | archived |
| Kimi K2.6 Q4X 32K (scluster) | 19/19 (100%) | 99.3 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB | archived |
| Claude Haiku (Cloud) | 19/19 (100%) | unavailable | Cloud hardware unavailable | archived |
| Qwen 3.6 35B-A3B Q4 (M3 Ultra) | 18/19 (94.7%) | 16.5 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| Qwen 3.6 35B-A3B Q4 KVQ8 (M3 Ultra) | 18/19 (94.7%) | 17.9 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| Codex GPT-5.4-mini (Cloud) | 18/19 (94.7%) | unavailable | Cloud hardware unavailable | archived |
| Qwen 3.5 35B-A3B Q8 (M3 Ultra) | 17/19 (89.5%) | 13.6 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| Qwen 3.6 35B-A3B Q8 (M3 Ultra) | 17/19 (89.5%) | 14.4 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| Qwen 3.6 27B Q4 KVQ8 (M3 Ultra) | 17/19 (89.5%) | 33.0 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| Qwen 3.5 122B Q4 KVQ8 (M3 Ultra) | 16/19 (84.2%) | 21.0 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| Qwen 3.5 35B-A3B Q4 (M3 Ultra) | 15/19 (78.9%) | 4.7 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| MiniMax M2.5 Q4 KVQ8 (M3 Ultra) | 15/19 (78.9%) | 30.4 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| MiniMax M2.7 Q4 KVQ8 (M3 Ultra) | 14/19 (73.7%) | 31.0 min/task | Apple M3 Ultra, 256 GB unified memory | archived |
| Gemma 4 26B A4B Q4 (M3 Ultra) | 10/19 (52.6%) | 19.6 min/task | Apple M3 Ultra, 256 GB unified memory | archived |

The following completed scluster rows are retained with their original
20-task denominator because only the summary table survived; their task-level
artifacts are not available to determine whether the excluded task was their
failure. They are historical comparisons, not current 19-task scores.

| Model | Archived quality | Speed | Hardware |
|---|---:|---:|---|
| Qwen 3.6 35B-A3B UD-Q4 128K | 19/20 | 6.1 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Gemma 4 31B Q4 | 19/20 | 20.5 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| GLM-4.7 UD-Q2XL 128K | 19/20 | 80.4 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Qwen 3.5 9B Q4 128K | 18/20 | 21.3 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Qwen 3.5 397B A17B UD-Q4 128K | 18/20 | 85.4 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Qwen 3.5 4B Q4 128K | 17/20 | 20.7 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Qwen3 Coder Next Q5KM 32K | 16/20 | 6.4 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| MiniMax M2.7 UD-Q4 128K | 15/20 | 109.3 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| GLM-4.7 Flash UD-Q4XL 128K | 13/20 | 22.1 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Gemma 4 26B A4B UD-Q4 128K | 13/20 | 26.4 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Nemotron-H 120B A12B Q4KM 32K | 10/20 | 10.3 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| GPT-OSS 120B Q4KM 128K | 7/20 | 5.0 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Qwen 3.5 2B Q4 128K | 1/20 | 25.7 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |

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

The summary above is a curated historical comparison and intentionally includes
coarse hardware labels and average runtimes. Public Fortbench export bundles
remain hardware-free: they contain only model and weight identity, inference
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
