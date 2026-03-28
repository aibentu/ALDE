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
from datetime import datetime, timezone
import json
import glob
import typing
import subprocess
import time
import uuid
import importlib
from pathlib import Path
from typing import Callable, Any
from dataclasses import dataclass, field
import multiprocessing
from copy import deepcopy

try:
    from .agents_config import (  # type: ignore
        build_agent_handoff,
        create_agent_system_basic_config,
        create_agent_system_persisted_config_module,
        get_available_agent_labels,
        get_available_tool_names,
        get_action_request_schema_config,
        get_tool_config,
        get_tool_configs,
        get_tool_group_configs,
        normalize_action_request_name,
        normalize_tool_name,
        validate_action_request,
    )
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from ALDE.alde.agents_config import (  # type: ignore
            build_agent_handoff,
            create_agent_system_basic_config,
            create_agent_system_persisted_config_module,
            get_available_agent_labels,
            get_available_tool_names,
            get_action_request_schema_config,
            get_tool_config,
            get_tool_configs,
            get_tool_group_configs,
            normalize_action_request_name,
            normalize_tool_name,
            validate_action_request,
        )
    else:
        raise

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


def _shutdown_loky_executor() -> None:
    """Best-effort cleanup for joblib/loky reusable executors.

    Some embedding and reranking stacks lazily create loky workers. If the
    reusable executor survives until interpreter shutdown, Python 3.13 emits
    leaked semaphore warnings from resource_tracker.
    """
    get_reusable_executor = None
    for module_name in ("joblib.externals.loky", "loky"):
        try:
            module = importlib.import_module(module_name)
            get_reusable_executor = getattr(module, "get_reusable_executor", None)
            if callable(get_reusable_executor):
                break
        except Exception:
            continue

    if not callable(get_reusable_executor):
        return

    try:
        executor = get_reusable_executor()
    except Exception:
        return

    if executor is None:
        return

    try:
        executor.shutdown(wait=True, kill_workers=True)
    except TypeError:
        try:
            executor.shutdown(wait=True)
        except Exception:
            pass
    except Exception:
        pass


def _close_conn(conn: Any) -> None:
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


def _close_process_handle(proc: Any) -> None:
    try:
        if proc is not None:
            proc.close()
    except Exception:
        pass

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
            raw = f.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
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

        ts = _now_utc_filename_stamp()
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


def _default_document_db_path(obj: str) -> str:
    return os.path.join(_default_appdata_dir(), f"{obj}_db.json")


_DOCUMENT_SECTION_KEYS: dict[str, str] = {
    "job_postings": "job_posting",
    "profiles": "profile",
}


_DOCUMENT_DEFAULT_AGENTS: dict[str, str] = {
    "job_postings": "job_posting_parser",
    "profiles": "profile_parser",
}


def _normalize_document_obj_name(obj: str | None, default: str = "documents") -> str:
    normalized = str(obj or "").strip()
    return normalized or default


def _document_section_key(obj: str) -> str:
    normalized_obj = _normalize_document_obj_name(obj)
    return _DOCUMENT_SECTION_KEYS.get(normalized_obj, normalized_obj)


def _document_default_agent(obj: str) -> str:
    normalized_obj = _normalize_document_obj_name(obj)
    return _DOCUMENT_DEFAULT_AGENTS.get(normalized_obj, f"{_document_section_key(normalized_obj)}_parser")


def _extract_document_section(result_payload: dict[str, Any], resolved_obj: str) -> dict[str, Any]:
    resolved_section_key = _document_section_key(resolved_obj)
    candidate_keys = [
        resolved_section_key,
        resolved_obj,
        "job_posting",
        "profile",
    ]
    for candidate_key in candidate_keys:
        candidate_value = result_payload.get(candidate_key)
        if isinstance(candidate_value, dict):
            return candidate_value
    return {}


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    current: Any = payload
    for segment in str(key or "").split("."):
        if not segment:
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


