# Agents

FortBench ships six adapter classes (`fortbench/adapters.py`):

- **Codex** -- cloud (gpt-5.4 family) and local profiles (`-p local` via
  llama.cpp Responses API). Used for both cloud baselines and most
  local rows.
- **Claude** -- cloud, Anthropic models. The Haiku row in the 20-task
  cloud comparison runs through this adapter.
- **OpenCode** -- local, open-weight models via llama.cpp.
- **Qwen Code** -- local, Qwen Code CLI.
- **Vibe** -- local, Mistral Vibe CLI for Devstral models.
- **aider** -- local or cloud.

The 20-task corpus comparisons in the published matrix exercise
**Codex**, **Claude**, and **OpenCode**; the other three remain
available but are not part of the current published matrix.

Local serving uses the [krystophny/llama.cpp](https://github.com/krystophny/llama.cpp)
fork with Responses API compliance fixes
([PR #21174](https://github.com/ggml-org/llama.cpp/pull/21174)).
