try:
    from .get_path import GetPath  # type: ignore
except ImportError as e:
    msg = str(e)
    if "no known parent package" in msg or "attempted relative import" in msg:
        from get_path import GetPath  # type: ignore
    else:
        raise
import os
import hashlib
from datetime import datetime
import json
import glob
import typing
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Any
from dataclasses import dataclass, field
import multiprocessing
import queue as queue_mod

try:
    from .iter_documents import iter_documents
except ImportError as e:  # allow running directly from the repository root
    # Only fall back when this file is executed outside the package context.
    # Don't hide real ImportErrors coming from inside `iter_documents`.
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from iter_documents import iter_documents
    else:
        raise

try:
    from .learning_signals import (  # type: ignore
        compute_reward,
        validate_outcome_event,
        validate_query_event,
    )
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from learning_signals import (  # type: ignore
            compute_reward,
            validate_outcome_event,
            validate_query_event,
        )
    else:
        raise

try:
    from .policy_store import append_event  # type: ignore
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from policy_store import append_event  # type: ignore
    else:
        raise
# Extractor import (local module)
_DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Cover_letters")


def _sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _safe_int(val: object, default: int = 0) -> int:
    try:
        return int(val)  # type: ignore[arg-type]
    except Exception:
        return default


def _load_json_file(path: str) -> object:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # Best-effort recovery:
        # - Prefer the adjacent atomic-write temp file (`.tmp`) if present.
        # - Otherwise, try the newest `*.backup_*.json` in the same directory.
        # If recovery succeeds, preserve the corrupt file and restore a valid JSON.
        candidates: list[str] = []
        tmp = f"{path}.tmp"
        if os.path.exists(tmp):
            candidates.append(tmp)

        base_no_ext = os.path.splitext(path)[0]
        backup_glob = f"{base_no_ext}.backup_*.json"
        backups = glob.glob(backup_glob)
        backups.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
        candidates.extend(backups)

        recovered: object | None = None
        for cand in candidates:
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    recovered = json.load(f)
                break
            except Exception:
                continue

        if recovered is None:
            raise

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        corrupt_path = f"{base_no_ext}.corrupt_{ts}.json"
        try:
            os.replace(path, corrupt_path)
        except Exception:
            # If we can't move it, continue and just overwrite with recovered.
            pass

        try:
            _atomic_write_json(path, recovered)
        except Exception:
            # Fall back: at least return recovered in-memory.
            return recovered

        return recovered


