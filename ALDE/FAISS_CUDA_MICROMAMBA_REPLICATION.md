# FAISS (CUDA/GPU) Setup via micromamba (ALDE replication guide)

This repo uses **FAISS on CUDA (GPU-only)** via a repo-local **micromamba** environment.

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

What this brings in (example from a working machine):
- `faiss 1.7.4 (py310 cuda)`
- `faiss-gpu 1.7.4`
- `libfaiss 1.7.4 cuda112`

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

## 7) Run ALDE vectorstore on GPU

### Canonical command

```bash
cd /home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE
export MAMBA_ROOT_PREFIX="$PWD/.micromamba"

.tools/micromamba/micromamba run -p "$PWD/.micromamba/envs/alde-gpu" \
  python -m alde.vstores
```

### GPU-only policy

The vectorstore defaults to **GPU-only**.

- Enforced by: `AI_IDE_FAISS_REQUIRE_GPU=1` (default)
- If you ever want to allow CPU FAISS: set `AI_IDE_FAISS_REQUIRE_GPU=0`

### Embeddings device

- Default is `auto` (prefers CUDA if available)
- Force embeddings device:

```bash
export AI_IDE_EMBEDDINGS_DEVICE=cuda
# or: export AI_IDE_EMBEDDINGS_DEVICE=cpu
```

---

## 8) Why CPU↔GPU conversion exists in code

LangChain’s FAISS persistence (`save_local` / `load_local`) is CPU-index oriented.

So [alde/vstores.py](alde/vstores.py) follows this runtime model:
- **Persist on CPU** (index files on disk)
- **Query on GPU** by converting the in-memory index with FAISS GPU helpers

This keeps the on-disk index portable while still enforcing GPU-only retrieval at runtime.

---

## 9) Common pitfalls

- Running `alde/vstores.py` from the workspace `.venv` (Python 3.13) will fail with missing `faiss`.
  Use the micromamba env command above.
- `pip install faiss-gpu` is not the right install path here.
- If `_faiss_gpu_status()` reports 0 GPUs, re-check:
  - `nvidia-smi`
  - driver/CUDA availability
  - that you’re actually running inside `.micromamba/envs/alde-gpu`
