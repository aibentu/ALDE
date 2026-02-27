#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
MICROMAMBA_BIN="$REPO_ROOT/.tools/micromamba/micromamba"
MAMBA_ROOT_PREFIX="$REPO_ROOT/.micromamba"
GPU_ENV_PREFIX="$MAMBA_ROOT_PREFIX/envs/alde-gpu"
CLI_PATH="$REPO_ROOT/alde/vdb_worker_cli.py"

if [[ ! -x "$MICROMAMBA_BIN" ]]; then
  echo "[error] micromamba binary not found or not executable: $MICROMAMBA_BIN" >&2
  exit 1
fi

if [[ ! -d "$GPU_ENV_PREFIX" ]]; then
  echo "[error] GPU env not found: $GPU_ENV_PREFIX" >&2
  echo "Create it first (see FAISS_CUDA_MICROMAMBA_REPLICATION.md)." >&2
  exit 1
fi

if [[ ! -f "$CLI_PATH" ]]; then
  echo "[error] CLI file not found: $CLI_PATH" >&2
  exit 1
fi

if [[ $# -lt 2 ]]; then
  cat >&2 <<'USAGE'
Usage:
  ./run_vdb_gpu.sh <memorydb|vectordb> "<query>" [additional args]

Examples:
  ./run_vdb_gpu.sh memorydb "email Frau Ludmila Schmitt Hochschule fuer Technik und Wirtschaft"
  ./run_vdb_gpu.sh vectordb "python embeddings" -k 10
USAGE
  exit 2
fi

cd "$REPO_ROOT"
MAMBA_ROOT_PREFIX="$MAMBA_ROOT_PREFIX" "$MICROMAMBA_BIN" run -p "$GPU_ENV_PREFIX" \
  python "$CLI_PATH" "$@"
