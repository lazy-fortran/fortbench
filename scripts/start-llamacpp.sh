#!/usr/bin/env bash
set -euo pipefail

: "${FORTBENCH_MODEL_FILE:?Set FORTBENCH_MODEL_FILE to a GGUF path}"

server="${LLAMA_SERVER:-llama-server}"
context="${FORTBENCH_CONTEXT_SIZE:-32768}"
port="${FORTBENCH_PORT:-8080}"
alias="${FORTBENCH_SERVED_MODEL:-fortbench-model}"
read -r -a extra_args <<< "${FORTBENCH_LLAMA_ARGS:-}"

exec "$server" \
  --model "$FORTBENCH_MODEL_FILE" \
  --alias "$alias" \
  --host 127.0.0.1 \
  --port "$port" \
  --ctx-size "$context" \
  "${extra_args[@]}"
