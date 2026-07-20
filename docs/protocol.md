# Protocol

Each run uses a clean workspace and three stages:

1. Initial one-shot attempt
2. Self-review and repair using local test/build feedback
3. Final repair and polish

Every stage is a fresh CLI invocation. FortBench does not use
`continue`, session resume, or persistent chat state between stages.
Stages stop early on first acceptance pass. The primary score is
deterministic acceptance status from the per-task validator. Local
rows run in strict series so GPU and inference-server contention
does not skew per-task wall time. Cloud rows can run in bounded
parallel.
