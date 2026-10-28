# Results

The published suites score 19 of the 20 frozen tasks. The task
`roots-fortran-26-itp-method-fix` stays in the inventory but is excluded from
scoring because its acceptance command passes on both the base and the fixed
commit.

Models are ordered by number of solved tasks, then by average wall time per
scored task. Hardware is listed because it dominates the time column; cloud and
private endpoints do not report it.

## Recent runs

| Model | Solved | Average time | Hardware |
|---|---:|---:|---|
| DeepSeek V4 Flash via custom endpoint | 19/19 (100%) | 14.3 min/task | Private endpoint, hardware unavailable |
| Qwen3.8-27B via OpenCode/llama.cpp | 19/19 (100%) | 15.4 min/task | 2x NVIDIA RTX 5060 Ti, 16 GB each |

## Earlier runs, rescored to 19 tasks

These runs originally covered all 20 tasks; their scores have been recomputed
without the excluded task.

| Model | Solved | Average time | Hardware |
|---|---:|---:|---|
| Qwen 3.6 27B Q4 | 19/19 (100%) | 10.6 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Qwen 3.5 122B A10B UD-Q4 | 19/19 (100%) | 11.3 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Mistral Medium 3.5 UD-Q4 | 19/19 (100%) | 30.4 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Kimi K2.6 Q4X 32K | 19/19 (100%) | 99.3 min/task | 2x AMD EPYC 9455, RTX PRO 6000 Blackwell Max-Q 96 GB |
| Claude Haiku | 19/19 (100%) | unavailable | Cloud hardware unavailable |
| Qwen 3.6 35B-A3B Q4 | 18/19 (94.7%) | 16.5 min/task | Apple M3 Ultra, 256 GB unified memory |
| Qwen 3.6 35B-A3B Q4 KVQ8 | 18/19 (94.7%) | 17.9 min/task | Apple M3 Ultra, 256 GB unified memory |
| Codex GPT-5.4-mini | 18/19 (94.7%) | unavailable | Cloud hardware unavailable |
| Qwen 3.5 35B-A3B Q8 | 17/19 (89.5%) | 13.6 min/task | Apple M3 Ultra, 256 GB unified memory |
| Qwen 3.6 35B-A3B Q8 | 17/19 (89.5%) | 14.4 min/task | Apple M3 Ultra, 256 GB unified memory |
| Qwen 3.6 27B Q4 KVQ8 | 17/19 (89.5%) | 33.0 min/task | Apple M3 Ultra, 256 GB unified memory |
| Qwen 3.5 122B Q4 KVQ8 | 16/19 (84.2%) | 21.0 min/task | Apple M3 Ultra, 256 GB unified memory |
| Qwen 3.5 35B-A3B Q4 | 15/19 (78.9%) | 4.7 min/task | Apple M3 Ultra, 256 GB unified memory |
| MiniMax M2.5 Q4 KVQ8 | 15/19 (78.9%) | 30.4 min/task | Apple M3 Ultra, 256 GB unified memory |
| MiniMax M2.7 Q4 KVQ8 | 14/19 (73.7%) | 31.0 min/task | Apple M3 Ultra, 256 GB unified memory |
| Gemma 4 26B A4B Q4 | 10/19 (52.6%) | 19.6 min/task | Apple M3 Ultra, 256 GB unified memory |

## Earlier runs, 20-task denominator

Only the summary of these runs survives, so it cannot be determined whether the
excluded task was among their failures. They are kept as historical comparisons
and are not directly comparable with the 19-task scores.

| Model | Solved | Average time | Hardware |
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

## What the numbers mean

A task counts as solved when its deterministic acceptance commands pass within
the three-stage [protocol](protocol.md). Times are wall-clock averages per scored
task and depend on hardware, inference settings and server load. Raw run
artifacts are private; see [publishing results](publishing.md) for the
hardware-free export format.
