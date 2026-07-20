# Publishing hardware-free results

Public records describe correctness, not machine performance. A publication
bundle may contain the benchmark/task revision; model and weight identity;
inference engine and version; generation settings; model output; deterministic
status; solved stage; and an optional quality score.

It must not contain hostnames, hardware, RAM, operating-system inventory,
absolute paths, timestamps, durations, latency, throughput, energy, cost,
environment dumps, or raw provider logs.

Keep the raw run private. Create a model metadata file from
`examples/public-metadata.json`, then export an allowlisted record:

```bash
fortbench export-public \
  runs/corpus20/results.json \
  public-results/model-name.json \
  --metadata my-model-metadata.json
```

The exporter retains model output and deterministic status, but drops raw logs,
commands, hardware, hostnames, paths, timestamps, and all timing fields. It
redacts absolute paths and network addresses that appear inside model output or
metadata. Review the resulting JSON before committing it. Never copy
`results.json`, `summary.*`, `system-config.json`, or `artifacts/` directly.
