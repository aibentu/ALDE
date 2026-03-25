#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
pkg_root="${repo_root}/ALDE"
micromamba_bin="${pkg_root}/.tools/micromamba/micromamba"
env_prefix="${pkg_root}/.micromamba/envs/alde-gpu"
health_script="${repo_root}/scripts/check_vstore_gpu_health.py"
default_store_dir="${pkg_root}/AppData/VSM_3_Data"

if [[ ! -x "${micromamba_bin}" ]]; then
  echo "micromamba binary not found: ${micromamba_bin}" >&2
  exit 1
fi

if [[ ! -d "${env_prefix}" ]]; then
  echo "micromamba env not found: ${env_prefix}" >&2
  exit 1
fi

if [[ ! -f "${health_script}" ]]; then
  echo "health check script not found: ${health_script}" >&2
  exit 1
fi

export MAMBA_ROOT_PREFIX="${pkg_root}/.micromamba"
export AI_IDE_VSTORE_GPU_ONLY="${AI_IDE_VSTORE_GPU_ONLY:-1}"
export AI_IDE_FAISS_USE_GPU="${AI_IDE_FAISS_USE_GPU:-1}"
export AI_IDE_FAISS_REQUIRE_GPU="${AI_IDE_FAISS_REQUIRE_GPU:-1}"
export AI_IDE_EMBEDDINGS_DEVICE="${AI_IDE_EMBEDDINGS_DEVICE:-cuda}"

has_store_arg=0
for arg in "$@"; do
  if [[ "${arg}" == "--store-dir" ]]; then
    has_store_arg=1
    break
  fi
done

cmd=(
  "${micromamba_bin}" run -p "${env_prefix}"
  python "${health_script}"
)

if [[ ${has_store_arg} -eq 0 ]]; then
  cmd+=(--store-dir "${default_store_dir}")
fi

cmd+=("$@")

cd "${pkg_root}"
exec "${cmd[@]}"