def _atomic_write_json(path: str, payload: object) -> None:
    def _sanitize(obj: Any) -> Any:
        """Recursively coerce data into JSON-safe types."""
        if isinstance(obj, dict):
            safe: dict[str, Any] = {}
            for k, v in obj.items():
                key = k if isinstance(k, (str, int, float, bool)) or k is None else str(k)
                safe[str(key)] = _sanitize(v)
            return safe
        if isinstance(obj, list):
            return [_sanitize(x) for x in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        try:
            return str(obj)
        except Exception:
            return "[unserializable]"
    
    tmp = f"{path}.tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_sanitize(payload), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _default_dispatcher_db_path() -> str:
    # Keep this local and file-based for now (schema can be swapped later).
    base = GetPath()._parent(parg=f"{__file__}")
    return os.path.join(base, "AppData", "dispatcher_doc_db.json")


def _load_dispatcher_db(db_path: str) -> dict:
    if not os.path.exists(db_path):
        return {"schema": "dispatcher_doc_db_v1", "documents": {}}
    raw = _load_json_file(db_path)
    if isinstance(raw, dict) and isinstance(raw.get("documents"), dict):
        return raw
    # Backward/unknown format: wrap safely.
    return {"schema": "dispatcher_doc_db_v1", "documents": {}}


def _save_dispatcher_db(db_path: str, db: dict) -> None:
    _atomic_write_json(db_path, db)


def dispatch_job_posting_pdfs(
    scan_dir: str,
    db: dict | None = None,
    db_path: str | None = None,
    thread_id: str | None = None,
    dispatcher_message_id: str | None = None,
    recursive: bool = True,
    extensions: list | None = None,
    max_files: int | None = None,
    parser_agent_name: str = "_job_posting_parser",
    dry_run: bool = False,
) -> dict:
    """Discover PDFs, fingerprint them, check/update a small DB, and prepare parser handoffs.

    This is intentionally deterministic and does not read/parse PDF contents.
    """

    ts = datetime.utcnow().isoformat() + "Z"
    scan_dir_original = str(scan_dir or "")
    scan_dir = os.path.abspath(os.path.expanduser(scan_dir_original))
    thread_id = (thread_id or "UNKNOWN")
    dispatcher_message_id = (dispatcher_message_id or "UNKNOWN")

    if extensions is None:
        extensions = [".pdf", ".PDF"]   
    ext_set = {str(e) for e in extensions}

    # Resolve DB path
    resolved_db_path = (
        (db or {}).get("path") if isinstance(db, dict) else None
    ) or db_path or _default_dispatcher_db_path()
    resolved_db_path = os.path.abspath(os.path.expanduser(str(resolved_db_path)))

    warnings: list[dict] = []

    # If the model passes placeholder paths like "/path/to/jobs", try to infer
    # the intended scan_dir from nearby, reliable inputs (DB path / repo layout).
    if not os.path.isdir(scan_dir):
        fallback_candidates: list[tuple[str, str]] = []
        # 1) Most reliable: scan alongside the dispatcher DB (often lives next to PDFs).
        try:
            db_parent = os.path.dirname(resolved_db_path)
            if db_parent:
                fallback_candidates.append((db_parent, "fallback_to_db_parent"))
        except Exception:
            pass
        # 2) Common project layout: AppData/VSM_4_Data next to this module.
        try:
            base = GetPath()._parent(parg=f"{__file__}")
            vsm4 = os.path.join(base, "AppData", "VSM_4_Data")
            fallback_candidates.append((vsm4, "fallback_to_default_vsm4"))
        except Exception:
            pass

        for candidate, reason in fallback_candidates:
            cand = os.path.abspath(os.path.expanduser(str(candidate)))
            if os.path.isdir(cand):
                warnings.append({
                    "warning": "scan_dir_not_found_using_fallback",
                    "scan_dir_original": scan_dir_original,
                    "scan_dir_used": cand,
                    "reason": reason,
                })
                scan_dir = cand
                break

    # DB reachability check
    db_load_error: str | None = None
    dispatcher_db: dict | None = None
    try:
        dispatcher_db = _load_dispatcher_db(resolved_db_path)
    except Exception as e:
        db_load_error = f"{type(e).__name__}: {e}"

    if db_load_error and not dry_run:
        return {
            "agent": "data_dispatcher",
            "scan_dir": scan_dir,
            "timestamp": ts,
            "db": {"path": resolved_db_path, "reachable": False, "error": db_load_error},
            "summary": {"pdf_found": 0, "new": 0, "known_unprocessed": 0, "known_processing": 0, "known_processed": 0, "errors": 1},
            "forwarded": [],
            "handoff_messages": [],
            "errors": [{"path": scan_dir, "error": "db_unreachable", "detail": db_load_error}],
        }

    # Collect files
    pdf_paths: list[str] = []
    errors: list[dict] = []
    if not os.path.isdir(scan_dir):
        return {
            "agent": "data_dispatcher",
            "scan_dir": scan_dir,
            "timestamp": ts,
            "db": {"path": resolved_db_path, "reachable": db_load_error is None, "error": db_load_error},
            "summary": {"pdf_found": 0, "new": 0, "known_unprocessed": 0, "known_processing": 0, "known_processed": 0, "errors": 1},
            "forwarded": [],
            "handoff_messages": [],
            "warnings": warnings,
            "errors": [{"path": scan_dir, "error": "scan_dir_not_found"}],
        }

    if recursive:
        for root, dirs, files in os.walk(scan_dir):
            # Never treat our generated outputs as inputs.
            # This prevents polluting the dispatcher DB with cover-letter PDFs.
            dirs[:] = [
                d
                for d in dirs
                if not str(d).startswith("Cover_letters")
            ]
            for fn in files:
                if fn == "Muster_Anschreiben.pdf":
                    continue
                if any(fn.endswith(ext) for ext in ext_set):
                    pdf_paths.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(scan_dir):
            if fn == "Muster_Anschreiben.pdf":
                continue
            p = os.path.join(scan_dir, fn)
            if os.path.isfile(p) and any(fn.endswith(ext) for ext in ext_set):
                pdf_paths.append(p)

    pdf_paths.sort()
    if max_files is not None:
        pdf_paths = pdf_paths[: max(0, int(max_files))]

    # Classification buckets
    new_items: list[dict] = []
    known_unprocessed: list[dict] = []
    known_processing: list[dict] = []
    known_processed: list[dict] = []
    error_items: list[dict] = []
    forwarded: list[dict] = []
    handoff_messages: list[dict] = []
    duplicates: list[dict] = []

    seen_hashes: set[str] = set()
    docs = (dispatcher_db or {"documents": {}}).get("documents", {}) if isinstance(dispatcher_db, dict) else {}

    def _classify_record(rec: dict | None) -> str:
        if not rec:
            return "new"
        if rec.get("processed") is True or rec.get("processing_state") == "processed":
            return "known_processed"
        st = (rec.get("processing_state") or "").lower().strip()
        if st in {"queued", "processing"}:
            return "known_processing"
        # new/failed/unknown => treat as unprocessed
        return "known_unprocessed"

    for path in pdf_paths:
        abs_path = os.path.abspath(path)
        try:
            st = os.stat(abs_path)
            file_size_bytes = _safe_int(getattr(st, "st_size", 0), 0)
            mtime_epoch = _safe_int(getattr(st, "st_mtime", 0), 0)
        except Exception as e:
            err = {"path": abs_path, "error": "stat_failed", "detail": f"{type(e).__name__}: {e}"}
            errors.append(err)
            error_items.append(err)
            continue

        # Readability + hash
        try:
            content_sha256 = _sha256_file(abs_path)
        except Exception as e:
            err = {"path": abs_path, "error": "unreadable", "detail": f"{type(e).__name__}: {e}"}
            errors.append(err)
            error_items.append(err)
            continue

        if content_sha256 in seen_hashes:
            duplicates.append({"path": abs_path, "content_sha256": content_sha256})
            continue
        seen_hashes.add(content_sha256)

        rec = docs.get(content_sha256) if isinstance(docs, dict) else None
        bucket = _classify_record(rec if isinstance(rec, dict) else None)
        item = {
            "path": abs_path,
            "name": os.path.basename(abs_path),
            "content_sha256": content_sha256,
            "file_size_bytes": file_size_bytes,
            "mtime_epoch": mtime_epoch,
            "db": {
                "existing_record_id": (rec or {}).get("id") if isinstance(rec, dict) else None,
                "processed": (rec or {}).get("processed") if isinstance(rec, dict) else None,
                "processing_state": (rec or {}).get("processing_state") if isinstance(rec, dict) else None,
            },
        }

        if bucket == "new":
            new_items.append(item)
        elif bucket == "known_unprocessed":
            known_unprocessed.append(item)
        elif bucket == "known_processing":
            known_processing.append(item)
        else:
            known_processed.append(item)

    # Upsert + build handoffs
    def _try_write_db() -> tuple[bool, str | None]:
        if dispatcher_db is None:
            return False, "db_not_loaded"
        try:
            _save_dispatcher_db(resolved_db_path, dispatcher_db)
            return True, None
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    to_forward = new_items + known_unprocessed
    for item in to_forward:
        sha = item["content_sha256"]
        rec = docs.get(sha) if isinstance(docs, dict) else None

        # If DB was not reachable and we're not in dry-run, do not forward blind.
        if dispatcher_db is None and not dry_run:
            errors.append({"path": item["path"], "error": "db_unreachable"})
            continue

        db_write_ok = True
        db_write_err: str | None = None

        if not dry_run and isinstance(dispatcher_db, dict):
            if "documents" not in dispatcher_db or not isinstance(dispatcher_db.get("documents"), dict):
                dispatcher_db["documents"] = {}
            docs = dispatcher_db["documents"]

            current = docs.get(sha) if isinstance(docs, dict) else None
            current_state = (current or {}).get("processing_state") if isinstance(current, dict) else None
            if (current_state or "").lower().strip() not in {"queued", "processing"}:
                # Upsert record as queued
                new_rec = dict(current) if isinstance(current, dict) else {}
                new_rec.setdefault("id", sha)
                new_rec["content_sha256"] = sha
                new_rec["source_path"] = item["path"]
                new_rec["file_size_bytes"] = item["file_size_bytes"]
                new_rec["mtime_epoch"] = item["mtime_epoch"]
                new_rec["last_seen_at"] = ts
                new_rec["processed"] = False
                new_rec["processing_state"] = "queued"
                docs[sha] = new_rec
                ok, err = _try_write_db()
                db_write_ok = ok
                db_write_err = err

        if not dry_run and not db_write_ok:
            # Policy: do not forward untracked.
            errors.append({
                "path": item["path"],
                "error": "db_write_failed",
                "detail": db_write_err,
                "content_sha256": sha,
            })
            continue

        payload = {
            "type": "job_posting_pdf",
            "correlation_id": sha,
            "link": {"thread_id": thread_id, "message_id": "PENDING"},
            "file": {
                "path": item["path"],
                "name": item["name"],
                "content_sha256": sha,
                "file_size_bytes": item["file_size_bytes"],
                "mtime_epoch": item["mtime_epoch"],
            },
            "db": {
                "existing_record_id": (rec or {}).get("id") if isinstance(rec, dict) else None,
                "processing_state": "queued" if not dry_run else ((rec or {}).get("processing_state") if isinstance(rec, dict) else "new"),
            },
            "requested_actions": ["parse", "extract_text", "store_job_posting", "mark_processed_on_success"],
        }

        if dry_run:
            continue

        forwarded.append({
            "path": item["path"],
            "content_sha256": sha,
            "link": {"thread_id": thread_id, "message_id": "PENDING"},
        })
        handoff_messages.append({
            "target_agent": parser_agent_name,
            "message_text": json.dumps(payload, ensure_ascii=False),
            "correlation_id": sha,
            "dispatcher_message_id": dispatcher_message_id,
        })

    report = {
        "agent": "data_dispatcher",
        "scan_dir": scan_dir,
        "timestamp": ts,
        "db": {"path": resolved_db_path, "reachable": db_load_error is None, "error": db_load_error},
        "warnings": warnings,
        "summary": {
            "pdf_found": len(pdf_paths),
            "new": len(new_items),
            "known_unprocessed": len(known_unprocessed),
            "known_processing": len(known_processing),
            "known_processed": len(known_processed),
            "duplicates": len(duplicates),
            "errors": len(errors),
        },
        "classified": {
            "new": new_items,
            "known_unprocessed": known_unprocessed,
            "known_processing": known_processing,
            "known_processed": known_processed,
            "error": error_items,
            "duplicates": duplicates,
        },
        "forwarded": forwarded,
        "handoff_messages": handoff_messages,
        "errors": errors,
        "input": {
            "thread_id": thread_id,
            "dispatcher_message_id": dispatcher_message_id,
            "recursive": bool(recursive),
            "extensions": list(ext_set),
            "max_files": max_files,
            "parser_agent_name": parser_agent_name,
            "dry_run": bool(dry_run),
        },
    }
    return report


def batch_generate_cover_letters(
    scan_dir: str,
    profile_path: str,
    db_path: str,
    out_dir: str | None = None,
    model: str = "gpt-4o-mini",
    max_files: int | None = None,
    max_text_chars: int = 20000,
    dry_run: bool = False,
    write_pdf: bool = True,
    rerun_processed: bool = False,
) -> dict:
    """Batch-generate cover letters for all job-offer PDFs in a directory.

    Thin wrapper around `alde.batch_cover_letters.batch_generate` so it can be used
    via the unified tool dispatcher (tool calling).
    """
    try:
        from .batch_cover_letters import batch_generate  # type: ignore
    except Exception:
        from batch_cover_letters import batch_generate  # type: ignore

    return batch_generate(
        scan_dir=scan_dir,
        profile_path=profile_path,
        dispatcher_db_path=db_path,
        out_dir=out_dir,
        model=model,
        max_files=max_files,
        max_text_chars=max_text_chars,
        dry_run=dry_run,
        write_pdf=write_pdf,
        rerun_processed=rerun_processed,
    )


def md_to_pdf(
    md_path: str,
    pdf_path: str,
    title: str | None = None,
    author: str | None = None,
    pagesize: str = "A4",
    margin_left_mm: float = 18,
    margin_right_mm: float = 18,
    margin_top_mm: float = 16,
    margin_bottom_mm: float = 16,
) -> dict:
    """Convert a Markdown file to a clean PDF (ReportLab).

    Notes:
    - Supported pagesizes: A4, LETTER
    - Margins are in millimetres.
    """

    from pathlib import Path
    from reportlab.lib.pagesizes import A4, LETTER  # type: ignore

    try:
        from .md_to_pdf import PdfOptions, markdown_to_pdf  # type: ignore
    except Exception:
        from md_to_pdf import PdfOptions, markdown_to_pdf  # type: ignore

    md_p = Path(md_path).expanduser()
    pdf_p = Path(pdf_path).expanduser()
    pdf_p.parent.mkdir(parents=True, exist_ok=True)

    ps = (pagesize or "A4").strip().upper()
    if ps not in {"A4", "LETTER"}:
        raise ValueError(f"Unsupported pagesize: {pagesize!r} (use 'A4' or 'LETTER')")

    rl_pagesize = A4 if ps == "A4" else LETTER

    options = PdfOptions(
        title=title,
        author=author,
        pagesize=rl_pagesize,
        margin_left_mm=float(margin_left_mm),
        margin_right_mm=float(margin_right_mm),
        margin_top_mm=float(margin_top_mm),
        margin_bottom_mm=float(margin_bottom_mm),
    )

    markdown_to_pdf(md_p, pdf_p, options=options)

    try:
        size_bytes = pdf_p.stat().st_size
    except Exception:
        size_bytes = None

    return {
        "ok": True,
        "md_path": str(md_p),
        "pdf_path": str(pdf_p),
        "bytes": size_bytes,
        "pagesize": ps,
        "margins_mm": {
            "left": float(margin_left_mm),
            "right": float(margin_right_mm),
            "top": float(margin_top_mm),
            "bottom": float(margin_bottom_mm),
        },
    }





@dataclass
class ParamSpec:
    """Parameter specification for tool functions."""
    name: str
    type: str = "string"  # string, number, boolean, array, object
    description: str = ""
    required: bool = False
    enum: list | None = None
    items: dict | None = None
    default: any = None

    def to_python_type(self) -> str:
        """Convert JSON schema type to Python type hint."""
        type_map = {
            "string": "str",
            "number": "float",
            "integer": "int",
            "boolean": "bool",
            "array": "list",
            "object": "dict"
        }
        py_type = type_map.get(self.type, "Any")
        if not self.required:
            py_type = f"{py_type} | None"
        return py_type
    
    def to_tool_property(self) -> dict:
        """Convert to OpenAI tool parameter property."""
        prop = {"type": self.type, "description": self.description}
        if self.enum:
            prop["enum"] = self.enum #:list
        if self.items:
            prop["items"] = self.items #:dict
        elif self.type == "array":
            # OpenAI requires `items` for arrays in JSON schema.
            # Default to string to remain permissive unless specified.
            prop["items"] = {"type": "string"}
        return prop


def call(phone_number: str, message: str | None = None) -> str:
    """Placeholder for initiating a phone call."""
    return f"Calling {phone_number}" + (f" with message: {message}" if message else "")
def accept_call(call_id: str) -> str:

    """Placeholder for accepting an incoming call."""
    return f"Call {call_id} accepted."

def reject_call(call_id: str, reason: str | None = None) -> str:
    """Placeholder for rejecting an incoming call."""
    return f"Call {call_id} rejected" + (f": {reason}" if reason else ".")

def calendar(event: str, date: str, time: str) -> str:
    """Placeholder for calendar scheduling."""
    return f"Event '{event}' scheduled on {date} at {time}."

def send_mail(recipient: str, subject: str, body: str) -> str:
    """Placeholder for sending an email."""
    return f"Email sent to {recipient} with subject '{subject}'.\nBody:\n{body}"

def dml_tool(operation: str, data: str) -> str:
    """Placeholder for Data Manipulation Language tool."""
    return f"DML Tool executed: operation='{operation}', data='{data}...'"
def dsl_tool(operation: str, data: str) -> str:
    """Placeholder for Data Scripting Language tool."""

    return f"DSL Tool executed: operation='{operation}', data='{data}...'"
def code_tool(operation: str, data: str) -> str:
    """Placeholder for Code Manipulation Language tool."""

    return f"Code Tool executed: operation='{operation}', data='{data}...'"
def fetch_url(url: str) -> str:
    """Fetch content from a URL."""


_VSTORE_AUTOBUILD = os.getenv("AI_IDE_VSTORE_AUTOBUILD", "0").strip() in {"1", "true", "True"}
_VSTORE_TOOL_TIMEOUT_S = float(os.getenv("AI_IDE_VSTORE_TOOL_TIMEOUT_S", "45"))
_VSTORE_TOOL_TIMEOUT_AUTOBUILD_S = float(
    os.getenv("AI_IDE_VSTORE_TOOL_TIMEOUT_AUTOBUILD_S", "120")
)
_VSTORE_MP_START = os.getenv("AI_IDE_VSTORE_MP_START", "auto").strip().lower()  # auto|spawn|fork|forkserver

# Administrative vector-store operations can take longer (build/index).
_VDB_WORKER_TIMEOUT_S = float(os.getenv("AI_IDE_VDB_WORKER_TIMEOUT_S", "300"))

# Tool output limits (prevents prompt blow-ups / UI hangs)
_TOOL_MAX_ITEMS = int(os.getenv("AI_IDE_VSTORE_TOOL_MAX_ITEMS", "5") or 5)
_TOOL_MAX_TOTAL_CHARS = int(os.getenv("AI_IDE_VSTORE_TOOL_MAX_TOTAL_CHARS", "12000") or 12000)
_TOOL_MAX_CONTENT_CHARS = int(os.getenv("AI_IDE_VSTORE_TOOL_MAX_CONTENT_CHARS", "1500") or 1500)
_TOOL_INCLUDE_METADATA = os.getenv("AI_IDE_VSTORE_TOOL_INCLUDE_METADATA", "0").strip() in {"1", "true", "True"}


def _effective_vstore_timeout_s(autobuild: bool | None) -> float:
    do_autobuild = _VSTORE_AUTOBUILD if autobuild is None else bool(autobuild)
    return _VSTORE_TOOL_TIMEOUT_AUTOBUILD_S if do_autobuild else _VSTORE_TOOL_TIMEOUT_S


def _micromamba_gpu_env() -> tuple[str, str, str] | None:
    """Return (repo_root, micromamba_bin, env_path) if present."""
    try:
        repo_root = str(Path(__file__).resolve().parents[1])
        micromamba = os.path.join(repo_root, ".tools", "micromamba", "micromamba")
        env_path = os.path.join(repo_root, ".micromamba", "envs", "alde-gpu")
        if os.path.exists(micromamba) and os.path.isdir(env_path):
            return repo_root, micromamba, env_path
    except Exception:
        pass
    return None


def _looks_like_missing_gpu_faiss(msg: str) -> bool:
    m = (msg or "").lower()
    needles = (
        "faiss gpu required",
        "could not import faiss",
        "no module named 'faiss'",
        "no module named \"faiss\"",
        "faiss module not installed",
        "cpu-only build",
        "has no gpu bindings",
        "faiss reports 0 gpus",
    )
    return any(n in m for n in needles)


def _run_vectordb_in_micromamba(
    kind: str,
    query: str,
    k: int,
    *,
    store_dir: str | None = None,
    manifest_file: str | None = None,
    root_dir: str | None = None,
    autobuild: bool | None = None,
) -> list | str:
    """Run vectorstore query in the repo-local micromamba GPU env."""
    timeout_s = _effective_vstore_timeout_s(autobuild)
    env = _micromamba_gpu_env()
    if env is None:
        return (
            f"{kind} error: FAISS GPU required but current interpreter cannot provide it, "
            "and no local micromamba GPU env was found (.micromamba/envs/alde-gpu)."
        )
    repo_root, micromamba, env_path = env

    cmd: list[str] = [
        micromamba,
        "run",
        "-p",
        env_path,
        "python",
        "-m",
        "alde.vdb_worker_cli",
        kind,
        query,
        "-k",
        str(int(k)),
    ]

    if store_dir:
        cmd.extend(["--store_dir", str(store_dir)])
    if manifest_file:
        cmd.extend(["--manifest_file", str(manifest_file)])
    if root_dir:
        cmd.extend(["--root_dir", str(root_dir)])
    if autobuild is not None:
        cmd.extend(["--autobuild", "1" if bool(autobuild) else "0"])
    # Worker protocol should stay single-line JSON to make parsing robust.
    cmd.extend(["--pretty", "0"])

    run_env = dict(os.environ)
    run_env.setdefault("MAMBA_ROOT_PREFIX", os.path.join(repo_root, ".micromamba"))

    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=float(timeout_s),
        )
    except subprocess.TimeoutExpired:
        return (
            f"{kind} timed out after {timeout_s:.0f}s (micromamba GPU worker). "
            "Set AI_IDE_VSTORE_TOOL_TIMEOUT_AUTOBUILD_S (autobuild) or "
            "AI_IDE_VSTORE_TOOL_TIMEOUT_S (standard) for longer operations."
        )
    except Exception as e:
        return f"{kind} error: failed to run micromamba GPU worker ({type(e).__name__}: {e})"

    out = (proc.stdout or "").strip()
    if not out:
        err = (proc.stderr or "").strip()
        return f"{kind} error: micromamba GPU worker produced no output (exitcode={proc.returncode}). {err}"

    # The worker may emit logs/prints before the JSON payload.
    # Find the last decodable JSON object containing an "ok" key.
    raw = out
    payload: object | None = None
    decoder = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(raw[i:])
        except Exception:
            continue
        if isinstance(obj, dict) and "ok" in obj:
            payload = obj

    if payload is None:
        err = (proc.stderr or "").strip()
        return f"{kind} error: invalid JSON from micromamba GPU worker. stdout={raw[:500]} stderr={err[:500]}"

    if isinstance(payload, dict) and payload.get("ok") is True:
        return payload.get("result")
    if isinstance(payload, dict):
        return f"{kind} error: {payload.get('error', 'unknown')}"
    return f"{kind} error: invalid result payload from micromamba GPU worker"