class DocumentRepository:
    _DISPATCHER_DB_NAMES = {"dispatcher", "dispatcher_db", "dispatcher_documents"}

    def normalize_db_name(self, db_name: str | None = None, obj_name: str | None = None) -> str:
        normalized_db_name = str(db_name or "").strip().lower()
        if normalized_db_name in self._DISPATCHER_DB_NAMES:
            return "dispatcher_documents"
        if normalized_db_name:
            return normalized_db_name
        return _normalize_document_obj_name(obj_name)

    def _resolve_obj_name(self, *, db_name: str | None = None, obj_name: str | None = None) -> str:
        normalized_db_name = self.normalize_db_name(db_name=db_name, obj_name=obj_name)
        if normalized_db_name == "dispatcher_documents":
            return "documents"
        return _normalize_document_obj_name(obj_name or normalized_db_name)

    def _build_db(self, *, db_name: str | None = None, obj_name: str | None = None) -> dict[str, Any]:
        normalized_db_name = self.normalize_db_name(db_name=db_name, obj_name=obj_name)
        if normalized_db_name == "dispatcher_documents":
            return {"schema": "dispatcher_doc_db_v1", "documents": {}}
        resolved_obj_name = self._resolve_obj_name(db_name=normalized_db_name, obj_name=obj_name)
        return {"schema": f"{resolved_obj_name}_db_v1", resolved_obj_name: {}}

    def _resolve_db_path(self, db_path: str | None = None, *, db_name: str | None = None, obj_name: str | None = None) -> str:
        if db_path:
            return os.path.abspath(os.path.expanduser(str(db_path)))
        normalized_db_name = self.normalize_db_name(db_name=db_name, obj_name=obj_name)
        if normalized_db_name == "dispatcher_documents":
            return os.path.abspath(os.path.expanduser(_default_dispatcher_db_path()))
        resolved_obj_name = self._resolve_obj_name(db_name=normalized_db_name, obj_name=obj_name)
        return os.path.abspath(os.path.expanduser(_default_document_db_path(resolved_obj_name)))

    def load_db(self, db_path: str | None = None, *, db_name: str | None = None, obj_name: str | None = None) -> dict[str, Any]:
        resolved_db_path = self._resolve_db_path(db_path, db_name=db_name, obj_name=obj_name)
        empty_db = self._build_db(db_name=db_name, obj_name=obj_name)
        root_key = "documents" if self.normalize_db_name(db_name=db_name, obj_name=obj_name) == "dispatcher_documents" else self._resolve_obj_name(db_name=db_name, obj_name=obj_name)
        if not os.path.exists(resolved_db_path):
            return empty_db
        raw = _load_json_file(resolved_db_path)
        if isinstance(raw, dict) and isinstance(raw.get(root_key), dict):
            return raw
        return empty_db

    def save_db(self, db_path: str | None, db: dict[str, Any], *, db_name: str | None = None, obj_name: str | None = None) -> str:
        resolved_db_path = self._resolve_db_path(db_path, db_name=db_name, obj_name=obj_name)
        _atomic_write_json(resolved_db_path, db)
        return resolved_db_path

    def upsert_db(
        self,
        db_path: str | None,
        *,
        db_name: str | None = None,
        obj_name: str | None = None,
        record_id: str,
        record_value: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_obj_name = self._resolve_obj_name(db_name=db_name, obj_name=obj_name)
        db = self.load_db(db_path, db_name=db_name, obj_name=obj_name)
        if not isinstance(db.get(resolved_obj_name), dict):
            db[resolved_obj_name] = {}
        db[resolved_obj_name][record_id] = deepcopy(record_value)
        self.save_db(db_path, db, db_name=db_name, obj_name=obj_name)
        return db

    def persist_document(
        self,
        *,
        correlation_id: str,
        result_payload: dict[str, Any],
        obj_name: str,
        db_path: str | None = None,
        handoff_metadata: dict[str, Any] | None = None,
        handoff_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_obj_name = _normalize_document_obj_name(obj_name)
        resolved_section_key = _document_section_key(resolved_obj_name)
        resolved_db_path = self._resolve_db_path(db_path, db_name=resolved_obj_name, obj_name=resolved_obj_name)
        db = self.load_db(resolved_db_path, db_name=resolved_obj_name, obj_name=resolved_obj_name)
        if not isinstance(db.get(resolved_obj_name), dict):
            db[resolved_obj_name] = {}

        document_records = db[resolved_obj_name]
        record = document_records.get(correlation_id) if isinstance(document_records.get(correlation_id), dict) else {}
        record = dict(record)
        ts = _now_utc_iso()

        metadata = dict(handoff_metadata or {})
        incoming_payload = dict(handoff_payload or {})
        output_payload = incoming_payload.get("output") if isinstance(incoming_payload.get("output"), dict) else {}
        parse_section = result_payload.get("parse") if isinstance(result_payload.get("parse"), dict) else {}
        document_section = _extract_document_section(result_payload, resolved_obj_name)
        db_updates = result_payload.get("db_updates") if isinstance(result_payload.get("db_updates"), dict) else {}
        fallback_source_payload = output_payload if output_payload else result_payload

        record["correlation_id"] = correlation_id
        record["updated_at"] = ts
        record.setdefault("created_at", ts)
        record["source_agent"] = str(
            incoming_payload.get("agent_label")
            or metadata.get("source_agent")
            or result_payload.get("agent")
            or _document_default_agent(resolved_obj_name)
        )
        record["link"] = deepcopy(result_payload.get("link") if isinstance(result_payload.get("link"), dict) else output_payload.get("link") if isinstance(output_payload.get("link"), dict) else {})
        record["file"] = deepcopy(result_payload.get("file") if isinstance(result_payload.get("file"), dict) else output_payload.get("file") if isinstance(output_payload.get("file"), dict) else {})
        record["parse"] = deepcopy(parse_section)
        record[resolved_section_key] = deepcopy(document_section)
        record["db_updates"] = deepcopy(db_updates)
        record["handoff_metadata"] = deepcopy(metadata)
        record["source_payload"] = deepcopy(fallback_source_payload)

        document_records[correlation_id] = record
        db[resolved_obj_name] = document_records
        self.save_db(resolved_db_path, db, db_name=resolved_obj_name, obj_name=resolved_obj_name)
        return {
            "ok": True,
            "db_path": resolved_db_path,
            "obj_name": resolved_obj_name,
            "correlation_id": correlation_id,
            "stored": True,
        }

    def get_document(
        self,
        correlation_id: str,
        *,
        obj_name: str,
        db_path: str | None = None,
    ) -> dict[str, Any] | None:
        resolved_obj_name = _normalize_document_obj_name(obj_name)
        resolved_section_key = _document_section_key(resolved_obj_name)
        db = self.load_db(db_path, db_name=resolved_obj_name, obj_name=resolved_obj_name)
        document_records = db.get(resolved_obj_name) if isinstance(db, dict) else None
        if not isinstance(document_records, dict):
            return None
        record = document_records.get(correlation_id)
        if not isinstance(record, dict):
            return None
        return {
            "agent": str(record.get("source_agent") or record.get("agent") or _document_default_agent(resolved_obj_name)),
            "correlation_id": str(record.get("correlation_id") or correlation_id),
            "link": deepcopy(record.get("link") or {}),
            "file": deepcopy(record.get("file") or {}),
            "parse": deepcopy(record.get("parse") or {}),
            resolved_section_key: deepcopy(record.get(resolved_section_key) or record.get(resolved_obj_name) or {}),
            "db_updates": deepcopy(record.get("db_updates") or {}),
        }

    def update_dispatcher_status(
        self,
        *,
        correlation_id: str,
        processing_state: str,
        db_path: str | None = None,
        processed: bool | None = None,
        failed_reason: str | None = None,
        extra_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_db_path = self._resolve_db_path(db_path, db_name="dispatcher_documents")
        db = self.load_db(resolved_db_path, db_name="dispatcher_documents")
        if not isinstance(db.get("documents"), dict):
            db["documents"] = {}

        docs = db["documents"]
        record = docs.get(correlation_id) if isinstance(docs.get(correlation_id), dict) else {}
        record = dict(record)

        normalized_state = str(processing_state or "").strip().lower() or "failed"
        effective_processed = bool(processed) if processed is not None else normalized_state == "processed"
        ts = _now_utc_iso()

        record.setdefault("id", correlation_id)
        record["content_sha256"] = correlation_id
        record["processing_state"] = normalized_state
        record["processed"] = effective_processed
        record["last_seen_at"] = ts

        if effective_processed:
            record["processed_at"] = ts
            record["failed_reason"] = None
            record["last_error"] = None
            record["last_error_at"] = None
        else:
            reason = str(failed_reason or "").strip() or None
            record["failed_reason"] = reason
            record["last_error"] = reason
            record["last_error_at"] = ts if reason else None

        if isinstance(extra_updates, dict):
            for key, value in extra_updates.items():
                if value is None and key in {"failed_reason", "last_error", "last_error_at"}:
                    record[str(key)] = None
                elif value is not None:
                    record[str(key)] = value

        docs[correlation_id] = record
        self.save_db(resolved_db_path, db, db_name="dispatcher_documents")
        return {
            "ok": True,
            "db_path": resolved_db_path,
            "correlation_id": correlation_id,
            "processing_state": normalized_state,
            "processed": effective_processed,
        }

    def upsert_db_record(
        self,
        *,
        record_id: str,
        result_payload: dict[str, Any],
        obj_name: str = "documents",
        obj_db_path: str | None = None,
        dispatcher_db_path: str | None = None,
        processing_state: str | None = None,
        processed: bool | None = None,
        failed_reason: str | None = None,
        source_agent: str | None = None,
        source_payload: dict[str, Any] | None = None,
        dispatcher_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_obj_name = _normalize_document_obj_name(obj_name)
        resolved_dispatcher_db_path = self._resolve_db_path(dispatcher_db_path, db_name="dispatcher_documents")
        resolved_obj_db_path = self._resolve_db_path(obj_db_path, db_name=resolved_obj_name, obj_name=resolved_obj_name)

        original_obj_db = self.load_db(resolved_obj_db_path, db_name=resolved_obj_name, obj_name=resolved_obj_name)
        next_obj_db = deepcopy(original_obj_db if isinstance(original_obj_db, dict) else {"schema": f"{resolved_obj_name}_db_v1", resolved_obj_name: {}})
        if not isinstance(next_obj_db.get(resolved_obj_name), dict):
            next_obj_db[resolved_obj_name] = {}

        resolved_section_key = _document_section_key(resolved_obj_name)
        ts = _now_utc_iso()
        parse_section = result_payload.get("parse") if isinstance(result_payload.get("parse"), dict) else {}
        record_section = _extract_document_section(result_payload, resolved_obj_name)
        db_updates = result_payload.get("db_updates") if isinstance(result_payload.get("db_updates"), dict) else {}
        metadata = {"source_agent": str(source_agent or result_payload.get("agent") or _document_default_agent(resolved_obj_name))}
        source_payload_dict = deepcopy(source_payload) if isinstance(source_payload, dict) else {}

        existing_record = next_obj_db[resolved_obj_name].get(record_id) if isinstance(next_obj_db[resolved_obj_name].get(record_id), dict) else {}
        next_record = dict(existing_record)
        next_record["correlation_id"] = record_id
        next_record["updated_at"] = ts
        next_record.setdefault("created_at", ts)
        next_record["source_agent"] = str(source_agent or result_payload.get("agent") or _document_default_agent(resolved_obj_name))
        next_record["link"] = deepcopy(result_payload.get("link") if isinstance(result_payload.get("link"), dict) else {})
        next_record["file"] = deepcopy(result_payload.get("file") if isinstance(result_payload.get("file"), dict) else {})
        next_record["parse"] = deepcopy(parse_section)
        next_record[resolved_section_key] = deepcopy(record_section)
        next_record["db_updates"] = deepcopy(db_updates)
        next_record["handoff_metadata"] = deepcopy(metadata)
        next_record["source_payload"] = deepcopy(source_payload_dict)
        next_obj_db[resolved_obj_name][record_id] = next_record

        normalized_state = str(
            processing_state
            or db_updates.get("processing_state")
            or ("processed" if (record_section or parse_section.get("is_job_posting")) else "failed")
        ).strip().lower() or "failed"
        effective_processed = bool(processed) if processed is not None else bool(db_updates.get("processed")) if isinstance(db_updates.get("processed"), bool) else normalized_state == "processed"
        effective_failed_reason = str(failed_reason or db_updates.get("failed_reason") or "").strip() or None

        try:
            self.save_db(resolved_obj_db_path, next_obj_db, db_name=resolved_obj_name, obj_name=resolved_obj_name)
            dispatcher_result = self.update_dispatcher_status(
                correlation_id=record_id,
                processing_state=normalized_state,
                db_path=resolved_dispatcher_db_path,
                processed=effective_processed,
                failed_reason=effective_failed_reason,
                extra_updates=dispatcher_updates,
            )
        except Exception as exc:
            try:
                self.save_db(
                    resolved_obj_db_path,
                    original_obj_db if isinstance(original_obj_db, dict) else {"schema": f"{resolved_obj_name}_db_v1", resolved_obj_name: {}},
                    db_name=resolved_obj_name,
                    obj_name=resolved_obj_name,
                )
            except Exception:
                pass
            return {
                "ok": False,
                "error": "atomic_upsert_failed",
                "details": f"{type(exc).__name__}: {exc}",
                "correlation_id": record_id,
                "obj_name": resolved_obj_name,
            }

        result: dict[str, Any] = {
            "ok": True,
            "stored": True,
            "dispatcher_updated": True,
            "correlation_id": record_id,
            "obj_name": resolved_obj_name,
            "obj_db_path": resolved_obj_db_path,
            "dispatcher_db_path": str(dispatcher_result.get("db_path") or resolved_dispatcher_db_path),
            "processing_state": normalized_state,
            "processed": effective_processed,
        }
        result[f"{resolved_obj_name}_db_path"] = resolved_obj_db_path
        return result

    def upsert_dispatcher_job_record(
        self,
        *,
        correlation_id: str,
        job_posting_result: dict[str, Any],
        dispatcher_db_path: str | None = None,
        job_postings_db_path: str | None = None,
        obj_name: str = "job_postings",
        processing_state: str | None = None,
        processed: bool | None = None,
        failed_reason: str | None = None,
        source_agent: str | None = None,
        source_payload: dict[str, Any] | None = None,
        dispatcher_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Backward-compatible wrapper for existing call sites.
        return self.upsert_db_record(
            record_id=correlation_id,
            result_payload=job_posting_result,
            obj_name=_normalize_document_obj_name(obj_name, ""),
            obj_db_path=job_postings_db_path,
            dispatcher_db_path=dispatcher_db_path,
            processing_state=processing_state,
            processed=processed,
            failed_reason=failed_reason,
            source_agent=source_agent,
            source_payload=source_payload,
            dispatcher_updates=dispatcher_updates,
        )


DOCUMENT_REPOSITORY = DocumentRepository()


@dataclass(frozen=True)
class RequestObjectSpec:
    obj_name: str
    result_sources: tuple[str, ...] = ()
    store_sources: tuple[str, ...] = ()
    file_sources: tuple[str, ...] = ()
    inline_sources: tuple[str, ...] = ("text", "json", "dict", "object", "structured", "inline")
    correlation_candidates: tuple[str, ...] = ("correlation_id", "id")
    path_candidates: tuple[str, ...] = ("path", "file_path", "value", "source_path")
    db_path_aliases: tuple[str, ...] = ("db_path",)
    parse_mode: str = "generic"


class RequestObjectResolutionService:
    _OBJECT_SPECS: dict[str, RequestObjectSpec] = {
        "profiles": RequestObjectSpec(
            obj_name="profiles",
            result_sources=("profile_result", "resolved_profile", "parsed_profile"),
            store_sources=("profile_id", "profiles_db", "stored_profile", "persisted_profile"),
            file_sources=("file", "path", "json_file", "structured_file", "document_file"),
            correlation_candidates=("correlation_id", "profile_id", "id"),
            db_path_aliases=("db_path", "profiles_db_path"),
            parse_mode="profile",
        ),
        "job_postings": RequestObjectSpec(
            obj_name="job_postings",
            result_sources=("job_posting_result", "resolved_job_posting", "parsed_job_posting"),
            store_sources=("correlation_id", "job_postings_db", "stored_job_posting", "persisted_job_posting"),
            file_sources=("file", "path", "text_file", "document_file", "structured_file", "json_file"),
            correlation_candidates=("correlation_id", "content_sha256", "job_id", "external_id", "title"),
            db_path_aliases=("db_path", "job_postings_db_path"),
            parse_mode="job_posting",
        ),
    }

    def load_object_spec(self, obj_name: str | None) -> RequestObjectSpec:
        resolved_obj_name = _normalize_document_obj_name(obj_name)
        spec = self._OBJECT_SPECS.get(resolved_obj_name)
        if spec is not None:
            return spec
        return RequestObjectSpec(obj_name=resolved_obj_name)

    def resolve_correlation_id(
        self,
        *,
        value: Any,
        candidates: tuple[str, ...],
        fallback_values: list[Any] | None = None,
    ) -> str:
        for candidate_value in [value, *(fallback_values or [])]:
            if isinstance(candidate_value, str) and candidate_value.strip():
                return candidate_value.strip()
            if not isinstance(candidate_value, dict):
                continue
            for candidate_key in candidates:
                resolved_value = _payload_value(candidate_value, candidate_key)
                if resolved_value is None:
                    continue
                text_value = str(resolved_value).strip()
                if text_value:
                    return text_value
        return ""

    def resolve_source_path(self, *, request_payload: dict[str, Any], value: Any, spec: RequestObjectSpec) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for candidate_key in spec.path_candidates:
                resolved_value = _payload_value(value, candidate_key)
                if resolved_value is None:
                    continue
                candidate_path = str(resolved_value).strip()
                if candidate_path:
                    return candidate_path
        for candidate_key in spec.path_candidates:
            resolved_value = _payload_value(request_payload, candidate_key)
            if resolved_value is None:
                continue
            candidate_path = str(resolved_value).strip()
            if candidate_path:
                return candidate_path
        return ""

    def resolve_db_path(
        self,
        *,
        request_payload: dict[str, Any],
        fallback_payload: dict[str, Any] | None,
        db_path_field: str | None,
        spec: RequestObjectSpec,
    ) -> str | None:
        candidate_keys: list[str] = []
        if db_path_field:
            candidate_keys.append(str(db_path_field))
        candidate_keys.extend(spec.db_path_aliases)
        for candidate_key in candidate_keys:
            request_value = request_payload.get(candidate_key)
            if isinstance(request_value, str) and request_value.strip():
                return request_value.strip()
            fallback_value = (fallback_payload or {}).get(candidate_key)
            if isinstance(fallback_value, str) and fallback_value.strip():
                return fallback_value.strip()
        return None

    def normalize_object_value(
        self,
        *,
        raw_value: dict[str, Any],
        spec: RequestObjectSpec,
        source_path: str | None = None,
    ) -> dict[str, Any]:
        normalized_value = deepcopy(raw_value)
        if source_path:
            normalized_value.setdefault("source_path", source_path)
        if spec.parse_mode == "job_posting":
            title = str(
                normalized_value.get("job_title")
                or normalized_value.get("title")
                or normalized_value.get("position")
                or ""
            ).strip()
            if title:
                normalized_value["job_title"] = title
            if not str(normalized_value.get("company_name") or "").strip() and isinstance(normalized_value.get("company"), dict):
                company_name = str(
                    normalized_value["company"].get("name")
                    or normalized_value["company"].get("about")
                    or ""
                ).strip()
                if company_name:
                    normalized_value["company_name"] = company_name
        return normalized_value

    def build_parse_payload(self, *, object_value: dict[str, Any], spec: RequestObjectSpec) -> dict[str, Any]:
        if spec.parse_mode == "profile":
            language = _payload_value(object_value, "preferences.language") or "de"
            return {"language": language, "errors": [], "warnings": []}
        if spec.parse_mode == "job_posting":
            return {"is_job_posting": True, "errors": [], "warnings": []}
        return {"errors": [], "warnings": []}

    def build_inline_result(self, raw_value: Any, *, obj_name: str, source_path: str | None = None) -> dict[str, Any] | None:
        spec = self.load_object_spec(obj_name)
        resolved_obj_name = _normalize_document_obj_name(obj_name, spec.obj_name)
        result_key = _document_section_key(resolved_obj_name)
        if isinstance(raw_value, dict):
            object_value = self.normalize_object_value(raw_value=raw_value, spec=spec, source_path=source_path)
            correlation_id = self.resolve_correlation_id(value=object_value, candidates=spec.correlation_candidates) or None
            return {
                "agent": _document_default_agent(resolved_obj_name),
                "correlation_id": correlation_id,
                "parse": self.build_parse_payload(object_value=object_value, spec=spec),
                result_key: object_value,
            }
        if isinstance(raw_value, str):
            raw_text = raw_value.strip()
            if not raw_text:
                return None
            object_value: dict[str, Any] = {"raw_text": raw_text}
            if source_path:
                object_value["source_path"] = source_path
            return {
                "agent": _document_default_agent(resolved_obj_name),
                "correlation_id": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "parse": self.build_parse_payload(object_value=object_value, spec=spec),
                result_key: object_value,
            }
        return None

    def load_result_from_store(self, *, correlation_id: str, obj_name: str, db_path: str | None) -> dict[str, Any] | None:
        if not correlation_id:
            return None
        return DOCUMENT_REPOSITORY.get_document(correlation_id, db_path=db_path, obj_name=obj_name)

    def load_result_from_file(self, *, source_path: str, obj_name: str) -> dict[str, Any] | None:
        resolved_path = os.path.abspath(os.path.expanduser(source_path))
        if not os.path.isfile(resolved_path):
            return None
        result = None
        try:
            result = self.build_inline_result(_load_json_file(resolved_path), obj_name=obj_name, source_path=resolved_path)
        except Exception:
            result = None
        if not isinstance(result, dict):
            try:
                with open(resolved_path, "r", encoding="utf-8") as file_handle:
                    result = self.build_inline_result(file_handle.read(), obj_name=obj_name, source_path=resolved_path)
            except Exception:
                return None
        if not isinstance(result, dict):
            return None
        result["correlation_id"] = str(result.get("correlation_id") or _sha256_file(resolved_path))
        result["file"] = {"path": resolved_path, "content_sha256": _sha256_file(resolved_path)}
        return result

    def build_result_from_request(
        self,
        request_payload: Any,
        *,
        obj_name: str,
        fallback_payload: dict[str, Any] | None = None,
        store_sources: set[str] | None = None,
        file_sources: set[str] | None = None,
        inline_sources: set[str] | None = None,
        db_path_field: str | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(request_payload, dict):
            return None
        spec = self.load_object_spec(obj_name)
        resolved_obj_name = _normalize_document_obj_name(obj_name, spec.obj_name)
        source = str(request_payload.get("source") or "").strip().lower()
        value = request_payload.get("value")
        result_sources = {str(item).strip().lower() for item in spec.result_sources if str(item).strip()}
        effective_store_sources = store_sources or {str(item).strip().lower() for item in spec.store_sources if str(item).strip()}
        effective_file_sources = file_sources or {str(item).strip().lower() for item in spec.file_sources if str(item).strip()}
        effective_inline_sources = inline_sources or {str(item).strip().lower() for item in spec.inline_sources if str(item).strip()}

        if source in result_sources and isinstance(value, dict):
            return deepcopy(value)
        if source in effective_store_sources:
            correlation_id = self.resolve_correlation_id(
                value=value,
                candidates=spec.correlation_candidates,
                fallback_values=[request_payload],
            )
            if not correlation_id:
                return None
            db_path = self.resolve_db_path(
                request_payload=request_payload,
                fallback_payload=fallback_payload,
                db_path_field=db_path_field,
                spec=spec,
            )
            return self.load_result_from_store(correlation_id=correlation_id, obj_name=resolved_obj_name, db_path=db_path)
        if source in effective_file_sources:
            candidate_path = self.resolve_source_path(request_payload=request_payload, value=value, spec=spec)
            if not candidate_path:
                return None
            return self.load_result_from_file(source_path=candidate_path, obj_name=resolved_obj_name)
        if source in effective_inline_sources or (not source and value is not None):
            return self.build_inline_result(value, obj_name=resolved_obj_name)
        return None


REQUEST_OBJECT_RESOLUTION_SERVICE = RequestObjectResolutionService()


class DocumentObjectService:
    def load_result_payload(self, result_payload: dict[str, Any] | str | None) -> dict[str, Any] | None:
        parsed_payload = result_payload
        if isinstance(parsed_payload, str):
            try:
                parsed_payload = json.loads(parsed_payload)
            except Exception:
                return None
        return parsed_payload if isinstance(parsed_payload, dict) else None

    def resolve_result_correlation_id(
        self,
        *,
        result_payload: dict[str, Any],
        obj_name: str,
        correlation_id: str | None = None,
        source_payload: dict[str, Any] | None = None,
    ) -> str:
        spec = REQUEST_OBJECT_RESOLUTION_SERVICE.load_object_spec(obj_name)
        result_key = _document_section_key(obj_name)
        result_object = result_payload.get(result_key) if isinstance(result_payload.get(result_key), dict) else {}
        return REQUEST_OBJECT_RESOLUTION_SERVICE.resolve_correlation_id(
            value=correlation_id or "",
            candidates=spec.correlation_candidates,
            fallback_values=[
                result_payload,
                result_payload.get("file") if isinstance(result_payload.get("file"), dict) else {},
                result_payload.get("db_updates") if isinstance(result_payload.get("db_updates"), dict) else {},
                result_object,
                source_payload or {},
            ],
        )

    def store_result(
        self,
        *,
        result_payload: dict[str, Any] | str,
        correlation_id: str | None = None,
        db_path: str | None = None,
        source_agent: str | None = None,
        source_payload: dict[str, Any] | None = None,
        obj_name: str,
    ) -> str:
        parsed_payload = self.load_result_payload(result_payload)
        if not isinstance(parsed_payload, dict):
            return json.dumps({"ok": False, "error": "document_result_must_be_object"}, ensure_ascii=False)
        resolved_obj_name = _normalize_document_obj_name(obj_name)
        effective_correlation_id = self.resolve_result_correlation_id(
            result_payload=parsed_payload,
            obj_name=resolved_obj_name,
            correlation_id=correlation_id,
            source_payload=source_payload,
        )
        if not effective_correlation_id:
            return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)
        metadata = {"source_agent": str(source_agent or parsed_payload.get("agent") or _document_default_agent(resolved_obj_name))}
        result = DOCUMENT_REPOSITORY.persist_document(
            correlation_id=effective_correlation_id,
            result_payload=parsed_payload,
            db_path=db_path or (str(parsed_payload.get(f"{resolved_obj_name}_db_path") or "").strip() or None),
            handoff_metadata=metadata,
            handoff_payload=source_payload if isinstance(source_payload, dict) else None,
            obj_name=resolved_obj_name,
        )
        return json.dumps(result, ensure_ascii=False)

    def ingest_result(
        self,
        *,
        object_payload: dict[str, Any] | None = None,
        request_payload: dict[str, Any] | None = None,
        result_payload: dict[str, Any] | str | None = None,
        correlation_id: str | None = None,
        db_path: str | None = None,
        source_agent: str | None = None,
        source_payload: dict[str, Any] | None = None,
        parse: dict[str, Any] | None = None,
        obj_name: str,
    ) -> str:
        parsed_payload = self.load_result_payload(result_payload)
        resolved_obj_name = _normalize_document_obj_name(obj_name)
        if parsed_payload is None:
            if isinstance(request_payload, dict):
                parsed_payload = REQUEST_OBJECT_RESOLUTION_SERVICE.build_result_from_request(request_payload, obj_name=resolved_obj_name)
            elif isinstance(object_payload, dict):
                parsed_payload = REQUEST_OBJECT_RESOLUTION_SERVICE.build_inline_result(object_payload, obj_name=resolved_obj_name)
        if not isinstance(parsed_payload, dict):
            return json.dumps({"ok": False, "error": "document_result_must_be_object"}, ensure_ascii=False)

        normalized_payload = deepcopy(parsed_payload)
        effective_correlation_id = self.resolve_result_correlation_id(
            result_payload=normalized_payload,
            obj_name=resolved_obj_name,
            correlation_id=correlation_id,
            source_payload=source_payload,
        )
        if not effective_correlation_id:
            return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

        normalized_payload["correlation_id"] = effective_correlation_id
        if source_agent:
            normalized_payload["agent"] = str(source_agent)
        if isinstance(source_payload, dict):
            normalized_payload["source_payload"] = deepcopy(source_payload)
        if not isinstance(normalized_payload.get("parse"), dict):
            spec = REQUEST_OBJECT_RESOLUTION_SERVICE.load_object_spec(resolved_obj_name)
            normalized_payload["parse"] = deepcopy(parse) if isinstance(parse, dict) else REQUEST_OBJECT_RESOLUTION_SERVICE.build_parse_payload(
                object_value={"raw_text": ""},
                spec=spec,
            )

        return self.store_result(
            result_payload=normalized_payload,
            correlation_id=effective_correlation_id,
            db_path=db_path,
            source_agent=source_agent,
            source_payload=source_payload,
            obj_name=resolved_obj_name,
        )


DOCUMENT_OBJECT_SERVICE = DocumentObjectService()


def store_object_result_tool(
    object_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    return DOCUMENT_OBJECT_SERVICE.store_result(
        result_payload=object_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=source_payload,
        obj_name=_normalize_document_obj_name(obj_name),
    )


def store_document_result_tool(
    document_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    return store_object_result_tool(
        object_result=document_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=source_payload,
        obj_name=obj_name,
    )


def ingest_object_tool(
    object_payload: dict[str, Any] | None = None,
    request_payload: dict[str, Any] | None = None,
    object_result: dict[str, Any] | str | None = None,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    parse: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    return DOCUMENT_OBJECT_SERVICE.ingest_result(
        object_payload=object_payload,
        request_payload=request_payload,
        result_payload=object_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=source_payload,
        parse=parse,
        obj_name=_normalize_document_obj_name(obj_name),
    )


def ingest_document_tool(
    object_payload: dict[str, Any] | None = None,
    request_payload: dict[str, Any] | None = None,
    document_result: dict[str, Any] | str | None = None,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    parse: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    return ingest_object_tool(
        object_payload=object_payload,
        request_payload=request_payload,
        object_result=document_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=source_payload,
        parse=parse,
        obj_name=obj_name,
    )


def upsert_object_record_tool(
    object_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    dispatcher_db_path: str | None = None,
    obj_db_path: str | None = None,
    obj_name: str | None = None,
    processing_state: str | None = None,
    processed: bool | None = None,
    failed_reason: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    dispatcher_updates: dict[str, Any] | None = None,
) -> str:
    parsed_result = object_result
    if isinstance(parsed_result, str):
        try:
            parsed_result = json.loads(parsed_result)
        except Exception:
            return json.dumps({"ok": False, "error": "invalid_object_result_json"}, ensure_ascii=False)
    if not isinstance(parsed_result, dict):
        return json.dumps({"ok": False, "error": "object_result_must_be_object"}, ensure_ascii=False)

    resolved_obj_name = _normalize_document_obj_name(obj_name)
    effective_correlation_id = DOCUMENT_OBJECT_SERVICE.resolve_result_correlation_id(
        result_payload=parsed_result,
        obj_name=resolved_obj_name,
        correlation_id=correlation_id,
        source_payload=source_payload,
    )
    if not effective_correlation_id:
        return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

    result = DOCUMENT_REPOSITORY.upsert_db_record(
        record_id=effective_correlation_id,
        result_payload=parsed_result,
        obj_name=resolved_obj_name,
        obj_db_path=obj_db_path,
        dispatcher_db_path=dispatcher_db_path,
        processing_state=processing_state,
        processed=processed,
        failed_reason=failed_reason,
        source_agent=source_agent,
        source_payload=source_payload,
        dispatcher_updates=dispatcher_updates,
    )
    return json.dumps(result, ensure_ascii=False)





def store_job_posting_result_tool(
    job_posting_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    return store_object_result_tool(
        object_result=job_posting_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=source_payload,
        obj_name=_normalize_document_obj_name(obj_name, "job_postings"),
    )


def upsert_dispatcher_job_record_tool(
    job_posting_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    dispatcher_db_path: str | None = None,
    job_postings_db_path: str | None = None,
    obj_name: str | None = None,
    processing_state: str | None = None,
    processed: bool | None = None,
    failed_reason: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    dispatcher_updates: dict[str, Any] | None = None,
) -> str:
    return upsert_object_record_tool(
        object_result=job_posting_result,
        correlation_id=correlation_id,
        dispatcher_db_path=dispatcher_db_path,
        obj_db_path=job_postings_db_path,
        obj_name=_normalize_document_obj_name(obj_name, "job_postings"),
        processing_state=processing_state,
        processed=processed,
        failed_reason=failed_reason,
        source_agent=source_agent,
        source_payload=source_payload,
        dispatcher_updates=dispatcher_updates,
    )


def store_profile_result_tool(
    profile_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    obj_name: str | None = None,
) -> str:
    return store_object_result_tool(
        object_result=profile_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        obj_name=_normalize_document_obj_name(obj_name, "profiles"),
    )


def ingest_profile_tool(
    profile: dict[str, Any] | None = None,
    applicant_profile: dict[str, Any] | None = None,
    profile_result: dict[str, Any] | str | None = None,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    request_payload = applicant_profile if isinstance(applicant_profile, dict) else {"source": "text", "value": profile} if isinstance(profile, dict) else None
    return ingest_object_tool(
        object_payload=profile,
        request_payload=request_payload,
        object_result=profile_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=source_payload,
        obj_name=_normalize_document_obj_name(obj_name, "profiles"),
    )


def ingest_job_posting_tool(
    job_posting: dict[str, Any] | None = None,
    job_posting_result: dict[str, Any] | str | None = None,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    parse: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    request_payload = {"source": "text", "value": job_posting} if isinstance(job_posting, dict) else None
    return ingest_object_tool(
        object_payload=job_posting,
        request_payload=request_payload,
        object_result=job_posting_result,
        correlation_id=correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=source_payload,
        parse=parse,
        obj_name=_normalize_document_obj_name(obj_name, "job_postings"),
    )


class ActionRequestService:
    def resolve_object_name(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
        config_key: str,
        default_obj_name: str,
        value_payload: dict[str, Any] | None = None,
    ) -> str:
        return str(
            (value_payload or {}).get("obj_name")
            or request_payload.get("obj_name")
            or resolution_config.get(config_key)
            or default_obj_name
        ).strip() or default_obj_name

    def resolve_object_db_path_field(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
        config_key: str,
        resolved_obj_name: str,
        value_payload: dict[str, Any] | None = None,
    ) -> str:
        return str(
            (
                f"{resolved_obj_name}_db_path"
                if ((value_payload or {}).get("obj_name") or request_payload.get("obj_name"))
                else resolution_config.get(config_key)
            )
            or f"{resolved_obj_name}_db_path"
        ).strip() or f"{resolved_obj_name}_db_path"

    def load_resolution_objects(self, *, resolution_config: dict[str, Any]) -> list[dict[str, Any]]:
        resolved_objects: list[dict[str, Any]] = []
        raw_objects = resolution_config.get("objects") or []
        if not isinstance(raw_objects, list):
            return resolved_objects
        for raw_object in raw_objects:
            if not isinstance(raw_object, dict):
                continue
            binding_name = str(
                raw_object.get("binding_name")
                or raw_object.get("request_field")
                or raw_object.get("result_field")
                or ""
            ).strip()
            request_field = str(raw_object.get("request_field") or "").strip()
            result_field = str(raw_object.get("result_field") or "").strip()
            default_obj_name = str(raw_object.get("default_obj_name") or "").strip()
            if not binding_name or not request_field or not result_field or not default_obj_name:
                continue
            resolved_objects.append(deepcopy(raw_object))
        return resolved_objects

    def load_resolution_object(
        self,
        *,
        resolution_config: dict[str, Any],
        binding_name: str | None,
    ) -> dict[str, Any] | None:
        normalized_binding_name = str(binding_name or "").strip()
        if not normalized_binding_name:
            return None
        for resolution_object in self.load_resolution_objects(resolution_config=resolution_config):
            candidate_name = str(
                resolution_object.get("binding_name")
                or resolution_object.get("request_field")
                or resolution_object.get("result_field")
                or ""
            ).strip()
            if candidate_name == normalized_binding_name:
                return resolution_object
        return None

    def resolve_binding_object_name(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
        resolution_object: dict[str, Any],
    ) -> str:
        request_field = str(resolution_object.get("request_field") or "").strip()
        value_payload = request_payload.get(request_field) if isinstance(request_payload.get(request_field), dict) else None
        default_obj_name = str(resolution_object.get("default_obj_name") or "documents").strip() or "documents"
        obj_name_config_key = str(resolution_object.get("obj_name_config_key") or "").strip()
        return self.resolve_object_name(
            request_payload=request_payload,
            resolution_config=resolution_config,
            config_key=obj_name_config_key,
            default_obj_name=default_obj_name,
            value_payload=value_payload,
        )

    def resolve_binding_db_path_field(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
        resolution_object: dict[str, Any],
        resolved_obj_name: str,
    ) -> str:
        request_field = str(resolution_object.get("request_field") or "").strip()
        value_payload = request_payload.get(request_field) if isinstance(request_payload.get(request_field), dict) else None
        db_path_field_key = str(resolution_object.get("db_path_field_key") or "").strip()
        return self.resolve_object_db_path_field(
            request_payload=request_payload,
            resolution_config=resolution_config,
            config_key=db_path_field_key,
            resolved_obj_name=resolved_obj_name,
            value_payload=value_payload,
        )

    def normalize_resolution_request(
        self,
        *,
        request_value: dict[str, Any] | None,
        default_source: str = "text",
    ) -> dict[str, Any] | None:
        if not isinstance(request_value, dict):
            return None
        source_name = str(request_value.get("source") or "").strip()
        if source_name or "value" in request_value:
            return request_value
        return {
            "source": str(default_source or "text").strip() or "text",
            "value": deepcopy(request_value),
        }

    def build_resolved_object_result(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
        resolution_object: dict[str, Any],
    ) -> dict[str, Any] | None:
        request_field = str(resolution_object.get("request_field") or "").strip()
        raw_request_value = request_payload.get(request_field)
        normalized_request_value = self.normalize_resolution_request(
            request_value=raw_request_value if isinstance(raw_request_value, dict) else None,
            default_source=str(resolution_object.get("default_source") or "text").strip() or "text",
        )
        if not isinstance(normalized_request_value, dict):
            return None

        resolved_obj_name = self.resolve_binding_object_name(
            request_payload=request_payload,
            resolution_config=resolution_config,
            resolution_object=resolution_object,
        )
        resolved_db_path_field = self.resolve_binding_db_path_field(
            request_payload=request_payload,
            resolution_config=resolution_config,
            resolution_object=resolution_object,
            resolved_obj_name=resolved_obj_name,
        )

        store_sources = {
            str(value).strip().lower()
            for value in (resolution_object.get("store_sources") or [])
            if str(value).strip()
        } or None
        file_sources = {
            str(value).strip().lower()
            for value in (resolution_object.get("file_sources") or [])
            if str(value).strip()
        } or None
        inline_sources = {
            str(value).strip().lower()
            for value in (resolution_object.get("inline_sources") or [])
            if str(value).strip()
        } or None

        return REQUEST_OBJECT_RESOLUTION_SERVICE.build_result_from_request(
            normalized_request_value,
            obj_name=resolved_obj_name,
            fallback_payload=request_payload,
            store_sources=store_sources,
            file_sources=file_sources,
            inline_sources=inline_sources,
            db_path_field=resolved_db_path_field,
        )

    def apply_resolution_defaults(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
    ) -> dict[str, Any]:
        enriched_payload = deepcopy(request_payload)
        for default_field in (resolution_config.get("default_fields") or []):
            if not isinstance(default_field, dict):
                continue
            field_name = str(default_field.get("field") or "").strip()
            config_key = str(default_field.get("config_key") or field_name).strip()
            if not field_name or not config_key or field_name in enriched_payload:
                continue

            raw_value = resolution_config.get(config_key)
            normalize_mode = str(default_field.get("normalize") or "").strip().lower()
            if normalize_mode == "tool_name":
                normalized_value = normalize_tool_name(str(raw_value or ""))
            elif isinstance(raw_value, str):
                normalized_value = raw_value.strip()
            else:
                normalized_value = deepcopy(raw_value)

            if normalized_value in (None, "", [], {}):
                continue
            enriched_payload[field_name] = normalized_value
        return enriched_payload

    def resolve_request_payload(self, payload: Any) -> Any:
        raw_payload = payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return raw_payload

        if not isinstance(payload, dict):
            return raw_payload

        action_name = normalize_action_request_name(str(payload.get("action") or ""))
        schema_config = get_action_request_schema_config(action_name, payload)
        resolution_config = dict(schema_config.get("request_resolution") or {})
        if not resolution_config:
            return raw_payload

        payload = deepcopy(payload)
        payload["action"] = action_name

        enriched_payload = self.apply_resolution_defaults(
            request_payload=payload,
            resolution_config=resolution_config,
        )

        for resolution_object in self.load_resolution_objects(resolution_config=resolution_config):
            result_field = str(resolution_object.get("result_field") or "").strip()
            request_field = str(resolution_object.get("request_field") or "").strip()
            if not result_field:
                continue

            if not isinstance(enriched_payload.get(result_field), dict):
                resolved_result = self.build_resolved_object_result(
                    request_payload=enriched_payload,
                    resolution_config=resolution_config,
                    resolution_object=resolution_object,
                )
                if isinstance(resolved_result, dict):
                    enriched_payload[result_field] = resolved_result

            if not isinstance(enriched_payload.get(result_field), dict):
                continue

            if bool(resolution_object.get("drop_request_field_when_resolved")):
                enriched_payload.pop(request_field, None)

            if bool(resolution_object.get("drop_db_path_field_when_resolved")):
                resolved_obj_name = self.resolve_binding_object_name(
                    request_payload=enriched_payload,
                    resolution_config=resolution_config,
                    resolution_object=resolution_object,
                )
                resolved_db_path_field = self.resolve_binding_db_path_field(
                    request_payload=enriched_payload,
                    resolution_config=resolution_config,
                    resolution_object=resolution_object,
                    resolved_obj_name=resolved_obj_name,
                )
                enriched_payload.pop(resolved_db_path_field, None)

        return enriched_payload

    def resolve_string_value(
        self,
        *,
        request_payload: dict[str, Any],
        field_names: list[str] | tuple[str, ...],
    ) -> str | None:
        for field_name in field_names:
            normalized_field_name = str(field_name or "").strip()
            if not normalized_field_name:
                continue
            value = request_payload.get(normalized_field_name)
            if value is None or isinstance(value, (dict, list)):
                continue
            text_value = str(value).strip()
            if text_value:
                return text_value
        return None

    def resolve_bool_value(
        self,
        *,
        request_payload: dict[str, Any],
        field_names: list[str] | tuple[str, ...],
    ) -> bool | None:
        for field_name in field_names:
            normalized_field_name = str(field_name or "").strip()
            if not normalized_field_name:
                continue
            value = request_payload.get(normalized_field_name)
            if isinstance(value, bool):
                return value
        return None

    def resolve_dict_value(
        self,
        *,
        request_payload: dict[str, Any],
        field_names: list[str] | tuple[str, ...],
    ) -> dict[str, Any] | None:
        for field_name in field_names:
            normalized_field_name = str(field_name or "").strip()
            if not normalized_field_name:
                continue
            value = request_payload.get(normalized_field_name)
            if isinstance(value, dict):
                return value
        return None

    def build_request_source_payload(
        self,
        *,
        request_payload: dict[str, Any],
        request_payload_field: str,
        object_payload_field: str,
        default_source: str = "text",
    ) -> dict[str, Any] | None:
        request_value = request_payload.get(request_payload_field) if request_payload_field else None
        normalized_request_value = self.normalize_resolution_request(
            request_value=request_value if isinstance(request_value, dict) else None,
            default_source=default_source,
        )
        if isinstance(normalized_request_value, dict):
            return normalized_request_value

        object_value = request_payload.get(object_payload_field) if object_payload_field else None
        if isinstance(object_value, dict):
            return {
                "source": str(default_source or "text").strip() or "text",
                "value": deepcopy(object_value),
            }
        return None

    def execute_ingest_object_action(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
        execution_config: dict[str, Any],
    ) -> str | None:
        binding_name = str(execution_config.get("binding_name") or "").strip()
        resolution_object = self.load_resolution_object(
            resolution_config=resolution_config,
            binding_name=binding_name,
        )
        if not isinstance(resolution_object, dict):
            return None

        resolved_obj_name = self.resolve_binding_object_name(
            request_payload=request_payload,
            resolution_config=resolution_config,
            resolution_object=resolution_object,
        )
        resolved_db_path_field = self.resolve_binding_db_path_field(
            request_payload=request_payload,
            resolution_config=resolution_config,
            resolution_object=resolution_object,
            resolved_obj_name=resolved_obj_name,
        )

        object_payload_field = str(execution_config.get("object_payload_field") or "").strip()
        request_payload_field = str(execution_config.get("request_payload_field") or resolution_object.get("request_field") or "").strip()
        result_payload_field = str(execution_config.get("result_payload_field") or resolution_object.get("result_field") or "").strip()
        default_source = str(execution_config.get("default_request_source") or resolution_object.get("default_source") or "text").strip() or "text"

        db_path_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("db_path_fields") or [resolved_db_path_field, "db_path"])
            if str(field_name).strip()
        ]
        correlation_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("correlation_id_fields") or ["correlation_id"])
            if str(field_name).strip()
        ]
        source_agent_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("source_agent_fields") or ["source_agent"])
            if str(field_name).strip()
        ]
        source_payload_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("source_payload_fields") or ["source_payload"])
            if str(field_name).strip()
        ]
        parse_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("parse_fields") or ["parse"])
            if str(field_name).strip()
        ]

        request_source_payload = self.build_request_source_payload(
            request_payload=request_payload,
            request_payload_field=request_payload_field,
            object_payload_field=object_payload_field,
            default_source=default_source,
        )

        return DOCUMENT_OBJECT_SERVICE.ingest_result(
            object_payload=request_payload.get(object_payload_field) if isinstance(request_payload.get(object_payload_field), dict) else None,
            request_payload=request_source_payload,
            result_payload=request_payload.get(result_payload_field),
            correlation_id=self.resolve_string_value(request_payload=request_payload, field_names=correlation_fields),
            db_path=self.resolve_string_value(request_payload=request_payload, field_names=db_path_fields),
            source_agent=self.resolve_string_value(request_payload=request_payload, field_names=source_agent_fields),
            source_payload=self.resolve_dict_value(request_payload=request_payload, field_names=source_payload_fields),
            parse=self.resolve_dict_value(request_payload=request_payload, field_names=parse_fields),
            obj_name=resolved_obj_name,
        )

    def execute_upsert_object_record_action(
        self,
        *,
        request_payload: dict[str, Any],
        resolution_config: dict[str, Any],
        execution_config: dict[str, Any],
    ) -> str | None:
        binding_name = str(execution_config.get("binding_name") or "").strip()
        resolution_object = self.load_resolution_object(
            resolution_config=resolution_config,
            binding_name=binding_name,
        )
        if not isinstance(resolution_object, dict):
            return None

        resolved_obj_name = self.resolve_binding_object_name(
            request_payload=request_payload,
            resolution_config=resolution_config,
            resolution_object=resolution_object,
        )
        resolved_db_path_field = self.resolve_binding_db_path_field(
            request_payload=request_payload,
            resolution_config=resolution_config,
            resolution_object=resolution_object,
            resolved_obj_name=resolved_obj_name,
        )

        result_payload_field = str(execution_config.get("result_payload_field") or resolution_object.get("result_field") or "").strip()
        object_payload_field = str(execution_config.get("object_payload_field") or "").strip()
        dispatcher_db_path_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("dispatcher_db_path_fields") or ["dispatcher_db_path"])
            if str(field_name).strip()
        ]
        obj_db_path_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("obj_db_path_fields") or [resolved_db_path_field, "db_path"])
            if str(field_name).strip()
        ]
        correlation_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("correlation_id_fields") or ["correlation_id"])
            if str(field_name).strip()
        ]
        source_agent_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("source_agent_fields") or ["source_agent"])
            if str(field_name).strip()
        ]
        source_payload_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("source_payload_fields") or ["source_payload"])
            if str(field_name).strip()
        ]
        processing_state_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("processing_state_fields") or ["processing_state"])
            if str(field_name).strip()
        ]
        processed_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("processed_fields") or ["processed"])
            if str(field_name).strip()
        ]
        failed_reason_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("failed_reason_fields") or ["failed_reason"])
            if str(field_name).strip()
        ]
        dispatcher_updates_fields = [
            str(field_name).strip()
            for field_name in (execution_config.get("dispatcher_updates_fields") or ["dispatcher_updates"])
            if str(field_name).strip()
        ]

        result_payload = request_payload.get(result_payload_field)
        if result_payload is None and object_payload_field:
            result_payload = request_payload.get(object_payload_field)
        if isinstance(result_payload, str):
            try:
                result_payload = json.loads(result_payload)
            except Exception:
                return json.dumps({"ok": False, "error": "invalid_object_result_json"}, ensure_ascii=False)
        if not isinstance(result_payload, dict):
            return json.dumps({"ok": False, "error": "object_result_must_be_object"}, ensure_ascii=False)

        source_payload = self.resolve_dict_value(request_payload=request_payload, field_names=source_payload_fields)
        correlation_id = DOCUMENT_OBJECT_SERVICE.resolve_result_correlation_id(
            result_payload=result_payload,
            obj_name=resolved_obj_name,
            correlation_id=self.resolve_string_value(request_payload=request_payload, field_names=correlation_fields),
            source_payload=source_payload,
        )
        if not correlation_id:
            return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

        result = DOCUMENT_REPOSITORY.upsert_db_record(
            record_id=correlation_id,
            result_payload=result_payload,
            obj_name=resolved_obj_name,
            obj_db_path=self.resolve_string_value(request_payload=request_payload, field_names=obj_db_path_fields),
            dispatcher_db_path=self.resolve_string_value(request_payload=request_payload, field_names=dispatcher_db_path_fields),
            processing_state=self.resolve_string_value(request_payload=request_payload, field_names=processing_state_fields),
            processed=self.resolve_bool_value(request_payload=request_payload, field_names=processed_fields),
            failed_reason=self.resolve_string_value(request_payload=request_payload, field_names=failed_reason_fields),
            source_agent=self.resolve_string_value(request_payload=request_payload, field_names=source_agent_fields),
            source_payload=source_payload,
            dispatcher_updates=self.resolve_dict_value(request_payload=request_payload, field_names=dispatcher_updates_fields),
        )
        return json.dumps(result, ensure_ascii=False)

    def load_action_executor(self, handler_name: str | None) -> Callable[..., str | None] | None:
        normalized_handler_name = str(handler_name or "").strip().lower()
        executors: dict[str, Callable[..., str | None]] = {
            "ingest_object": self.execute_ingest_object_action,
            "upsert_object_record": self.execute_upsert_object_record_action,
        }
        return executors.get(normalized_handler_name)

    def execute_request(self, payload: Any) -> str | None:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None

        if not isinstance(payload, dict):
            return None

        action_name = normalize_action_request_name(str(payload.get("action") or ""))
        if not action_name:
            return None

        payload = deepcopy(payload)
        payload["action"] = action_name

        schema_config = get_action_request_schema_config(action_name, payload)
        resolution_config = dict(schema_config.get("request_resolution") or {}) if isinstance(schema_config, dict) else {}
        if schema_config:
            validation = validate_action_request(action_name, payload)
            if not validation.get("valid"):
                return json.dumps(
                    {
                        "ok": False,
                        "error": "invalid_action_request",
                        "action": action_name,
                        "schema_name": validation.get("schema_name") or "",
                        "errors": list(validation.get("errors") or []),
                        "warnings": list(validation.get("warnings") or []),
                    },
                    ensure_ascii=False,
                )

        resolved_payload = self.resolve_request_payload(payload)
        if isinstance(resolved_payload, str):
            try:
                resolved_payload = json.loads(resolved_payload)
            except Exception:
                resolved_payload = payload
        if not isinstance(resolved_payload, dict):
            resolved_payload = payload

        execution_config = dict(schema_config.get("action_execution") or {}) if isinstance(schema_config, dict) else {}
        action_executor = self.load_action_executor(execution_config.get("handler_name"))
        if action_executor is None:
            return None
        return action_executor(
            request_payload=resolved_payload,
            resolution_config=resolution_config,
            execution_config=execution_config,
        )

    def execute_request_tool(
        self,
        action_request: dict[str, Any] | str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        request_payload = action_request
        if isinstance(request_payload, str):
            try:
                request_payload = json.loads(request_payload)
            except Exception:
                return json.dumps({"ok": False, "error": "invalid_action_request_json"}, ensure_ascii=False)

        if request_payload is None:
            request_payload = dict(payload or {})
            if action:
                request_payload.setdefault("action", str(action))

        if not isinstance(request_payload, dict):
            return json.dumps({"ok": False, "error": "action_request_must_be_object"}, ensure_ascii=False)

        result = self.execute_request(request_payload)
        if result is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": "unknown_or_unsupported_action",
                    "action": str(request_payload.get("action") or "").strip().lower(),
                },
                ensure_ascii=False,
            )
        return result


