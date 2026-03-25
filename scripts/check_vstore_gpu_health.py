#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _alde_pkg_root() -> Path:
    return _repo_root() / "ALDE"


def _default_store_dir() -> Path:
    return _alde_pkg_root() / "AppData" / "VSM_3_Data"


def _ensure_import_path() -> None:
    pkg_root = _alde_pkg_root()
    if str(pkg_root) not in sys.path:
        sys.path.insert(0, str(pkg_root))


def _micromamba_bin() -> Path:
    return _alde_pkg_root() / ".tools" / "micromamba" / "micromamba"


def _gpu_env_prefix() -> Path:
    return _alde_pkg_root() / ".micromamba" / "envs" / "alde-gpu"


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.resolve().relative_to(other.resolve())
        return True
    except ValueError:
        return False


def _in_gpu_env() -> bool:
    return _is_relative_to(Path(sys.executable), _gpu_env_prefix())


def _decode_last_report(raw: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    payload: dict[str, Any] | None = None
    for index, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(raw[index:])
        except Exception:
            continue
        if isinstance(obj, dict) and "healthy" in obj:
            payload = obj
    return payload


def _tail_text(value: str, limit: int = 2000) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def _micromamba_runtime_status() -> dict[str, Any]:
    micromamba_bin = _micromamba_bin()
    env_prefix = _gpu_env_prefix()
    return {
        "available": bool(micromamba_bin.is_file() and os.access(micromamba_bin, os.X_OK) and env_prefix.is_dir()),
        "micromamba_bin": str(micromamba_bin),
        "env_prefix": str(env_prefix),
        "active_python_in_gpu_env": _in_gpu_env(),
    }


def _nvidia_summary() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _collect_runtime_report(store_dir: Path, query_text: str, top_k: int, run_query: bool) -> dict[str, Any]:
    _ensure_import_path()

    from alde.vstores import VectorStore, _faiss_gpu_status  # type: ignore

    manifest_file = store_dir / "manifest.json"
    report: dict[str, Any] = {
        "repo_root": str(_repo_root()),
        "package_root": str(_alde_pkg_root()),
        "python_executable": sys.executable,
        "env": {
            "AI_IDE_VSTORE_GPU_ONLY": os.getenv("AI_IDE_VSTORE_GPU_ONLY"),
            "AI_IDE_FAISS_USE_GPU": os.getenv("AI_IDE_FAISS_USE_GPU"),
            "AI_IDE_FAISS_REQUIRE_GPU": os.getenv("AI_IDE_FAISS_REQUIRE_GPU"),
            "AI_IDE_FAISS_GPU_DEVICE": os.getenv("AI_IDE_FAISS_GPU_DEVICE"),
            "AI_IDE_EMBEDDINGS_DEVICE": os.getenv("AI_IDE_EMBEDDINGS_DEVICE"),
            "HF_TOKEN": "set" if os.getenv("HF_TOKEN") else "unset",
        },
        "nvidia_smi": _nvidia_summary(),
        "micromamba_runtime": _micromamba_runtime_status(),
        "store": {
            "store_dir": str(store_dir),
            "manifest_file": str(manifest_file),
            "store_exists": store_dir.is_dir(),
            "manifest_exists": manifest_file.exists(),
            "index_exists": (store_dir / "index.faiss").exists(),
            "index_pickle_exists": (store_dir / "index.pkl").exists(),
        },
        "faiss_gpu_status": _faiss_gpu_status(),
    }

    try:
        with open(manifest_file, encoding="utf-8") as fh:
            manifest = json.load(fh)
        report["store"]["manifest_entries"] = len(manifest) if isinstance(manifest, list) else None
    except Exception as exc:
        report["store"]["manifest_entries_error"] = f"{type(exc).__name__}: {exc}"

    vs = VectorStore(store_path=str(store_dir), manifest_file=str(manifest_file))
    report["vectorstore"] = {
        "initialized": False,
        "gpu_enabled": False,
        "gpu_device": None,
    }

    try:
        vs._initialize()
        report["vectorstore"]["initialized"] = True
        report["vectorstore"]["embeddings_class"] = type(vs.embeddings).__name__ if vs.embeddings is not None else None
        report["vectorstore"]["embeddings_device"] = str(getattr(getattr(vs.embeddings, "_client", None), "device", None))
    except Exception as exc:
        report["vectorstore"]["initialize_error"] = f"{type(exc).__name__}: {exc}"

    try:
        vs._load_faiss_store()
        if vs.store is not None:
            report["vectorstore"]["cpu_index_ntotal"] = int(vs.store.index.ntotal)
    except Exception as exc:
        report["vectorstore"]["load_error"] = f"{type(exc).__name__}: {exc}"

    try:
        vs._maybe_enable_gpu_index()
        report["vectorstore"]["gpu_enabled"] = bool(getattr(vs, "_gpu_index_enabled", False))
        report["vectorstore"]["gpu_device"] = getattr(vs, "_gpu_device", None)
        if vs.store is not None:
            report["vectorstore"]["active_index_ntotal"] = int(vs.store.index.ntotal)
    except Exception as exc:
        report["vectorstore"]["gpu_enable_error"] = f"{type(exc).__name__}: {exc}"

    if run_query:
        try:
            results = vs.query(query_text, k=top_k)
            report["query"] = {
                "ok": True,
                "query": query_text,
                "result_count": len(results),
                "results": results[:top_k],
            }
        except Exception as exc:
            report["query"] = {
                "ok": False,
                "query": query_text,
                "error": f"{type(exc).__name__}: {exc}",
            }

    healthy = True
    healthy &= bool(report["nvidia_smi"].get("ok"))
    healthy &= bool(report["faiss_gpu_status"].get("available"))
    healthy &= bool(report["store"].get("manifest_exists"))
    healthy &= bool(report["store"].get("index_exists"))
    healthy &= bool(report["vectorstore"].get("initialized"))
    healthy &= bool(report["vectorstore"].get("gpu_enabled"))
    if run_query:
        healthy &= bool(report.get("query", {}).get("ok"))
        healthy &= int(report.get("query", {}).get("result_count", 0)) > 0

    report["healthy"] = healthy
    return report


def _run_micromamba_health_check(store_dir: Path, query_text: str, top_k: int, run_query: bool) -> dict[str, Any]:
    micromamba_bin = _micromamba_bin()
    env_prefix = _gpu_env_prefix()
    script_path = Path(__file__).resolve()

    if not micromamba_bin.is_file() or not os.access(micromamba_bin, os.X_OK):
        return {
            "ok": False,
            "reason": f"micromamba binary not found: {micromamba_bin}",
        }
    if not env_prefix.is_dir():
        return {
            "ok": False,
            "reason": f"micromamba env not found: {env_prefix}",
        }

    cmd = [
        str(micromamba_bin),
        "run",
        "-p",
        str(env_prefix),
        "python",
        str(script_path),
        "--runtime-mode",
        "current",
        "--store-dir",
        str(store_dir),
        "--query",
        query_text,
        "-k",
        str(int(top_k)),
    ]
    if not run_query:
        cmd.append("--skip-query")

    run_env = dict(os.environ)
    run_env.setdefault("MAMBA_ROOT_PREFIX", str(_alde_pkg_root() / ".micromamba"))

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_alde_pkg_root()),
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            check=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"failed to execute micromamba health check: {type(exc).__name__}: {exc}",
        }

    payload = _decode_last_report(proc.stdout or "")
    if payload is None:
        return {
            "ok": False,
            "reason": "micromamba health check did not emit a decodable JSON report",
            "returncode": proc.returncode,
            "stdout_tail": _tail_text(proc.stdout or ""),
            "stderr_tail": _tail_text(proc.stderr or ""),
        }

    return {
        "ok": proc.returncode == 0 or bool(payload.get("healthy")),
        "returncode": proc.returncode,
        "report": payload,
        "stderr_tail": _tail_text(proc.stderr or ""),
    }