def _shrink_vectordb_result(result: object, k: int) -> object:
    """Shrink tool results so they are safe to send back into the LLM context."""
    try:
        if isinstance(result, list):
            items = result[: max(1, min(int(k), _TOOL_MAX_ITEMS))]
            shrunk: list = []
            for it in items:
                if isinstance(it, dict):
                    content = str(it.get("content", ""))
                    if _TOOL_MAX_CONTENT_CHARS > 0 and len(content) > _TOOL_MAX_CONTENT_CHARS:
                        content = content[:_TOOL_MAX_CONTENT_CHARS] + "\n…[truncated]"
                    out = {
                        "rank": it.get("rank"),
                        "score": it.get("score"),
                        "source": it.get("source"),
                        "title": it.get("title"),
                        "page": it.get("page"),
                        "content": content,
                    }
                    if _TOOL_INCLUDE_METADATA and isinstance(it.get("metadata"), dict):
                        out["metadata"] = it.get("metadata")
                    shrunk.append(out)
                else:
                    shrunk.append(str(it)[:_TOOL_MAX_CONTENT_CHARS])

            # Global cap (approx) by JSON size.
            try:
                blob = json.dumps(shrunk, ensure_ascii=False)
                if _TOOL_MAX_TOTAL_CHARS > 0 and len(blob) > _TOOL_MAX_TOTAL_CHARS:
                    # Hard truncate the serialized form; return as string with note.
                    return blob[:_TOOL_MAX_TOTAL_CHARS] + "\n…[truncated-total]"
            except Exception:
                pass
            return shrunk

        if isinstance(result, dict):
            blob = json.dumps(result, ensure_ascii=False)
            if _TOOL_MAX_TOTAL_CHARS > 0 and len(blob) > _TOOL_MAX_TOTAL_CHARS:
                return blob[:_TOOL_MAX_TOTAL_CHARS] + "\n…[truncated-total]"
            return result

        # Strings or other objects
        s = str(result)
        if _TOOL_MAX_TOTAL_CHARS > 0 and len(s) > _TOOL_MAX_TOTAL_CHARS:
            return s[:_TOOL_MAX_TOTAL_CHARS] + "\n…[truncated-total]"
        return result
    except Exception:
        return "[tool result could not be shrunk]"