ACTION_REQUEST_SERVICE = ActionRequestService()


def resolve_configured_request_payload(payload: Any) -> Any:
    return ACTION_REQUEST_SERVICE.resolve_request_payload(payload)


def execute_deterministic_action_request(payload: Any) -> str | None:
    return ACTION_REQUEST_SERVICE.execute_request(payload)


def execute_action_request_tool(
    action_request: dict[str, Any] | str | None = None,
    action: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    return ACTION_REQUEST_SERVICE.execute_request_tool(action_request=action_request, action=action, payload=payload)


def build_agent_system_configs_tool(
    system_name: str | None = None,
    action_request: dict[str, Any] | str | None = None,
    persist_path: str | None = None,
    write_file: bool | None = None,
    builder_request: dict[str, Any] | str | None = None,
) -> str:
    request_payload = action_request if action_request is not None else builder_request
    if isinstance(request_payload, str):
        try:
            request_payload = json.loads(request_payload)
        except Exception:
            return json.dumps({"ok": False, "error": "invalid_action_request_json"}, ensure_ascii=False)

    if request_payload is None:
        request_payload = {}

    if not isinstance(request_payload, dict):
        return json.dumps({"ok": False, "error": "action_request_must_be_object"}, ensure_ascii=False)

    resolved_system_name = str(system_name or request_payload.get("system_name") or "").strip()
    if not resolved_system_name:
        return json.dumps({"ok": False, "error": "system_name_is_required"}, ensure_ascii=False)

    resolved_write_file = bool(request_payload.get("write_file")) if write_file is None else bool(write_file)
    persisted_module = create_agent_system_persisted_config_module(resolved_system_name, request_payload)
    resolved_persist_path = str(persist_path or request_payload.get("persist_path") or persisted_module.get("relative_path") or "").strip()
    if resolved_write_file and not resolved_persist_path:
        return json.dumps({"ok": False, "error": "persist_path_is_required_when_write_file_is_true"}, ensure_ascii=False)

    if resolved_persist_path:
        resolved_path = Path(resolved_persist_path)
        if not resolved_path.is_absolute():
            resolved_path = Path(__file__).resolve().parent / resolved_path
        persisted_module["written_path"] = str(resolved_path)
        persisted_module["relative_path"] = str(resolved_path.relative_to(Path(__file__).resolve().parent)) if resolved_path.is_relative_to(Path(__file__).resolve().parent) else str(resolved_path)
        if resolved_write_file:
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(str(persisted_module.get("content") or ""), encoding="utf-8")
            persisted_module["written"] = True
        else:
            persisted_module["written"] = False

    config_bundle = create_agent_system_basic_config(resolved_system_name, request_payload)
    config_bundle["persisted_module"] = persisted_module
    return json.dumps(config_bundle, ensure_ascii=False)


def update_dispatcher_document_status(
    *,
    correlation_id: str,
    processing_state: str,
    db_path: str | None = None,
    processed: bool | None = None,
    failed_reason: str | None = None,
    extra_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return DOCUMENT_REPOSITORY.update_dispatcher_status(
        correlation_id=correlation_id,
        processing_state=processing_state,
        db_path=db_path,
        processed=processed,
        failed_reason=failed_reason,
        extra_updates=extra_updates,
    )


class DocumentDispatchService:
    def classify_record(self, record: dict[str, Any] | None) -> str:
        if not record:
            return "new"
        if record.get("processed") is True or record.get("processing_state") == "processed":
            return "known_processed"
        processing_state = str(record.get("processing_state") or "").lower().strip()
        if processing_state in {"queued", "processing"}:
            return "known_processing"
        return "known_unprocessed"

    def resolve_scan_dir(self, scan_dir: str, *, resolved_db_path: str, warnings: list[dict[str, Any]]) -> str:
        resolved_scan_dir = os.path.abspath(os.path.expanduser(str(scan_dir or "")))
        if os.path.isdir(resolved_scan_dir):
            return resolved_scan_dir

        fallback_candidates: list[tuple[str, str]] = []
        try:
            db_parent = os.path.dirname(resolved_db_path)
            if db_parent:
                fallback_candidates.append((db_parent, "fallback_to_db_parent"))
        except Exception:
            pass
        try:
            base = GetPath()._parent(parg=f"{__file__}")
            vsm4 = os.path.join(base, "AppData", "VSM_4_Data")
            fallback_candidates.append((vsm4, "fallback_to_default_vsm4"))
        except Exception:
            pass

        for candidate, reason in fallback_candidates:
            resolved_candidate = os.path.abspath(os.path.expanduser(str(candidate)))
            if os.path.isdir(resolved_candidate):
                warnings.append(
                    {
                        "warning": "scan_dir_not_found_using_fallback",
                        "scan_dir_original": str(scan_dir or ""),
                        "scan_dir_used": resolved_candidate,
                        "reason": reason,
                    }
                )
                return resolved_candidate

        return resolved_scan_dir

    def collect_document_paths(self, scan_dir: str, *, recursive: bool, extensions: set[str]) -> list[str]:
        document_paths: list[str] = []
        if recursive:
            for root, dirs, files in os.walk(scan_dir):
                dirs[:] = [directory for directory in dirs if not str(directory).startswith("Cover_letters")]
                for file_name in files:
                    if file_name == "Muster_Anschreiben.pdf":
                        continue
                    if any(file_name.endswith(extension) for extension in extensions):
                        document_paths.append(os.path.join(root, file_name))
        else:
            for file_name in os.listdir(scan_dir):
                if file_name == "Muster_Anschreiben.pdf":
                    continue
                file_path = os.path.join(scan_dir, file_name)
                if os.path.isfile(file_path) and any(file_name.endswith(extension) for extension in extensions):
                    document_paths.append(file_path)
        document_paths.sort()
        return document_paths

    def save_dispatcher_db(self, dispatcher_db: dict[str, Any] | None, *, resolved_db_path: str) -> tuple[bool, str | None]:
        if dispatcher_db is None:
            return False, "db_not_loaded"
        try:
            DOCUMENT_REPOSITORY.save_db(resolved_db_path, dispatcher_db, db_name="dispatcher_documents")
            return True, None
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def load_dispatcher_db(self, *, resolved_db_path: str) -> tuple[dict[str, Any] | None, str | None]:
        try:
            return DOCUMENT_REPOSITORY.load_db(resolved_db_path, db_name="dispatcher_documents"), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def classify_documents(
        self,
        *,
        pdf_paths: list[str],
        docs: dict[str, Any],
        errors: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        classified: dict[str, list[dict[str, Any]]] = {
            "new": [],
            "known_unprocessed": [],
            "known_processing": [],
            "known_processed": [],
            "duplicates": [],
            "error_items": [],
        }
        seen_hashes: set[str] = set()

        for path in pdf_paths:
            abs_path = os.path.abspath(path)
            try:
                stat_result = os.stat(abs_path)
                file_size_bytes = _safe_int(getattr(stat_result, "st_size", 0), 0)
                mtime_epoch = _safe_int(getattr(stat_result, "st_mtime", 0), 0)
            except Exception as exc:
                err = {"path": abs_path, "error": "stat_failed", "detail": f"{type(exc).__name__}: {exc}"}
                errors.append(err)
                classified["error_items"].append(err)
                continue

            try:
                content_sha256 = _sha256_file(abs_path)
            except Exception as exc:
                err = {"path": abs_path, "error": "unreadable", "detail": f"{type(exc).__name__}: {exc}"}
                errors.append(err)
                classified["error_items"].append(err)
                continue

            if content_sha256 in seen_hashes:
                classified["duplicates"].append({"path": abs_path, "content_sha256": content_sha256})
                continue
            seen_hashes.add(content_sha256)

            record = docs.get(content_sha256) if isinstance(docs, dict) else None
            bucket = self.classify_record(record if isinstance(record, dict) else None)
            item = {
                "path": abs_path,
                "name": os.path.basename(abs_path),
                "content_sha256": content_sha256,
                "file_size_bytes": file_size_bytes,
                "mtime_epoch": mtime_epoch,
                "db": {
                    "existing_record_id": (record or {}).get("id") if isinstance(record, dict) else None,
                    "processed": (record or {}).get("processed") if isinstance(record, dict) else None,
                    "processing_state": (record or {}).get("processing_state") if isinstance(record, dict) else None,
                },
            }
            classified[bucket].append(item)

        return classified

    def queue_document(
        self,
        *,
        dispatcher_db: dict[str, Any] | None,
        resolved_db_path: str,
        item: dict[str, Any],
        correlation_id: str,
        timestamp: str,
    ) -> tuple[bool, str | None]:
        if not isinstance(dispatcher_db, dict):
            return False, "db_not_loaded"
        if "documents" not in dispatcher_db or not isinstance(dispatcher_db.get("documents"), dict):
            dispatcher_db["documents"] = {}

        docs = dispatcher_db["documents"]
        current = docs.get(correlation_id) if isinstance(docs, dict) else None
        current_state = (current or {}).get("processing_state") if isinstance(current, dict) else None
        if (current_state or "").lower().strip() in {"queued", "processing"}:
            return True, None

        next_record = dict(current) if isinstance(current, dict) else {}
        next_record.setdefault("id", correlation_id)
        next_record["content_sha256"] = correlation_id
        next_record["source_path"] = item["path"]
        next_record["file_size_bytes"] = item["file_size_bytes"]
        next_record["mtime_epoch"] = item["mtime_epoch"]
        next_record["last_seen_at"] = timestamp
        next_record["processed"] = False
        next_record["processing_state"] = "queued"
        docs[correlation_id] = next_record
        return self.save_dispatcher_db(dispatcher_db, resolved_db_path=resolved_db_path)

    def resolve_object_db_path(
        self,
        *,
        dispatch_policy: dict[str, Any],
        resolved_obj_db_path_field: str,
        resolved_obj_name: str,
    ) -> str | None:
        metadata_defaults = dict(dispatch_policy.get("metadata_defaults") or {})
        obj_db_default = metadata_defaults.get(resolved_obj_db_path_field)
        if not isinstance(obj_db_default, dict):
            obj_db_default = {}

        resolver_name = str(obj_db_default.get("resolver") or "").strip()
        resolver_obj_name = str(obj_db_default.get("obj_name") or resolved_obj_name).strip() or resolved_obj_name
        if resolver_name in {
            "default_document_db_path",
            f"default_{resolved_obj_name}_db_path",
            f"default_{resolver_obj_name}_db_path",
        }:
            return _default_document_db_path(resolver_obj_name)
        if isinstance(obj_db_default.get("value"), str) and str(obj_db_default.get("value") or "").strip():
            return os.path.abspath(os.path.expanduser(str(obj_db_default.get("value"))))
        return None

    def build_dispatch_payload(
        self,
        *,
        dispatch_policy: dict[str, Any],
        thread_id: str,
        resolved_obj_name: str,
        item: dict[str, Any],
        record: dict[str, Any] | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        return {
            "type": str(dispatch_policy.get("document_type") or "file"),
            "correlation_id": item["content_sha256"],
            "obj_name": resolved_obj_name,
            "link": {"thread_id": thread_id, "message_id": "PENDING"},
            "file": {
                "path": item["path"],
                "name": item["name"],
                "content_sha256": item["content_sha256"],
                "file_size_bytes": item["file_size_bytes"],
                "mtime_epoch": item["mtime_epoch"],
            },
            "db": {
                "existing_record_id": (record or {}).get("id") if isinstance(record, dict) else None,
                "processing_state": "queued" if not dry_run else ((record or {}).get("processing_state") if isinstance(record, dict) else "new"),
            },
            "requested_actions": list(dispatch_policy.get("requested_actions") or ["parse", "extract_text", "store_object_result", "mark_processed_on_success"]),
        }

    def build_handoff_message(
        self,
        *,
        dispatch_policy: dict[str, Any],
        target_agent: str,
        payload: dict[str, Any],
        correlation_id: str,
        dispatcher_message_id: str,
        resolved_db_path: str,
        resolved_obj_name: str,
        resolved_obj_db_path_field: str,
        obj_db_path: str | None,
    ) -> dict[str, Any]:
        handoff_metadata = {
            "correlation_id": correlation_id,
            "dispatcher_message_id": dispatcher_message_id,
            "dispatcher_db_path": resolved_db_path,
            "obj_name": resolved_obj_name,
            "obj_db_path": obj_db_path,
        }
        if resolved_obj_db_path_field and resolved_obj_db_path_field != "obj_db_path":
            handoff_metadata[resolved_obj_db_path_field] = obj_db_path
        legacy_obj_db_path_field = f"{resolved_obj_name}_db_path"
        if legacy_obj_db_path_field not in handoff_metadata:
            handoff_metadata[legacy_obj_db_path_field] = obj_db_path
        return build_agent_handoff(
            source_agent_label=str(dispatch_policy.get("source_agent") or "_data_dispatcher"),
            target_agent=target_agent,
            protocol=str(dispatch_policy.get("handoff_protocol") or "agent_handoff_v1"),
            agent_response={
                "agent_label": str(dispatch_policy.get("source_agent") or "_data_dispatcher"),
                "handoff_to": target_agent,
                "output": payload,
            },
            handoff_metadata=handoff_metadata,
        )

    def forward_documents(
        self,
        *,
        items: list[dict[str, Any]],
        dispatcher_db: dict[str, Any] | None,
        resolved_db_path: str,
        timestamp: str,
        dispatch_policy: dict[str, Any],
        thread_id: str,
        dispatcher_message_id: str,
        agent_name: str,
        resolved_obj_name: str,
        resolved_obj_db_path_field: str,
        dry_run: bool,
        errors: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        forwarded: list[dict[str, Any]] = []
        handoff_messages: list[dict[str, Any]] = []

        for item in items:
            correlation_id = item["content_sha256"]
            docs = (dispatcher_db or {"documents": {}}).get("documents", {}) if isinstance(dispatcher_db, dict) else {}
            record = docs.get(correlation_id) if isinstance(docs, dict) else None

            if dispatcher_db is None and not dry_run:
                errors.append({"path": item["path"], "error": "db_unreachable"})
                continue

            if not dry_run:
                db_write_ok, db_write_err = self.queue_document(
                    dispatcher_db=dispatcher_db,
                    resolved_db_path=resolved_db_path,
                    item=item,
                    correlation_id=correlation_id,
                    timestamp=timestamp,
                )
                if not db_write_ok:
                    errors.append(
                        {
                            "path": item["path"],
                            "error": "db_write_failed",
                            "detail": db_write_err,
                            "content_sha256": correlation_id,
                        }
                    )
                    continue

            payload = self.build_dispatch_payload(
                dispatch_policy=dispatch_policy,
                thread_id=thread_id,
                resolved_obj_name=resolved_obj_name,
                item=item,
                record=record if isinstance(record, dict) else None,
                dry_run=dry_run,
            )
            if dry_run:
                continue

            obj_db_path = self.resolve_object_db_path(
                dispatch_policy=dispatch_policy,
                resolved_obj_db_path_field=resolved_obj_db_path_field,
                resolved_obj_name=resolved_obj_name,
            )
            forwarded.append({"path": item["path"], "content_sha256": correlation_id, "link": {"thread_id": thread_id, "message_id": "PENDING"}})
            handoff_messages.append(
                self.build_handoff_message(
                    dispatch_policy=dispatch_policy,
                    target_agent=agent_name,
                    payload=payload,
                    correlation_id=correlation_id,
                    dispatcher_message_id=dispatcher_message_id,
                    resolved_db_path=resolved_db_path,
                    resolved_obj_name=resolved_obj_name,
                    resolved_obj_db_path_field=resolved_obj_db_path_field,
                    obj_db_path=obj_db_path,
                )
            )

        return forwarded, handoff_messages

    def build_report(
        self,
        *,
        scan_dir: str,
        timestamp: str,
        resolved_db_path: str,
        db_load_error: str | None,
        pdf_paths: list[str],
        classified: dict[str, list[dict[str, Any]]],
        forwarded: list[dict[str, Any]],
        handoff_messages: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "agent": "data_dispatcher",
            "scan_dir": scan_dir,
            "timestamp": timestamp,
            "db": {"path": resolved_db_path, "reachable": db_load_error is None, "error": db_load_error},
            "summary": {
                "pdf_found": len(pdf_paths),
                "new": len(classified["new"]),
                "known_unprocessed": len(classified["known_unprocessed"]),
                "known_processing": len(classified["known_processing"]),
                "known_processed": len(classified["known_processed"]),
                "errors": len(errors),
            },
            "classified": {
                "new": classified["new"],
                "known_unprocessed": classified["known_unprocessed"],
                "known_processing": classified["known_processing"],
                "known_processed": classified["known_processed"],
                "duplicates": classified["duplicates"],
                "error_items": classified["error_items"],
            },
            "forwarded": forwarded,
            "handoff_messages": handoff_messages,
            "warnings": warnings,
            "errors": errors,
        }

    def dispatch_documents(
        self,
        scan_dir: str,
        db: dict | None = None,
        db_path: str | None = None,
        obj: str | None = None,
        obj_name: str | None = None,
        thread_id: str | None = None,
        dispatcher_message_id: str | None = None,
        recursive: bool = True,
        extensions: list | None = None,
        max_files: int | None = None,
        agent_name: str = "_job_posting_parser",
        dry_run: bool = False,
    ) -> dict:
        ts = _now_utc_iso()
        dispatch_policy = dict((get_tool_config("dispatch_documents") or {}).get("dispatch_policy") or {})
        scan_dir_original = str(scan_dir or "")
        thread_id = thread_id or "UNKNOWN"
        dispatcher_message_id = dispatcher_message_id or "UNKNOWN"
        agent_name = str(agent_name or dispatch_policy.get("default_target_agent") or "_job_posting_parser").strip() or "_job_posting_parser"
        resolved_obj_name = str(obj_name or obj or dispatch_policy.get("obj_name") or "job_postings").strip() or "job_postings"
        resolved_obj_db_path_field = str(dispatch_policy.get("obj_db_path_field") or f"{resolved_obj_name}_db_path").strip() or f"{resolved_obj_name}_db_path"

        if extensions is None:
            extensions = [".pdf", ".PDF"]
        ext_set = {str(extension) for extension in extensions}

        resolved_db_path = ((db or {}).get("path") if isinstance(db, dict) else None) or db_path or _default_dispatcher_db_path()
        resolved_db_path = os.path.abspath(os.path.expanduser(str(resolved_db_path)))

        warnings: list[dict[str, Any]] = []
        scan_dir = self.resolve_scan_dir(scan_dir_original, resolved_db_path=resolved_db_path, warnings=warnings)

        dispatcher_db, db_load_error = self.load_dispatcher_db(resolved_db_path=resolved_db_path)

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

        errors: list[dict[str, Any]] = []
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

        pdf_paths = self.collect_document_paths(scan_dir, recursive=recursive, extensions=ext_set)
        if max_files is not None:
            pdf_paths = pdf_paths[: max(0, int(max_files))]

        docs = (dispatcher_db or {"documents": {}}).get("documents", {}) if isinstance(dispatcher_db, dict) else {}
        classified = self.classify_documents(pdf_paths=pdf_paths, docs=docs if isinstance(docs, dict) else {}, errors=errors)
        forwarded, handoff_messages = self.forward_documents(
            items=classified["new"] + classified["known_unprocessed"],
            dispatcher_db=dispatcher_db,
            resolved_db_path=resolved_db_path,
            timestamp=ts,
            dispatch_policy=dispatch_policy,
            thread_id=thread_id,
            dispatcher_message_id=dispatcher_message_id,
            agent_name=agent_name,
            resolved_obj_name=resolved_obj_name,
            resolved_obj_db_path_field=resolved_obj_db_path_field,
            dry_run=dry_run,
            errors=errors,
        )
        return self.build_report(
            scan_dir=scan_dir,
            timestamp=ts,
            resolved_db_path=resolved_db_path,
            db_load_error=db_load_error,
            pdf_paths=pdf_paths,
            classified=classified,
            forwarded=forwarded,
            handoff_messages=handoff_messages,
            warnings=warnings,
            errors=errors,
        )


DOCUMENT_DISPATCH_SERVICE = DocumentDispatchService()


def dispatch_docs(
    scan_dir: str,
    db: dict | None = None,
    db_path: str | None = None,
    obj: str | None = None,
    obj_name: str | None = None,
    thread_id: str | None = None,
    dispatcher_message_id: str | None = None,
    recursive: bool = True,
    extensions: list | None = None,
    max_files: int | None = None,
    agent_name: str = "_job_posting_parser",
    dry_run: bool = False,
) -> dict:
    return DOCUMENT_DISPATCH_SERVICE.dispatch_documents(
        scan_dir=scan_dir,
        db=db,
        db_path=db_path,
        obj=obj,
        obj_name=obj_name,
        thread_id=thread_id,
        dispatcher_message_id=dispatcher_message_id,
        recursive=recursive,
        extensions=extensions,
        max_files=max_files,
        agent_name=agent_name,
        dry_run=dry_run,
    )


def batch_generate_new_docs(
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
    """Batch-generate new documents for all job-offer PDFs in a directory.

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


def batch_generate_documents_tool(
    scan_dir: str,
    profile_path: str,
    db_path: str,
    out_dir: str | None = None,
    workflow_name: str = "cover_letter_batch_generation",
    model: str = "gpt-4o-mini",
    max_files: int | None = None,
    max_text_chars: int = 20000,
    dry_run: bool = False,
    write_pdf: bool = True,
    rerun_processed: bool = False,
) -> dict[str, Any]:
    try:
        from .batch_document import batch_document_generate  # type: ignore
    except Exception:
        from batch_document import batch_document_generate  # type: ignore

    return batch_document_generate(
        scan_dir=scan_dir,
        profile_path=profile_path,
        dispatcher_db_path=db_path,
        out_dir=out_dir,
        workflow_name=workflow_name,
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
_VSTORE_GPU_ONLY = os.getenv("AI_IDE_VSTORE_GPU_ONLY", "0").strip() in {"1", "true", "True"}
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
        "no module named 'langchain_huggingface'",
        'no module named "langchain_huggingface"',
        "no module named 'langchain_community'",
        'no module named "langchain_community"',
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
    chunk_strategy: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
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
    if chunk_strategy:
        cmd.extend(["--chunk_strategy", str(chunk_strategy)])
    if chunk_size is not None:
        cmd.extend(["--chunk_size", str(int(chunk_size))])
    if overlap is not None:
        cmd.extend(["--overlap", str(int(overlap))])
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
                        "distance": it.get("distance", it.get("score")),
                        "score": it.get("score"),
                        "score_kind": it.get("score_kind"),
                        "source": it.get("source"),
                        "entry_ref": it.get("entry_ref"),
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
    chunk_strategy: str | None,
    chunk_size: int | None,
    overlap: int | None,
    result_conn,
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
        import importlib

        # Local imports inside the child keep the main GUI process safer.
        try:
            from .get_path import GetPath  # type: ignore
        except ImportError:
            GetPath = None  # type: ignore
            last_get_path_err: Exception | None = None
            for mod_name in ("alde.get_path", "ALDE.alde.get_path", "get_path"):
                try:
                    GetPath = importlib.import_module(mod_name).GetPath  # type: ignore[attr-defined]
                    break
                except Exception as exc:
                    last_get_path_err = exc
            if GetPath is None:
                raise last_get_path_err or ImportError("Could not import GetPath")

        try:
            from .vstores import VectorStore  # type: ignore
        except Exception:
            VectorStore = None  # type: ignore
            vstores_errors: list[Exception] = []
            for mod_name in ("alde.vstores", "ALDE.alde.vstores", "vstores"):
                try:
                    VectorStore = importlib.import_module(mod_name).VectorStore  # type: ignore[attr-defined]
                    break
                except Exception as exc:
                    vstores_errors.append(exc)
            if VectorStore is None:
                raise (vstores_errors[0] if vstores_errors else ImportError("Could not import VectorStore"))

        resolved_store_dir, resolved_manifest = _resolve_vectordb_paths(kind, store_dir, manifest_file)
        db = VectorStore(store_path=resolved_store_dir, manifest_file=resolved_manifest)

        do_autobuild = _VSTORE_AUTOBUILD if autobuild is None else bool(autobuild)
        if do_autobuild:
            # Default build root is the project root.
            default_root = GetPath().get_path(parg=f"{__file__}", opt="p")
            db.build(
                root_dir or default_root,
                chunk_strategy=chunk_strategy,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        result = db.query(query, k=int(k))
        result = _shrink_vectordb_result(result, int(k))
        result_conn.send({"ok": True, "result": result})
    except BaseException as e:
        # Must catch BaseException so we also report SystemExit in case
        # underlying code tries to sys.exit().
        try:
            result_conn.send({"ok": False, "error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass
    finally:
        _shutdown_loky_executor()
        _close_conn(result_conn)


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
    doc_types: list[str] | str | None,
    chunk_strategy: str | None,
    chunk_size: int | None,
    overlap: int | None,
    force: bool,
    remove_store_dir: bool,
    result_conn,
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
            result_conn.send({"ok": True, "result": {"operation": "list", "stores": stores}})
            return

        if op in {"create", "init", "new"}:
            if not _is_safe_store_dir(store_dir):
                result_conn.send({"ok": False, "error": f"Refusing to create unsafe store_dir: {store_dir}"})
                return
            os.makedirs(store_dir, exist_ok=True)
            if not os.path.exists(manifest_file):
                _atomic_write_json(manifest_file, [])
            result_conn.send(
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
                result_conn.send({"ok": False, "error": f"Refusing unsafe store_dir: {store_dir}"})
                return
            result_conn.send(
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
                result_conn.send({"ok": False, "error": f"Refusing unsafe store_dir: {store_dir}"})
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
            db.build(
                resolved_root,
                doc_types=doc_types,
                chunk_strategy=chunk_strategy,
                chunk_size=chunk_size,
                overlap=overlap,
            )
            result_conn.send(
                {
                    "ok": True,
                    "result": {
                        "operation": "build",
                        "root_dir": resolved_root,
                        "doc_types": doc_types,
                        "chunk_strategy": chunk_strategy,
                        "chunk_size": chunk_size,
                        "overlap": overlap,
                        "store": {"name": store_name, "dir": store_dir, "manifest": manifest_file},
                    },
                }
            )
            return

        if op in {"wipe", "reset", "delete"}:
            if not force:
                result_conn.send(
                    {
                        "ok": False,
                        "error": "Refusing wipe without force=true.",
                    }
                )
                return
            if not _is_safe_store_dir(store_dir):
                result_conn.send({"ok": False, "error": f"Refusing unsafe store_dir: {store_dir}"})
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

            result_conn.send(
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

        result_conn.send({"ok": False, "error": f"Unsupported operation: {operation!r}"})
    except BaseException as e:
        try:
            result_conn.send({"ok": False, "error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass
    finally:
        _shutdown_loky_executor()
        _close_conn(result_conn)


def _run_vdb_admin_subprocess(
    operation: str,
    store: str | None = None,
    root_dir: str | None = None,
    doc_types: list[str] | str | None = None,
    chunk_strategy: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
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

    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_vdb_admin_worker,
        args=(
            operation,
            store,
            root_dir,
            doc_types,
            chunk_strategy,
            chunk_size,
            overlap,
            bool(force),
            bool(remove_store_dir),
            child_conn,
        ),
        daemon=True,
    )
    try:
        proc.start()
        _close_conn(child_conn)
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

        if not parent_conn.poll(0.1):
            return "vdb_worker failed: no result returned."

        payload = parent_conn.recv()
    finally:
        _close_conn(child_conn)
        _close_conn(parent_conn)
        _close_process_handle(proc)

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
    chunk_strategy: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list | str:
    """Execute vector DB work in a spawned subprocess with timeout."""
    # Explicit GPU-only mode: never attempt local (potentially CPU) execution.
    if _VSTORE_GPU_ONLY:
        return _run_vectordb_in_micromamba(
            kind,
            query,
            k,
            store_dir=store_dir,
            manifest_file=manifest_file,
            root_dir=root_dir,
            autobuild=autobuild,
            chunk_strategy=chunk_strategy,
            chunk_size=chunk_size,
            overlap=overlap,
        )

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

    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_vectordb_worker,
        args=(
            kind,
            query,
            int(k),
            store_dir,
            manifest_file,
            root_dir,
            autobuild,
            chunk_strategy,
            chunk_size,
            overlap,
            child_conn,
        ),
        daemon=True,
    )
    try:
        proc.start()
        _close_conn(child_conn)
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

        if not parent_conn.poll(0.1):
            return f"{kind} failed: no result returned."

        payload = parent_conn.recv()
    finally:
        _close_conn(child_conn)
        _close_conn(parent_conn)
        _close_process_handle(proc)

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
                chunk_strategy=chunk_strategy,
                chunk_size=chunk_size,
                overlap=overlap,
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
                chunk_strategy=chunk_strategy,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        return f"{kind} error: {err}"
    return f"{kind} error: invalid result payload"


def _now_utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _now_utc_filename_stamp() -> str:
    return _now_utc_datetime().strftime("%Y%m%d_%H%M%S")


def _now_utc_iso() -> str:
    return _now_utc_datetime().isoformat().replace("+00:00", "Z")


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
    chunk_strategy: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
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
        "chunk_strategy": chunk_strategy,
        "chunk_size": chunk_size,
        "overlap": overlap,
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
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
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
    chunk_strategy: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
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
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
    )

def vectordb(
    query: str,
    k: int = 5,
    store_dir: str | None = None,
    manifest_file: str | None = None,
    root_dir: str | None = None,
    autobuild: bool | None = None,
    chunk_strategy: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
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
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
    )


def vdb_worker(
    operation: str,
    store: str | None = None,
    root_dir: str | None = None,
    doc_types: list[str] | str | None = None,
    chunk_strategy: str | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
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
        doc_types=doc_types,
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
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
_TOOL_RUNTIME_REFS: dict[str, Any] = {
    "default_save_dir": _DEFAULT_SAVE_DIR,
    "agent_labels": get_available_agent_labels(),
}


_TOOL_IMPLEMENTATIONS: dict[str, Callable | None] = {
    "memorydb": memorydb,
    "vectordb": vectordb,
    "vdb_worker": vdb_worker,
    "build_agent_system_configs": build_agent_system_configs_tool,
    "execute_action_request": ACTION_REQUEST_SERVICE.execute_request_tool,
    "store_object_result": store_object_result_tool,
    "ingest_object": ingest_object_tool,
    "upsert_object_record": upsert_object_record_tool,
    "upsert_dispatcher_job_record": upsert_dispatcher_job_record_tool,
    "ingest_profile": ingest_profile_tool,
    "ingest_job_posting": ingest_job_posting_tool,
    "store_job_posting_result": store_job_posting_result_tool,
    "store_profile_result": store_profile_result_tool,
    "batch_document_generator": batch_generate_documents_tool,
    "batch_generate_documents": batch_generate_documents_tool,
    "write_document": write_document,
    "read_document": read_document,
    "update_document": update_document,
    "delete_document": delete_document,
    "list_documents": list_documents,
    "md_to_pdf": md_to_pdf,
    "calendar": calendar,
    "send_mail": send_mail,
    "dml_tool": dml_tool,
    "dsl_tool": dsl_tool,
    "code_tool": code_tool,
    "iter_documents": iter_documents,
    "dispatch_documents": DOCUMENT_DISPATCH_SERVICE.dispatch_documents,
    "dispatch_docs": DOCUMENT_DISPATCH_SERVICE.dispatch_documents,
    "fetch_url": fetch_url,
    "fetch_data": fetch_data,
    "call_api": call_api,
    "call": call,
    "accept_call": accept_call,
    "reject_call": reject_call,
    "route_to_agent": None,
}


def _param_spec_from_config(config: dict[str, Any]) -> ParamSpec:
    enum = config.get("enum")
    enum_ref = config.get("enum_ref")
    if enum_ref:
        enum = list(_TOOL_RUNTIME_REFS.get(str(enum_ref), []))

    default = config.get("default")
    default_ref = config.get("default_ref")
    if default_ref:
        default = _TOOL_RUNTIME_REFS.get(str(default_ref))

    return ParamSpec(
        name=str(config.get("name") or ""),
        type=str(config.get("type") or "string"),
        description=str(config.get("description") or ""),
        required=bool(config.get("required", False)),
        enum=enum,
        items=config.get("items"),
        default=default,
    )


def _tool_spec_from_config(config: dict[str, Any]) -> ToolSpec:
    name = normalize_tool_name(str(config.get("name") or ""))
    implementation_name = config.get("implementation_name")
    if implementation_name is None and "implementation_name" in config:
        implementation = None
    else:
        implementation_key = str(implementation_name or name)
        implementation = _TOOL_IMPLEMENTATIONS.get(implementation_key)

    return ToolSpec(
        name=name,
        description=str(config.get("description") or ""),
        parameters=[_param_spec_from_config(param_config) for param_config in (config.get("parameters") or [])],
        implementation=implementation,
    )


def _build_unified_tools() -> list[ToolSpec]:
    return [_tool_spec_from_config(tool_config) for tool_config in get_tool_configs()]


def create_tool_registry(specs: list[ToolSpec]) -> dict[str, dict]:
    return {spec.name: spec.to_tool_definition() for spec in specs}


def create_function_dispatcher(specs: list[ToolSpec]) -> dict[str, Callable]:
    return {spec.name: spec.implementation for spec in specs if spec.implementation}


UNIFIED_TOOLS: list[ToolSpec] = _build_unified_tools()
tool_registry: dict[str, dict] = create_tool_registry(UNIFIED_TOOLS)
function_dispatcher: dict[str, Callable] = create_function_dispatcher(UNIFIED_TOOLS)
_tool_specs_by_name: dict[str, ToolSpec] = {normalize_tool_name(spec.name): spec for spec in UNIFIED_TOOLS}
# ---------------------------------------------------------------------------
# Tool groups (toolsets)lt
# ---------------------------------------------------------------------------
# These are convenience aliases you can use in agent configs, e.g.:
#   tools: ["@rag", "@docs_rw", "route_to_agent"]
# Expansion is handled in agents_factory.get_agent_tools().

TOOL_GROUPS: dict[str, list[str]] = get_tool_group_configs()


def get_tool_registry() -> dict[str, dict]:
    return tool_registry


def get_function_dispatcher() -> dict[str, Callable]:
    return function_dispatcher


def get_tool_spec(name: str) -> ToolSpec | None:
    return _tool_specs_by_name.get(normalize_tool_name(name))


def get_agent_tools(tool_names: list[str]) -> list[dict]:
    resolved: list[dict] = []
    if not tool_names:
        return resolved

    for item in tool_names:
        if isinstance(item, dict):
            if item.get("type") == "function" and isinstance(item.get("function"), dict):
                resolved.append(item)
            continue

        if not isinstance(item, str):
            continue

        if item.startswith("@"):
            group = item[1:].strip()
            for tool_name in (TOOL_GROUPS.get(group) or []):
                normalized_name = normalize_tool_name(tool_name)
                if normalized_name in tool_registry:
                    resolved.append(tool_registry[normalized_name])
            continue

        normalized_name = normalize_tool_name(item)
        if normalized_name in tool_registry:
            resolved.append(tool_registry[normalized_name])

    return resolved


def list_tool_names() -> list[str]:
    """Return all available tool names (from UNIFIED_TOOLS)."""
    out: list[str] = []
    for name in get_available_tool_names():
        normalized_name = normalize_tool_name(name)
        if normalized_name and normalized_name not in out:
            out.append(normalized_name)
    return out