def run_health_check(
    store_dir: Path,
    query_text: str,
    top_k: int,
    run_query: bool,
    runtime_mode: str = "auto",
) -> dict[str, Any]:
    current_report = _collect_runtime_report(store_dir, query_text, top_k, run_query)
    execution: dict[str, Any] = {
        "requested_runtime_mode": runtime_mode,
        "effective_runtime": "current",
        "current_python_in_gpu_env": _in_gpu_env(),
        "used_micromamba_worker": False,
    }

    report = dict(current_report)
    report["execution"] = execution

    if runtime_mode == "current":
        return report

    micromamba_status = current_report.get("micromamba_runtime", {})
    should_probe_worker = bool(micromamba_status.get("available")) and not _in_gpu_env()
    if runtime_mode == "micromamba":
        should_probe_worker = bool(micromamba_status.get("available"))

    if not should_probe_worker:
        return report

    worker_probe = _run_micromamba_health_check(store_dir, query_text, top_k, run_query)
    report["current_runtime"] = current_report
    report["worker_runtime"] = worker_probe

    worker_report = worker_probe.get("report") if isinstance(worker_probe, dict) else None
    if isinstance(worker_report, dict):
        effective_report = dict(worker_report)
        effective_report["current_runtime"] = current_report
        effective_report["worker_runtime"] = worker_probe
        effective_report["execution"] = {
            **execution,
            "effective_runtime": "micromamba_gpu_worker",
            "used_micromamba_worker": True,
        }
        return effective_report

    report["execution"] = {
        **execution,
        "worker_probe_failed": True,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_vstore_gpu_health")
    parser.add_argument("--store-dir", default=str(_default_store_dir()), help="Vector store directory to validate")
    parser.add_argument("--query", default="OpenAI embeddings", help="Query text used for the end-to-end check")
    parser.add_argument("-k", type=int, default=2, help="Top-k for the health-check query")
    parser.add_argument("--skip-query", action="store_true", help="Skip the end-to-end query step")
    parser.add_argument(
        "--runtime-mode",
        choices=["auto", "current", "micromamba"],
        default="auto",
        help="auto: prefer repo-local micromamba GPU runtime when current Python is outside it; current: inspect only this interpreter; micromamba: force probing the repo-local micromamba GPU runtime.",
    )
    args = parser.parse_args(argv)

    report = run_health_check(
        Path(args.store_dir).expanduser().resolve(),
        args.query,
        int(args.k),
        not args.skip_query,
        runtime_mode=args.runtime_mode,
    )
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0 if report.get("healthy") else 1


if __name__ == "__main__":
    raise SystemExit(main())