def _vectordb_worker(
    kind: str,
    query: str,
    k: int,
    store_dir: str | None,
    manifest_file: str | None,
    root_dir: str | None,
    autobuild: bool | None,
    result_q,
) -> None:
    """Run VectorStore build/query in a child process.

    A segfault in native deps (torch/faiss) will only kill the child.
    """
    try:
        import faulthandler

        faulthandler.enable(all_threads=True)
    except Exception:
        pass

    try:
        # Local imports inside the child keep the main GUI process safer.
        try:
            from .get_path import GetPath  # type: ignore
        except ImportError as e:
            msg = str(e)
            if "no known parent package" in msg or "attempted relative import" in msg:
                from get_path import GetPath  # type: ignore
            else:
                raise

        try:
            from .vstores import VectorStore  # type: ignore
        except Exception:
            from vstores import VectorStore  # type: ignore

        resolved_store_dir, resolved_manifest = _resolve_vectordb_paths(kind, store_dir, manifest_file)
        db = VectorStore(store_path=resolved_store_dir, manifest_file=resolved_manifest)

        do_autobuild = _VSTORE_AUTOBUILD if autobuild is None else bool(autobuild)
        if do_autobuild:
            # Default build root is the project root.
            default_root = GetPath().get_path(parg=f"{__file__}", opt="p")
            db.build(root_dir or default_root)
        result = db.query(query, k=int(k))
        result = _shrink_vectordb_result(result, int(k))
        result_q.put({"ok": True, "result": result})
    except BaseException as e:
        # Must catch BaseException so we also report SystemExit in case
        # underlying code tries to sys.exit().
        result_q.put({"ok": False, "error": f"{type(e).__name__}: {e}"})


def _default_appdata_dir() -> str:
    base = GetPath()._parent(parg=f"{__file__}")
    return os.path.join(base, "AppData")


def _resolve_vectordb_paths(
    kind: str,
    store_dir: str | None,
    manifest_file: str | None,
) -> tuple[str, str]:
    """Resolve user/tool arguments into (store_dir, manifest_file).

    `store_dir` can be:
    - an explicit path (absolute/relative/~), OR
    - a store id/name like "3" or "VSM_3_Data" which maps under canonical AppData.

    When omitted, defaults to the historical locations:
    - memorydb => AppData/VSM_3_Data
    - vectordb => AppData/VSM_1_Data
    """
    if not store_dir:
        appdata = _default_appdata_dir()
        if kind == "memorydb":
            d = os.path.join(appdata, "VSM_3_Data")
        else:
            d = os.path.join(appdata, "VSM_1_Data")
        m = manifest_file or os.path.join(d, "manifest.json")
        return d, m

    raw = str(store_dir).strip()

    # Heuristic: treat as filesystem path when it looks like one.
    looks_like_path = (
        raw.startswith(("/", "./", "../", "~"))
        or ("/" in raw)
        or ("\\" in raw)
    )

    if looks_like_path:
        d = os.path.abspath(os.path.expanduser(raw))
        m = manifest_file or os.path.join(d, "manifest.json")
        return d, m

    # Otherwise, interpret as store id/name under AppData (same logic as vdb_worker).
    d, _store_name, m = _resolve_vsm_store_dir(raw)
    if manifest_file:
        m = str(manifest_file)
    return d, m


def _resolve_vsm_store_dir(store: str | None) -> tuple[str, str, str]:
    """Resolve a store identifier into (store_dir, store_name, manifest_file)."""
    appdata = _default_appdata_dir()
    os.makedirs(appdata, exist_ok=True)

    def _sanitize(name: str) -> str:
        name = (name or "").strip()
        # prevent path traversal / separators
        name = name.replace("/", "_").replace("\\", "_")
        safe = "".join(ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in name)
        return safe.strip("_")

    if store is None or str(store).strip() == "":
        # Auto-pick next numeric store.
        existing_nums: list[int] = []
        with os.scandir(appdata) as it:
            for entry in it:
                if not entry.is_dir():
                    continue
                nm = entry.name
                if nm.startswith("VSM_") and nm.endswith("_Data"):
                    mid = nm[len("VSM_") : -len("_Data")]
                    if mid.isdigit():
                        try:
                            existing_nums.append(int(mid))
                        except Exception:
                            pass
        next_num = (max(existing_nums) + 1) if existing_nums else 0
        store_name = f"VSM_{next_num}_Data"
    else:
        raw = str(store).strip()
        if raw.isdigit():
            store_name = f"VSM_{raw}_Data"
        else:
            safe = _sanitize(raw)
            if safe.startswith("VSM_") and safe.endswith("_Data"):
                store_name = safe
            elif safe.startswith("VSM_"):
                store_name = f"{safe}_Data"
            else:
                store_name = f"VSM_{safe}_Data"

    store_dir = os.path.join(appdata, store_name)
    manifest_file = os.path.join(store_dir, "manifest.json")
    return store_dir, store_name, manifest_file


