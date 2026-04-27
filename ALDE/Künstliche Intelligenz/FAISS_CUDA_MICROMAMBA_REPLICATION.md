# FAISS (CUDA/GPU) Setup via micromamba (ALDE replication guide)

This repo uses repo-local **micromamba** for the FAISS GPU runtime.

Current verified state on this machine:
- `faiss 1.7.4`
- `faiss-gpu 1.7.4`
- `libfaiss 1.7.4 cuda112`
- `pytorch 2.4.0` with `pytorch-cuda 11.8`
- `faiss.get_num_gpus() == 1`

Key paths (repo-relative):
- micromamba binary: `.tools/micromamba/micromamba`
- env root: `.micromamba/`
- GPU env prefix: `.micromamba/envs/alde-gpu`

> Important: **Do not** use `pip install faiss-gpu`. PyPI does not provide usable GPU FAISS wheels for this setup.

---

## 0) Prerequisites (host)

1) NVIDIA driver works:

```bash
nvidia-smi
```

2) You are in the repo root:

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
```

---

## 1) Create the `alde-gpu` environment

All commands below use the repo-local micromamba and store everything under `.micromamba/`.

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

# Create env (Python 3.10 is used because GPU FAISS bindings are not available for newer Python versions in typical pip-based setups)
.tools/micromamba/micromamba create -y -p "$PWD/.micromamba/envs/alde-gpu" -c conda-forge \
  python=3.10 pip
```

---

## 2) Install FAISS GPU (CUDA)

Install FAISS from conda-forge (known-good for this repo):

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba install -y -p "$PWD/.micromamba/envs/alde-gpu" -c conda-forge \
  faiss-gpu=1.7.4
```

What this brings in on a known-good setup:
- `faiss 1.7.4 (py310 cuda)`
- `faiss-gpu 1.7.4`
- `libfaiss 1.7.4 cuda112`
- MKL-backed BLAS/LAPACK runtime via conda packages

---

## 3) Install PyTorch with CUDA (optional but used for embeddings)

If you want embeddings on GPU (and to verify CUDA end-to-end), install PyTorch CUDA:

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba install -y -p "$PWD/.micromamba/envs/alde-gpu" \
  -c pytorch -c nvidia \
  pytorch=2.4.0 torchvision=0.19.0 torchaudio=2.4.0 pytorch-cuda=11.8
```

---

## 4) Install Python deps used by `alde.vstores`

At minimum, `alde/vstores.py` expects LangChain packages (FAISS wrapper + loaders/splitters) and an embeddings backend.

If you use OpenAI embeddings:

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" \
  pip install -U \
    langchain-community langchain-core langchain-text-splitters \
    openai python-dotenv
```

If you use HuggingFace/sentence-transformers embeddings:

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" \
  pip install -U \
    langchain-community langchain-core langchain-text-splitters \
    langchain-huggingface sentence-transformers
```

  Optional but recommended when debugging model downloads:

  ```bash
  export HF_TOKEN=...
  ```

---

## 5) Verify FAISS is GPU-enabled

Run this inside the env:

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" python - <<'PY'
import faiss
print('faiss_version', getattr(faiss, '__version__', 'unknown'))
print('has_StandardGpuResources', hasattr(faiss, 'StandardGpuResources'))
print('has_index_cpu_to_gpu', hasattr(faiss, 'index_cpu_to_gpu'))
print('has_index_cpu_to_all_gpus', hasattr(faiss, 'index_cpu_to_all_gpus'))
print('num_gpus', faiss.get_num_gpus() if hasattr(faiss,'get_num_gpus') else None)
PY
```

Expected:
- `has_StandardGpuResources True`
- `has_index_cpu_to_gpu True`
- `has_index_gpu_to_cpu True`
- `num_gpus >= 1`

Note:
- Some FAISS GPU builds do **not** expose `faiss.swigfaiss_gpu` as a separate import. For this repo, the check above is the correct one.

---

## 6) Verify PyTorch sees CUDA (optional)

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" python - <<'PY'
import torch
print('torch', torch.__version__)
print('cuda_available', torch.cuda.is_available())
if torch.cuda.is_available():
    print('cuda_device_count', torch.cuda.device_count())
    print('cuda_device_0', torch.cuda.get_device_name(0))
    print('cuda_capability_0', torch.cuda.get_device_capability(0))
PY
```

---

## 7) Runtime knobs used by the code

The current code in [alde/vstores.py](alde/vstores.py) uses these settings:

- `AI_IDE_FAISS_USE_GPU=1`
  Meaning: when FAISS GPU helpers are available, promote the in-memory CPU index to GPU for query-time search.
- `AI_IDE_FAISS_REQUIRE_GPU=0`
  Meaning: direct `VectorStore` usage may fall back to CPU unless you explicitly require GPU.
- `AI_IDE_FAISS_GPU_DEVICE=0`
  Meaning: choose GPU device index for FAISS CPU→GPU promotion.
- `AI_IDE_EMBEDDINGS_DEVICE=auto`
  Meaning: embeddings prefer CUDA when PyTorch reports it is available.
- `AI_IDE_VSTORE_GPU_ONLY=0`
  Meaning: tool-level queries do not force the micromamba worker unless you opt in.

If you want strict GPU-only behavior end to end, set:

```bash
export AI_IDE_VSTORE_GPU_ONLY=1
export AI_IDE_FAISS_USE_GPU=1
export AI_IDE_FAISS_REQUIRE_GPU=1
export AI_IDE_EMBEDDINGS_DEVICE=cuda
```

