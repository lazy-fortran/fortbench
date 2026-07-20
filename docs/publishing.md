# Publishing hardware-free results

Public records describe correctness, not machine performance. A publication
bundle may contain the benchmark/task revision; model and weight identity;
inference engine and version; generation settings; model output; deterministic
status; solved stage; and an optional quality score.

It must not contain hostnames, hardware, RAM, operating-system inventory,
absolute paths, timestamps, durations, latency, throughput, energy, cost,
environment dumps, or raw provider logs.

Keep the raw run private. Build a public record from an explicit allowlist and
review the resulting JSON before committing it. Until the allowlisted exporter
lands, do not copy `results.json`, `summary.*`, `system-config.json`, or
`artifacts/` into this repository.