def _vdb_admin_worker(
    operation: str,
    store: str | None,
    root_dir: str | None,
    force: bool,
    remove_store_dir: bool,
    result_q,
) -> None:
    """Run vdb administrative operations in a child process."""
    try:
        import faulthandler

        faulthandler.enable(all_threads=True)
    except Exception:
        pass

    try:
        import shutil
        import contextlib

        # Local imports inside the child keep the main GUI process safer.
        try:
            from .get_path import GetPath  # type: ignore
        except ImportError as e:
            msg = str(e)
            if "no known parent package" in msg or "attempted relative import" in msg:
                from get_path import GetPath  # type: ignore
            else:
                raise

        try:
            from .vstores import VectorStore  # type: ignore
        except Exception:
            from vstores import VectorStore  # type: ignore

        op = (operation or "").strip().lower()
        store_dir, store_name, manifest_file = _resolve_vsm_store_dir(store)

        def _is_safe_store_dir(p: str) -> bool:
            # Only allow operations under <repo>/<pkg>/AppData/VSM_*_Data
            appdata = os.path.abspath(_default_appdata_dir())
            p_abs = os.path.abspath(p)
            if not p_abs.startswith(appdata + os.sep):
                return False
            base = os.path.basename(p_abs)
            return base.startswith("VSM_") and base.endswith("_Data")

        if op in {"list", "ls"}:
            appdata = _default_appdata_dir()
            stores: list[dict] = []
            if os.path.isdir(appdata):
                with os.scandir(appdata) as it:
                    for entry in it:
                        if not entry.is_dir():
                            continue
                        nm = entry.name
                        if not (nm.startswith("VSM_") and nm.endswith("_Data")):
                            continue
                        d = entry.path
                        stores.append(
                            {
                                "name": nm,
                                "dir": d,
                                "manifest": os.path.join(d, "manifest.json"),
                                "has_index": os.path.exists(os.path.join(d, "index.faiss")),
                            }
                        )
            stores.sort(key=lambda x: x.get("name", ""))
            result_q.put({"ok": True, "result": {"operation": "list", "stores": stores}})
            return

        if op in {"create", "init", "new"}:
            if not _is_safe_store_dir(store_dir):
                result_q.put({"ok": False, "error": f"Refusing to create unsafe store_dir: {store_dir}"})
                return
            os.makedirs(store_dir, exist_ok=True)
            if not os.path.exists(manifest_file):
                _atomic_write_json(manifest_file, [])
            result_q.put(
                {
                    "ok": True,
                    "result": {
                        "operation": "create",
                        "store": {"name": store_name, "dir": store_dir, "manifest": manifest_file},
                    },
                }
            )
            return

        if op in {"status", "info"}:
            if not _is_safe_store_dir(store_dir):
                result_q.put({"ok": False, "error": f"Refusing unsafe store_dir: {store_dir}"})
                return
            result_q.put(
                {
                    "ok": True,
                    "result": {
                        "operation": "status",
                        "store": {
                            "name": store_name,
                            "dir": store_dir,
                            "manifest": manifest_file,
                            "exists": os.path.isdir(store_dir),
                            "has_manifest": os.path.exists(manifest_file),
                            "has_index": os.path.exists(os.path.join(store_dir, "index.faiss")),
                        },
                    },
                }
            )
            return

        if op in {"build", "index", "rebuild"}:
            if not _is_safe_store_dir(store_dir):
                result_q.put({"ok": False, "error": f"Refusing unsafe store_dir: {store_dir}"})
                return
            os.makedirs(store_dir, exist_ok=True)
            if not os.path.exists(manifest_file):
                _atomic_write_json(manifest_file, [])

            resolved_root = (

                os.path.abspath(os.path.expanduser(str(root_dir)))
                if root_dir
                else GetPath().get_path(parg=f"{__file__}", opt="p")
            )
            db = VectorStore(store_path=store_dir, manifest_file=manifest_file)
            db.build(resolved_root)
            result_q.put(
                {
                    "ok": True,
                    "result": {
                        "operation": "build",
                        "root_dir": resolved_root,
                        "store": {"name": store_name, "dir": store_dir, "manifest": manifest_file},
                    },
                }
            )
            return

        if op in {"wipe", "reset", "delete"}:
            if not force:
                result_q.put(
                    {
                        "ok": False,
                        "error": "Refusing wipe without force=true.",
                    }
                )
                return
            if not _is_safe_store_dir(store_dir):
                result_q.put({"ok": False, "error": f"Refusing unsafe store_dir: {store_dir}"})
                return

            if remove_store_dir:
                if os.path.isdir(store_dir):
                    shutil.rmtree(store_dir, ignore_errors=True)
            else:
                # Remove only known index artifacts + manifest.
                for fn in ("index.faiss", "index.pkl", "manifest.json"):
                    p = os.path.join(store_dir, fn)
                    with contextlib.suppress(Exception):
                        if os.path.exists(p):
                            os.remove(p)

            result_q.put(
                {
                    "ok": True,
                    "result": {
                        "operation": "wipe",
                        "store": {"name": store_name, "dir": store_dir, "manifest": manifest_file},
                        "removed_store_dir": bool(remove_store_dir),
                    },
                }
            )
            return

        result_q.put({"ok": False, "error": f"Unsupported operation: {operation!r}"})
    except BaseException as e:
        result_q.put({"ok": False, "error": f"{type(e).__name__}: {e}"})


def _run_vdb_admin_subprocess(
    operation: str,
    store: str | None = None,
    root_dir: str | None = None,
    force: bool = False,
    remove_store_dir: bool = False,
) -> dict | str:
    """Execute vdb admin work in a spawned subprocess with timeout."""
    import __main__

    if _VSTORE_MP_START in {"spawn", "fork", "forkserver"}:
        ctx = multiprocessing.get_context(_VSTORE_MP_START)
    else:
        main_file = getattr(__main__, "__file__", None)
        is_real_file = bool(main_file) and isinstance(main_file, str) and not main_file.startswith("<")
        if os.name == "posix" and not is_real_file:
            ctx = multiprocessing.get_context("fork")
        else:
            ctx = multiprocessing.get_context("spawn")

    result_q = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_vdb_admin_worker,
        args=(
            operation,
            store,
            root_dir,
            bool(force),
            bool(remove_store_dir),
            result_q,
        ),
        daemon=True,
    )
    proc.start()
    proc.join(_VDB_WORKER_TIMEOUT_S)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return (
            f"vdb_worker timed out after {_VDB_WORKER_TIMEOUT_S:.0f}s. "
            "Set AI_IDE_VDB_WORKER_TIMEOUT_S for longer build operations."
        )

    if proc.exitcode not in (0, None):
        return f"vdb_worker crashed in subprocess (exitcode={proc.exitcode})."

    try:
        payload = result_q.get_nowait()
    except queue_mod.Empty:
        return "vdb_worker failed: no result returned."

    if isinstance(payload, dict) and payload.get("ok") is True:
        return payload.get("result")
    if isinstance(payload, dict):
        return f"vdb_worker error: {payload.get('error', 'unknown')}"
    return "vdb_worker error: invalid result payload"


