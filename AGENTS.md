# Fortbench contributor guide

- The active public corpus is `tasks/corpus-20-v1/` with twenty frozen tasks.
- Do not mutate published task manifests; version a replacement corpus.
- Prefer deterministic acceptance commands over subjective scoring.
- Keep the public repository runnable with llama.cpp and a generic
  OpenAI-compatible endpoint.
- Never commit `runs/`, raw provider logs, host inventories, timing data, or
  performance reports.
- Public result exports are allowlisted and hardware-free.
- Run `python -m unittest discover -s tests -v` after runner changes.