## 8) Run ALDE vectorstore on GPU

### Canonical command

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" \
  python -m alde.vstores
```

### Canonical worker query

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"
export AI_IDE_VSTORE_GPU_ONLY=1
export AI_IDE_FAISS_USE_GPU=1
export AI_IDE_FAISS_REQUIRE_GPU=1
export AI_IDE_EMBEDDINGS_DEVICE=cuda

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" \
  python -m alde.vdb_worker_cli memorydb "OpenAI embeddings" -k 3 \
  --store_dir "$PWD/AppData/VSM_3_Data" --pretty 1
```

### Health check

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"
export AI_IDE_VSTORE_GPU_ONLY=1
export AI_IDE_FAISS_USE_GPU=1
export AI_IDE_FAISS_REQUIRE_GPU=1
export AI_IDE_EMBEDDINGS_DEVICE=cuda

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" \
  python ../scripts/check_vstore_gpu_health.py \
  --store-dir "$PWD/AppData/VSM_3_Data" --query "OpenAI embeddings" -k 2
```

### Shell wrapper

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt
./scripts/run_vstore_gpu_health.sh --query "OpenAI embeddings" -k 2
```

Defaults provided by the wrapper:
- `AI_IDE_VSTORE_GPU_ONLY=1`
- `AI_IDE_FAISS_USE_GPU=1`
- `AI_IDE_FAISS_REQUIRE_GPU=1`
- `AI_IDE_EMBEDDINGS_DEVICE=cuda`
- `--store-dir /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE/AppData/VSM_3_Data`

You can still override any of them, for example:

```bash
AI_IDE_EMBEDDINGS_DEVICE=cpu ./scripts/run_vstore_gpu_health.sh --skip-query
./scripts/run_vstore_gpu_health.sh --store-dir /abs/path/to/VSM_1_Data --query "LangChain"
```

This checks:
- host GPU visibility via `nvidia-smi`
- FAISS GPU helper availability
- manifest/index presence and counts
- embedding initialization device
- query-time GPU promotion
- a real end-to-end vector query with result payload inspection

### GPU-only policy

The vectorstore does **not** hard-default to GPU-only.

- Direct `VectorStore` usage promotes to GPU when possible because `AI_IDE_FAISS_USE_GPU=1` by default.
- Strict failure when GPU is unavailable only happens if you set `AI_IDE_FAISS_REQUIRE_GPU=1`.
- Tool-level forced micromamba execution only happens if you set `AI_IDE_VSTORE_GPU_ONLY=1`.

### Embeddings device

- Default is `auto` (prefers CUDA if available)
- Force embeddings device:

```bash
export AI_IDE_EMBEDDINGS_DEVICE=cuda
# or: export AI_IDE_EMBEDDINGS_DEVICE=cpu
```

---

## 9) Why CPU↔GPU conversion exists in code

LangChain’s FAISS persistence (`save_local` / `load_local`) is CPU-index oriented.

So [alde/vstores.py](alde/vstores.py) follows this runtime model:
- **Persist on CPU** (index files on disk)
- **Query on GPU** by converting the in-memory index with FAISS GPU helpers

This keeps the on-disk index portable while still enforcing GPU-only retrieval at runtime.

---

## 10) Rebuild a stale store

If `manifest.json` shows far more entries than the loaded FAISS index reports in `index.ntotal`, the store is stale and should be rebuilt from scratch.

Example for the memory store:

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"
export AI_IDE_FAISS_USE_GPU=1
export AI_IDE_FAISS_REQUIRE_GPU=1
export AI_IDE_EMBEDDINGS_DEVICE=cuda

rm -f AppData/VSM_3_Data/index.faiss AppData/VSM_3_Data/index.pkl AppData/VSM_3_Data/manifest.json
printf '[]\n' > AppData/VSM_3_Data/manifest.json

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" python - <<'PY'
from alde.vstores import VectorStore
store_dir = 'AppData/VSM_3_Data'
vs = VectorStore(store_path=store_dir, manifest_file=f'{store_dir}/manifest.json')
vs.build(store_dir)
print('manifest_entries', len(vs.manifest))
vs._load_faiss_store()
vs._maybe_enable_gpu_index()
print('faiss_vectors', vs.store.index.ntotal)
print('gpu_enabled', getattr(vs, '_gpu_index_enabled', False))
PY
```

Expected after a healthy rebuild:
- `manifest_entries` roughly matches the number of distinct source entries being tracked
- `faiss_vectors` is much larger than the number of manifest entries because each document can produce multiple chunks
- `gpu_enabled True`

---

## 11) Common pitfalls

- Running `alde/vstores.py` from the workspace `.venv` (Python 3.13) will fail with missing `faiss`.
  Use the micromamba env command above.
- `pip install faiss-gpu` is not the right install path here.
- Older broken envs can fail with missing `libmkl_intel_lp64.so.1`. Installing FAISS via conda-forge with its MKL-backed BLAS stack resolves that.
- If `_faiss_gpu_status()` reports 0 GPUs, re-check:
  - `nvidia-smi`
  - driver/CUDA availability
  - that you’re actually running inside `.micromamba/envs/alde-gpu`
- If worker output still looks CPU-only, verify:
  - `AI_IDE_VSTORE_GPU_ONLY=1`
  - `AI_IDE_FAISS_USE_GPU=1`
  - `AI_IDE_FAISS_REQUIRE_GPU=1`
  - the query log prints `FAISS-Index für Query auf GPU aktiviert (device=0).`
- Query payload values in `distance` / `score` are FAISS distances. Lower is better.