def _run_vectordb_subprocess(
    kind: str,
    query: str,
    k: int,
    *,
    store_dir: str | None = None,
    manifest_file: str | None = None,
    root_dir: str | None = None,
    autobuild: bool | None = None,
) -> list | str:
    """Execute vector DB work in a spawned subprocess with timeout."""
    timeout_s = _effective_vstore_timeout_s(autobuild)
    # CUDA + fork can be problematic if the *parent* already initialized CUDA.
    # For normal GUI runs (started from a file), prefer spawn.
    # For interactive runs (stdin/REPL), spawn can fail because __main__.__file__ is missing.
    import __main__

    if _VSTORE_MP_START in {"spawn", "fork", "forkserver"}:
        ctx = multiprocessing.get_context(_VSTORE_MP_START)
    else:
        main_file = getattr(__main__, "__file__", None)
        is_real_file = bool(main_file) and isinstance(main_file, str) and not main_file.startswith("<")
        if os.name == "posix" and not is_real_file:
            ctx = multiprocessing.get_context("fork")
        else:
            ctx = multiprocessing.get_context("spawn")

    result_q = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_vectordb_worker,
        args=(kind, query, int(k), store_dir, manifest_file, root_dir, autobuild, result_q),
        daemon=True,
    )
    proc.start()
    proc.join(timeout_s)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return (
            f"{kind} timed out after {timeout_s:.0f}s. "
            "Set AI_IDE_VSTORE_TOOL_TIMEOUT_AUTOBUILD_S (autobuild) or "
            "AI_IDE_VSTORE_TOOL_TIMEOUT_S (standard), or disable heavy queries."
        )

    # If the child crashed (e.g., segfault), exitcode will be negative.
    if proc.exitcode not in (0, None):
        return f"{kind} crashed in subprocess (exitcode={proc.exitcode})."

    try:
        payload = result_q.get_nowait()
    except queue_mod.Empty:
        return f"{kind} failed: no result returned."

    if isinstance(payload, dict) and payload.get("ok") is True:
        result = payload.get("result")
        if isinstance(result, str) and _looks_like_missing_gpu_faiss(result):
            return _run_vectordb_in_micromamba(
                kind,
                query,
                k,
                store_dir=store_dir,
                manifest_file=manifest_file,
                root_dir=root_dir,
                autobuild=autobuild,
            )
        return result
    if isinstance(payload, dict):
        err = str(payload.get("error", "unknown"))
        # If the current interpreter can't do GPU FAISS (common when the GUI
        # runs from .venv), retry transparently in the micromamba GPU env.
        if _looks_like_missing_gpu_faiss(err):
            return _run_vectordb_in_micromamba(
                kind,
                query,
                k,
                store_dir=store_dir,
                manifest_file=manifest_file,
                root_dir=root_dir,
                autobuild=autobuild,
            )
        return f"{kind} error: {err}"
    return f"{kind} error: invalid result payload"


def _now_utc_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _result_error_text(tool_name: str, result: object) -> str:
    if not isinstance(result, str):
        return ""
    txt = result.strip()
    low = txt.lower()
    if (
        f"{tool_name} error" in low
        or "timed out" in low
        or "crashed" in low
        or "failed" in low
    ):
        return txt
    return ""


def _emit_query_event(payload: dict[str, Any]) -> None:
    ok, reason = validate_query_event(payload)
    if not ok:
        return
    try:
        append_event("query", payload)
    except Exception:
        # Event logging is best-effort only.
        return


def _emit_outcome_event(payload: dict[str, Any]) -> None:
    ok, reason = validate_outcome_event(payload)
    if not ok:
        return
    try:
        append_event("outcome", payload)
    except Exception:
        # Event logging is best-effort only.
        return


def _run_retrieval_with_events(
    tool_name: str,
    query: str,
    k: int,
    *,
    store_dir: str | None = None,
    manifest_file: str | None = None,
    root_dir: str | None = None,
    autobuild: bool | None = None,
) -> list | str:
    event_id = str(uuid.uuid4())
    query_event: dict[str, Any] = {
        "event_id": event_id,
        "session_id": os.getenv("AI_IDE_SESSION_ID", "unknown"),
        "agent": os.getenv("AI_IDE_AGENT", "unknown"),
        "tool": tool_name,
        "query_text": str(query),
        "timestamp": _now_utc_iso(),
        "k": int(k),
        "autobuild": autobuild,
        "store_dir": store_dir,
        "manifest_file": manifest_file,
        "root_dir": root_dir,
        "policy_snapshot": {
            "k": int(k),
            "fetch_k": 0,
            "rerank_method": os.getenv("AI_IDE_VSTORE_RERANK_METHOD", "mmr"),
            "metadata_filters": {},
        },
    }
    _emit_query_event(query_event)

    t0 = time.perf_counter()
    result = _run_vectordb_subprocess(
        tool_name,
        query,
        k,
        store_dir=store_dir,
        manifest_file=manifest_file,
        root_dir=root_dir,
        autobuild=autobuild,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    err = _result_error_text(tool_name, result)
    outcome_event: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "query_event_id": event_id,
        "timestamp": _now_utc_iso(),
        "tool": tool_name,
        "success": not bool(err),
        "error": err or None,
        "timed_out": "timed out" in err.lower(),
        "latency_ms": latency_ms,
        "result_count": len(result) if isinstance(result, list) else 0,
        "query_rephrase_count": 0,
        "tool_retry_count": 0,
        "answer_used_signal": None,
        "explicit_feedback": None,
    }
    outcome_event["reward"] = compute_reward(query_event, outcome_event)
    _emit_outcome_event(outcome_event)
    return result

def memorydb(
    query: str,
    k: int = 5,
    store_dir: str | None = None,
    manifest_file: str | None = None,
    root_dir: str | None = None,
    autobuild: bool | None = None,
) -> list | str:
    # Run in subprocess to protect the GUI process from native crashes.
    return _run_retrieval_with_events(
        "memorydb",
        query,
        k,
        store_dir=store_dir,
        manifest_file=manifest_file,
        root_dir=root_dir,
        autobuild=autobuild,
    )

def vectordb(
    query: str,
    k: int = 5,
    store_dir: str | None = None,
    manifest_file: str | None = None,
    root_dir: str | None = None,
    autobuild: bool | None = None,
) -> list | str:
    # Run in subprocess to protect the GUI process from native crashes.
    return _run_retrieval_with_events(
        "vectordb",
        query,
        k,
        store_dir=store_dir,
        manifest_file=manifest_file,
        root_dir=root_dir,
        autobuild=autobuild,
    )


def vdb_worker(
    operation: str,
    store: str | None = None,
    root_dir: str | None = None,
    force: bool = False,
    remove_store_dir: bool = False,
) -> dict | str:
    """Create/list/build/wipe vector-store directories under AppData.

    Runs in a subprocess to protect the main process from native crashes.
    """
    return _run_vdb_admin_subprocess(
        operation=operation,
        store=store,
        root_dir=root_dir,
        force=force,
        remove_store_dir=remove_store_dir,
    )
# return data from T with type, key or with type, key where types, keys are (SQL/NoSQL) data structure types

def write_document(content: str, path: str | None = None, doc_id: str | None = None, filename: str | None = None) -> str:
        """Persist the generated cover letter to disk and return the saved file path."""
        target_dir = os.path.expanduser(path or _DEFAULT_SAVE_DIR)
        os.makedirs(target_dir, exist_ok=True)

        prefix_raw = (doc_id or "cover_letter").strip() or "cover_letter"
        # save prefix generation with safe characters
        safe_prefix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in prefix_raw)
        safe_prefix = safe_prefix[:80] or "cover_letter"
        hash_suffix = hashlib.sha1(prefix_raw.encode("utf-8", "ignore")).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_prefix}_{hash_suffix}_{timestamp}.md"
        file_path = os.path.join(target_dir, filename)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content.rstrip() + "\n")
        return f"Document saved to: {file_path}" 

def read_document(file_path: str) -> str:
        """Liest den Inhalt eines Dokuments von der Festplatte."""
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
            return content
        except FileNotFoundError:
            return f"Error: Datei '{file_path}' nicht gefunden."
        except Exception as e:
            return f"Error beim Lesen der Datei '{file_path}': {e}"
        
def update_document(data: list | dict, item:str, updatestr: str) -> str:
        """
        Aktualisiert ein Dokument im Vector Store basierend auf den übergebenen Daten."""
        normalized = item.strip().lower()
        for stored_doc in data:
            metadata = stored_doc.get('metadata', {})
            source = str(metadata.get(item, "")).strip().lower()
            if source == normalized:
                metadata[item] = updatestr
                print(f'Updated document with source: {source} to {updatestr}')
                return f"Updated {item} to {updatestr}"
        return "No matching document found"

def delete_document(file_path: str) -> str:
    """Delete a document from disk."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return f"Document '{file_path}' deleted successfully."
        return f"Document '{file_path}' not found."
    except Exception as e:
        return f"Error deleting document: {e}"
    
def list_documents(directory: str | None = None) -> str:
    """List all documents in a directory."""
    target_dir = os.path.expanduser(directory or _DEFAULT_SAVE_DIR)
    try:
        if not os.path.exists(target_dir):
            return f"Directory '{target_dir}' does not exist."
        files = os.listdir(target_dir)
        if not files:
            return f"No documents found in '{target_dir}'."
        return f"Documents in '{target_dir}':\n" + "\n".join(f"  - {f}" for f in files)
    except Exception as e:
        return f"Error listing documents: {e}"
    
def fetch_url(url: str) -> str:
    response = None
    try:
        import requests
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text[:5000]  # Limit response size
    except Exception as e:
        return f"Error fetching URL '{url}': {e}"
    finally:
        try:
            if response is not None:
                response.close()
        except Exception:
            pass
    
def fetch_data(source: str, query: str) -> str:
    """Fetch data from a specified source."""
    return f"Data fetched from '{source}' with query '{query}'"

def call_api(endpoint: str, method: str = "GET", payload: str | None = None) -> str:
    """Call an external API endpoint."""
    response = None
    try:
        import requests
        if method.upper() == "GET":
            response = requests.get(endpoint, timeout=10)
        elif method.upper() == "POST":
            response = requests.post(endpoint, json=json.loads(payload or "{}"), timeout=10)
        else:
            return f"Unsupported HTTP method: {method}"
        response.raise_for_status()
        return response.text[:5000]
    except Exception as e:
        return f"API call error: {e}"
    finally:
        try:
            if response is not None:
                response.close()
        except Exception:
            pass
    


@dataclass  
class ToolSpec:
    """Complete tool specification - single source of truth."""
    name: str
    description: str
    parameters: list[ParamSpec] = field(default_factory=list)
    implementation: Callable | None = None  # Optional: actual function reference
    
    # Callbacks bound to this tool 
    on_call: Callable[[str, dict], None] | None = None  # Called before execution
    on_result: Callable[[str, str], None] | None = None  # Called after execution
    
    def to_tool_definition(self) -> dict:
        """Generate OpenAI-compatible tool definition."""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_tool_property()
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }
    
    def execute(self, args: dict, tool_call_id: str = None) -> str:
        """Execute this tool with logging callbacks."""
        # Call on_call callback if registered
        if self.on_call:
            try:
                self.on_call(self.name, args)
            except Exception as e:
                print(f"on_call error: {e}")
        
        # Execute the tool
        result = ""
        try:
            if self.implementation:
                # Build kwargs from args
                kwargs = {}
                for p in self.parameters:
                    if p.name in args:
                        kwargs[p.name] = args[p.name]
                    elif p.default is not None:
                        kwargs[p.name] = p.default
                    elif not p.required:
                        kwargs[p.name] = None
                result = self.implementation(**kwargs)
            else:
                result = f"Tool '{self.name}' has no implementation"
        except Exception as e:
            result = f"Tool execution error: {e}"
        
        # Call on_result callback if registered
        if self.on_result:
            try:
                self.on_result(self.name, result, tool_call_id)
            except Exception as e:
                print(f"on_result error: {e}")
        
        return result
    
    def to_function_signature(self) -> str:
        """Generate Python function signature string."""
        params = []
        for p in self.parameters:
            if p.required:
                params.append(f"{p.name}: {p.to_python_type()}")
            else:
                default = f'"{p.default}"' if isinstance(p.default, str) else p.default
                params.append(f"{p.name}: {p.to_python_type()} = {default}")
        return f"def {self.name}({', '.join(params)}) -> str:"
    
    def to_function_stub(self) -> str:
        """Generate complete Python function stub."""
        sig = self.to_function_signature()
        # Prevent accidental triple-quote termination in generated source.
        safe_desc = (self.description or "").replace('"""', r'\"\"\"')
        docstring = f'    """{safe_desc}"""'
        body = f'    return f"{self.name} executed with params: {{{", ".join(p.name for p in self.parameters)}}}"'
        return f"{sig}\n{docstring}\n{body}"
    
    def compile_stub(
        self,
        *,
        attach_as_implementation: bool = True,
        globals_dict: dict | None = None,
    ) -> Callable:
        """Compile `to_function_stub()` into a real Python function.

        Uses `exec()` on the generated source code and returns the created
        callable. By default it also assigns it to `self.implementation`.

        Security note: only do this for trusted ToolSpec inputs.
        """

        import keyword
        import re

        def _is_identifier(name: str) -> bool:
            return bool(re.fullmatch(r"[A-Za-z_]\w*", name)) and not keyword.iskeyword(name)

        if not _is_identifier(self.name):
            raise ValueError(f"Tool name is not a valid Python identifier: {self.name!r}")
        for p in self.parameters:
            if not _is_identifier(p.name):
                raise ValueError(f"Param name is not a valid Python identifier: {p.name!r}")

        src = self.to_function_stub()

        ns: dict = {}
        if globals_dict is None:
            # Minimal, but still functional default. (We keep builtins so the
            # function can execute normally.)
            ns["__builtins__"] = __builtins__
        else:
            ns.update(globals_dict)
            ns.setdefault("__builtins__", __builtins__)

        exec(src, ns, ns)
        fn = ns.get(self.name)
        if not callable(fn):
            raise RuntimeError(f"Stub did not define a callable named {self.name!r}")

        if attach_as_implementation:
            self.implementation = fn
        return fn
# ============================================================================
# Helper: Quick creation from simple lists
# ============================================================================
def param(name: str, type: str = "string", desc: str = "", 
          required: bool = False, enum: list = None, default: any = None) -> ParamSpec:
    """Shorthand for creating ParamSpec."""
    return ParamSpec(name=name, type=type, description=desc, 
                     required=required, enum=enum, default=default)

def tool(name: str, desc: str, params: list[ParamSpec] = None, 
         impl: Callable = None) -> ToolSpec:
    """Shorthand for creating ToolSpec."""
    return ToolSpec(name=name, description=desc, 
                    parameters=params or [], implementation=impl)

# NOTE: Keep this module import-safe.
# Do not import `agents_registry` here; it can have import-time side effects and
# absolute imports break when running `python -m alde.*`.

UNIFIED_TOOLS: list[ToolSpec] = [
    tool("memorydb",
        "Query the memory vector database (code snippets / notes).",
        [
         param("query", "string", "Free-text query or identifier.", True),
         param("k", "integer", "Number of results.", default=3),
         param(
             "store_dir",
             "string",
             "Vector-store directory OR store id/name under AppData. Examples: '/abs/path/VSM_3_Data', './AppData/VSM_3_Data', '3', 'VSM_3_Data'.",
         ),
         param("manifest_file", "string", "Optional manifest.json path (default: <store_dir>/manifest.json)."),
         param("root_dir", "string", "Root directory to index when autobuild is enabled."),
         param("autobuild", "boolean", "Override AI_IDE_VSTORE_AUTOBUILD for this call.", default=None),
        ],
        impl=memorydb ),

    tool("vectordb",
        "Query the job-offer vector database.",
        [
         param("query", "string", "Free-text query or filename.", True),
         param("k", "integer", "Number of results.", default=3),
         param(
             "store_dir",
             "string",
             "Vector-store directory OR store id/name under AppData. Examples: '/abs/path/VSM_1_Data', './AppData/VSM_1_Data', '1', 'VSM_1_Data'.",
         ),
         param("manifest_file", "string", "Optional manifest.json path (default: <store_dir>/manifest.json)."),
         param("root_dir", "string", "Root directory to index when autobuild is enabled."),
         param("autobuild", "boolean", "Override AI_IDE_VSTORE_AUTOBUILD for this call.", default=None),
        ],
        impl=vectordb ),  

    tool(
        "vdb_worker",
        "Create/list/build/wipe vector store directories under AppData (runs in a subprocess).",
        [
            param(
                "operation",
                "string",
                "Operation to run: list|create|status|build|wipe.",
                required=True,
                enum=["list", "create", "status", "build", "wipe"],
            ),
            param(
                "store",
                "string",
                "Store id/name. Examples: '1' => VSM_1_Data, 'my_store' => VSM_my_store_Data. Empty => auto-next.",
            ),
            param(
                "root_dir",
                "string",
                "Root directory to index (only used for build). Default: project root.",
            ),
            param(
                "force",
                "boolean",
                "Required for wipe operations.",
                default=False,
            ),
            param(
                "remove_store_dir",
                "boolean",
                "If true and operation=wipe: delete the whole store directory. Otherwise remove only index+manifest files.",
                default=False,
            ),
        ],
        impl=vdb_worker,
    ),
    
    tool("write_document",
         "Persist the generated document to disk.",
         [param("content", "string", "text to write to disk.", True),
          param("path", "string", "Directory to store the file.", default=_DEFAULT_SAVE_DIR),
          param("titel", "string", "Optional file title for filename prefix.")],
         impl=write_document),
    
    tool("read_document",
         "Read the content of a document from disk.",
         [param("file_path", "string", "The absolute path to the file to read.", True)],
         impl=read_document),
    
    tool("update_document",
         "Update a document's metadata.",
         [ParamSpec(
             name="data",
             type="array",
             description="List of documents to search through.",
             required=True,
             items={"type": "object"},
         ),
          param("item", "string", "The metadata field name to match and update.", True),
          param("updatestr", "string", "The new value to set for the matched field.", True)],
         impl=update_document),
    
    tool("delete_document",
         "Delete a document from disk.",
         [param("file_path", "string", "The absolute path to the file to delete.", True)],
         impl=delete_document),
    
    tool("list_documents",
         "List all documents in a directory.",
         [param("directory", "string", "Directory path to list.", default=_DEFAULT_SAVE_DIR)],
         impl=list_documents),

    tool(
        "md_to_pdf",
        "Convert a Markdown file to a clean PDF (ReportLab).",
        [
            param("md_path", "string", "Path to the input Markdown file.", True),
            param("pdf_path", "string", "Path to the output PDF file.", True),
            param("title", "string", "Optional PDF title."),
            param("author", "string", "Optional PDF author."),
            param("pagesize", "string", "Page size.", enum=["A4", "LETTER"], default="A4"),
            param("margin_left_mm", "number", "Left margin in mm.", default=18),
            param("margin_right_mm", "number", "Right margin in mm.", default=18),
            param("margin_top_mm", "number", "Top margin in mm.", default=16),
            param("margin_bottom_mm", "number", "Bottom margin in mm.", default=16),
        ],
        impl=md_to_pdf,
    ),
    
    tool("calendar",
         "Schedule an event in the calendar.", 
         [param("event", "string", "Name or description of the event.", True),
          param("date", "string", "Date of the event (e.g., '2025-12-01').", True),
          param("time", "string", "Time of the event (e.g., '14:00').", True)],
         impl=calendar),
    
    tool("send_mail",
         "Send an email to a recipient.",
         [param("recipient", "string", "Email address of the recipient.", True),
          param("subject", "string", "Subject line of the email.", True),
          param("body", "string", "Body content of the email.", True)],
         impl=send_mail),
    
    tool("dml_tool",
         "Data Manipulation Language tool.",
         [param("operation", "string", "The operation to perform.", True),
          param("data", "string", "The data to operate on.", True)],
         impl=dml_tool),
    
    tool("dsl_tool",
         "Data Scripting Language tool for scripting operations.",
         [param("operation", "string", "The operation to perform.", True),
          param("data", "string", "The data to operate on.", True)],
         impl=dsl_tool),
    
    tool("code_tool",
         "Code Manipulation Language tool for code operations.",
         [param("operation", "string", "The code operation to perform.", True),
          param("data", "string", "The code or data to operate on.", True)],
         impl=code_tool),

    tool("iter_documents",
         "Recursively load supported documents from a root directory and returns a list of documents.",
         [param("root", "string", "Root directory to scan.", True)],
         impl=iter_documents),

    tool(
        "dispatch_job_posting_pdfs",
        "Discover PDFs in a directory, fingerprint them (SHA-256), check/update a small DB, and prepare handoff payloads for a parser agent.",
        [
            param("scan_dir", "string", "Directory to scan for PDFs.", True),
            ParamSpec(
                name="db",
                type="object",
                description="Optional DB adapter/config. Supported: { 'path': '/abs/path/to/db.json' }",
                required=False,
            ),
            param("db_path", "string", "Optional DB JSON path (file-based DB). Overrides db.path.", False),
            param("thread_id", "string", "Thread id for link.thread_id (or UNKNOWN).", False),
            param("dispatcher_message_id", "string", "Dispatcher message id for reporting (or UNKNOWN).", False),
            param("recursive", "boolean", "Recurse into subdirectories.", False, default=True),
            ParamSpec(
                name="extensions",
                type="array",
                description="File extensions to include (default: ['.pdf', '.PDF']).",
                required=False,
                items={"type": "string"},
            ),
            param("max_files", "integer", "Optional max number of PDFs to scan.", False),
            param("parser_agent_name", "string", "Target agent name for handoff messages.", False, default="_job_posting_parser"),
            param("dry_run", "boolean", "If true: do not update DB and do not create handoff messages.", False, default=False),
        ],
        impl=dispatch_job_posting_pdfs,
    ),

    tool(
        "batch_generate_cover_letters",
        "Generate cover letters for all job-offer PDFs in scan_dir using applicant profile + dispatcher DB; writes .md files to out_dir.",
        [
            param("scan_dir", "string", "Directory to scan for PDFs.", True),
            param("profile_path", "string", "Path to applicant_profile.json.", True),
            param("db_path", "string", "Path to dispatcher_doc_db.json.", True),
            param("out_dir", "string", "Output directory for generated cover letters (default: scan_dir/Cover_letters).", False),
            param("model", "string", "OpenAI model id.", False, default="gpt-4o-mini"),
            param("max_files", "integer", "Optional max number of PDFs to process.", False),
            param("max_text_chars", "integer", "Max extracted text chars per PDF to send to the model.", False, default=20000),
            param("dry_run", "boolean", "If true: do not call the model and do not write files.", False, default=False),
            param("write_pdf", "boolean", "If true: also write each cover letter as a PDF (requires reportlab).", False, default=True),
            param("rerun_processed", "boolean", "If true: also regenerate cover letters for PDFs already marked processed in the dispatcher DB.", False, default=False),
        ],
        impl=batch_generate_cover_letters,
    ),
    
    tool("fetch_url",
         "Fetch content from a URL.",
         [param("url", "string", "The URL to fetch content from.", True)],
         impl=fetch_url),
    
    tool("fetch_data",
         "Fetch data from a specified source.",
         [param("source", "string", "The data source to fetch from.", True),
          param("query", "string", "The query to execute on the source.", True)],
         impl=fetch_data),
    
    tool("call_api",
         "Call an external API endpoint.",
         [param("endpoint", "string", "The API endpoint URL.", True),
          param("method", "string", "HTTP method to use.", enum=["GET", "POST"], default="GET"),
          param("payload", "string", "JSON payload for POST requests.")],
         impl=call_api),
    
    tool("call",
         "Initiate a phone call.",
         [param("phone_number", "string", "The phone number to call.", True),
          param("message", "string", "Optional message to deliver.")],
         impl=call),
    
    tool("accept_call",
         "Accept an incoming call.",
         [param("call_id", "string", "The ID of the call to accept.", True)],
         impl=accept_call), 
    
    tool("reject_call",
         "Reject an incoming call.",
         [param("call_id", "string", "The ID of the call to reject.", True),
          param("reason", "string", "Optional reason for rejecting the call.")],
         impl=reject_call),
    
    tool("route_to_agent",
         "Route the request to a specialized agent.",
            [param("target_agent", "string", "The target agent to route to.", required=True),
          param("message_text", "string", "The message_text to pass to the agent.", required=True)],
         impl=None)  # Handled by dispatcher
]
# ---------------------------------------------------------------------------
# Tool groups (toolsets)lt
# ---------------------------------------------------------------------------
# These are convenience aliases you can use in agent configs, e.g.:
#   tools: ["@rag", "@docs_rw", "route_to_agent"]
# Expansion is handled in agents_factory.get_agent_tools().

TOOL_GROUPS: dict[str, list[str]] = {
    # Retrieval / context
    "rag": ["memorydb", "vectordb"],
    # Document CRUD
    "docs_rw": [
        "read_document",
        "write_document",
        "update_document",
        "delete_document",
        "list_documents",
        "md_to_pdf",
    ],
    # Web/data access
    "web": ["fetch_url", "fetch_data", "call_api"],
    # Comms / scheduling
    "comms": ["send_mail", "calendar", "call", "accept_call", "reject_call"],
    # Local utilities
    "code": ["code_tool", "iter_documents"],
    # Dispatcher workflow
    "dispatcher": ["dispatch_job_posting_pdfs", "batch_generate_cover_letters", "vdb_worker"],
}


def list_tool_names() -> list[str]:
    """Return all available tool names (from UNIFIED_TOOLS)."""
    out: list[str] = []
    for spec in UNIFIED_TOOLS:
        try:
            name = getattr(spec, "name", None)
            if isinstance(name, str) and name and name not in out:
                out.append(name)
        except Exception:
            continue
    return out