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


def _default_document_db_path(obj: str) -> str:
    return os.path.join(_default_appdata_dir(), f"{obj}_db.json")


def _load_document_db(db_path: str, obj: str) -> dict:
    if not os.path.exists(db_path):
        return {"schema": f"{obj}_db_v1", obj: {}}
    raw = _load_json_file(db_path)
    if isinstance(raw, dict) and isinstance(raw.get(obj), dict):
        return raw
    return {"schema": f"{obj}_db_v1", obj: {}}


def _save_document_db(db_path: str, db: dict) -> None:
    _atomic_write_json(db_path, db)


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


def persist_document_result(
    *,
    correlation_id: str,
    result_payload: dict[str, Any],
    obj: str,
    db_path: str | None = None,
    handoff_metadata: dict[str, Any] | None = None,
    handoff_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_obj = _normalize_document_obj_name(obj)
    resolved_section_key = _document_section_key(resolved_obj)
    resolved_db_path = os.path.abspath(os.path.expanduser(str(db_path or _default_document_db_path(resolved_obj))))
    db = _load_document_db(resolved_db_path, resolved_obj)
    if not isinstance(db, dict):
        db = {"schema": f"{resolved_obj}_db_v1", resolved_obj: {}}
    if not isinstance(db.get(resolved_obj), dict):
        db[resolved_obj] = {}

    document_records = db[resolved_obj]
    record = document_records.get(correlation_id) if isinstance(document_records.get(correlation_id), dict) else {}
    record = dict(record)
    ts = _now_utc_iso()

    metadata = dict(handoff_metadata or {})
    incoming_payload = dict(handoff_payload or {})
    output_payload = incoming_payload.get("output") if isinstance(incoming_payload.get("output"), dict) else {}
    parse_section = result_payload.get("parse") if isinstance(result_payload.get("parse"), dict) else {}
    document_section = _extract_document_section(result_payload, resolved_obj)
    db_updates = result_payload.get("db_updates") if isinstance(result_payload.get("db_updates"), dict) else {}
    fallback_source_payload = output_payload if output_payload else result_payload

    record["correlation_id"] = correlation_id
    record["updated_at"] = ts
    record.setdefault("created_at", ts)
    record["source_agent"] = str(
        incoming_payload.get("agent_label")
        or metadata.get("source_agent")
        or result_payload.get("agent")
        or _document_default_agent(resolved_obj)
    )
    record["link"] = deepcopy(result_payload.get("link") if isinstance(result_payload.get("link"), dict) else output_payload.get("link") if isinstance(output_payload.get("link"), dict) else {})
    record["file"] = deepcopy(result_payload.get("file") if isinstance(result_payload.get("file"), dict) else output_payload.get("file") if isinstance(output_payload.get("file"), dict) else {})
    record["parse"] = deepcopy(parse_section)
    record[resolved_section_key] = deepcopy(document_section)
    record["db_updates"] = deepcopy(db_updates)
    record["handoff_metadata"] = deepcopy(metadata)
    record["source_payload"] = deepcopy(fallback_source_payload)

    document_records[correlation_id] = record
    _save_document_db(resolved_db_path, db)
    return {
        "ok": True,
        "db_path": resolved_db_path,
        "obj_name": resolved_obj,
        "correlation_id": correlation_id,
        "stored": True,
    }


def persist_job_posting_result(
    *,
    correlation_id: str,
    result_payload: dict[str, Any],
    db_path: str | None = None,
    handoff_metadata: dict[str, Any] | None = None,
    handoff_payload: dict[str, Any] | None = None,
    obj: str = "job_postings",
) -> dict[str, Any]:
    return persist_document_result(
        correlation_id=correlation_id,
        result_payload=result_payload,
        obj=obj,
        db_path=db_path,
        handoff_metadata=handoff_metadata,
        handoff_payload=handoff_payload,
    )


def store_job_posting_result_tool(
    job_posting_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    source_payload: dict[str, Any] | None = None,
    obj_name: str | None = None,
) -> str:
    parsed_result = job_posting_result
    if isinstance(parsed_result, str):
        try:
            parsed_result = json.loads(parsed_result)
        except Exception:
            return json.dumps({"ok": False, "error": "invalid_job_posting_result_json"}, ensure_ascii=False)
    if not isinstance(parsed_result, dict):
        return json.dumps({"ok": False, "error": "job_posting_result_must_be_object"}, ensure_ascii=False)

    effective_correlation_id = str(
        correlation_id
        or parsed_result.get("correlation_id")
        or ((parsed_result.get("file") or {}).get("content_sha256") if isinstance(parsed_result.get("file"), dict) else "")
        or ((parsed_result.get("db_updates") or {}).get("content_sha256") if isinstance(parsed_result.get("db_updates"), dict) else "")
        or ""
    ).strip()
    if not effective_correlation_id:
        return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

    metadata = {"source_agent": str(source_agent or parsed_result.get("agent") or "job_posting_parser")}
    resolved_obj_name = _normalize_document_obj_name(obj_name, "job_postings")
    result = persist_job_posting_result(
        correlation_id=effective_correlation_id,
        result_payload=parsed_result,
        db_path=db_path or (str(parsed_result.get(f"{resolved_obj_name}_db_path") or "").strip() or None),
        handoff_metadata=metadata,
        handoff_payload=source_payload if isinstance(source_payload, dict) else None,
        obj=resolved_obj_name,
    )
    return json.dumps(result, ensure_ascii=False)


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
    parsed_result = job_posting_result
    if isinstance(parsed_result, str):
        try:
            parsed_result = json.loads(parsed_result)
        except Exception:
            return json.dumps({"ok": False, "error": "invalid_job_posting_result_json"}, ensure_ascii=False)
    if not isinstance(parsed_result, dict):
        return json.dumps({"ok": False, "error": "job_posting_result_must_be_object"}, ensure_ascii=False)

    effective_correlation_id = str(
        correlation_id
        or parsed_result.get("correlation_id")
        or ((parsed_result.get("file") or {}).get("content_sha256") if isinstance(parsed_result.get("file"), dict) else "")
        or ((parsed_result.get("job_posting") or {}).get("job_id") if isinstance(parsed_result.get("job_posting"), dict) else "")
        or ((source_payload or {}).get("record_id") if isinstance(source_payload, dict) else "")
        or ""
    ).strip()
    if not effective_correlation_id:
        return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

    resolved_obj_name = _normalize_document_obj_name(obj_name, "job_postings")
    resolved_section_key = _document_section_key(resolved_obj_name)

    resolved_dispatcher_db_path = os.path.abspath(os.path.expanduser(str(dispatcher_db_path or _default_dispatcher_db_path())))
    resolved_job_postings_db_path = os.path.abspath(os.path.expanduser(str(job_postings_db_path or _default_document_db_path(resolved_obj_name))))

    original_dispatcher_db = _load_dispatcher_db(resolved_dispatcher_db_path)
    original_job_postings_db = _load_document_db(resolved_job_postings_db_path, resolved_obj_name)
    next_dispatcher_db = deepcopy(original_dispatcher_db if isinstance(original_dispatcher_db, dict) else {"schema": "dispatcher_doc_db_v1", "documents": {}})
    next_job_postings_db = deepcopy(original_job_postings_db if isinstance(original_job_postings_db, dict) else {"schema": f"{resolved_obj_name}_db_v1", resolved_obj_name: {}})

    if not isinstance(next_dispatcher_db.get("documents"), dict):
        next_dispatcher_db["documents"] = {}
    if not isinstance(next_job_postings_db.get(resolved_obj_name), dict):
        next_job_postings_db[resolved_obj_name] = {}

    ts = _now_utc_iso()
    parse_section = parsed_result.get("parse") if isinstance(parsed_result.get("parse"), dict) else {}
    job_posting_section = _extract_document_section(parsed_result, resolved_obj_name)
    db_updates = parsed_result.get("db_updates") if isinstance(parsed_result.get("db_updates"), dict) else {}
    metadata = {"source_agent": str(source_agent or parsed_result.get("agent") or _document_default_agent(resolved_obj_name))}
    source_payload_dict = deepcopy(source_payload) if isinstance(source_payload, dict) else {}

    job_record = next_job_postings_db[resolved_obj_name].get(effective_correlation_id) if isinstance(next_job_postings_db[resolved_obj_name].get(effective_correlation_id), dict) else {}
    job_record = dict(job_record)
    job_record["correlation_id"] = effective_correlation_id
    job_record["updated_at"] = ts
    job_record.setdefault("created_at", ts)
    job_record["source_agent"] = str(source_agent or parsed_result.get("agent") or _document_default_agent(resolved_obj_name))
    job_record["link"] = deepcopy(parsed_result.get("link") if isinstance(parsed_result.get("link"), dict) else {})
    job_record["file"] = deepcopy(parsed_result.get("file") if isinstance(parsed_result.get("file"), dict) else {})
    job_record["parse"] = deepcopy(parse_section)
    job_record[resolved_section_key] = deepcopy(job_posting_section)
    job_record["db_updates"] = deepcopy(db_updates)
    job_record["handoff_metadata"] = deepcopy(metadata)
    job_record["source_payload"] = deepcopy(source_payload_dict)
    next_job_postings_db[resolved_obj_name][effective_correlation_id] = job_record

    normalized_state = str(
        processing_state
        or db_updates.get("processing_state")
        or ("processed" if (job_posting_section or parse_section.get("is_job_posting")) else "failed")
    ).strip().lower() or "failed"
    effective_processed = bool(processed) if processed is not None else bool(db_updates.get("processed")) if isinstance(db_updates.get("processed"), bool) else normalized_state == "processed"
    effective_failed_reason = str(failed_reason or db_updates.get("failed_reason") or "").strip() or None

    dispatcher_record = next_dispatcher_db["documents"].get(effective_correlation_id) if isinstance(next_dispatcher_db["documents"].get(effective_correlation_id), dict) else {}
    dispatcher_record = dict(dispatcher_record)
    dispatcher_record.setdefault("id", effective_correlation_id)
    dispatcher_record["content_sha256"] = effective_correlation_id
    dispatcher_record["processing_state"] = normalized_state
    dispatcher_record["processed"] = effective_processed
    dispatcher_record["last_seen_at"] = ts
    if effective_processed:
        dispatcher_record["processed_at"] = ts
        dispatcher_record["failed_reason"] = None
        dispatcher_record["last_error"] = None
        dispatcher_record["last_error_at"] = None
    else:
        dispatcher_record["failed_reason"] = effective_failed_reason
        dispatcher_record["last_error"] = effective_failed_reason
        dispatcher_record["last_error_at"] = ts if effective_failed_reason else None
    if isinstance(dispatcher_updates, dict):
        for key, value in dispatcher_updates.items():
            if value is None and key in {"failed_reason", "last_error", "last_error_at"}:
                dispatcher_record[str(key)] = None
            elif value is not None:
                dispatcher_record[str(key)] = value
    next_dispatcher_db["documents"][effective_correlation_id] = dispatcher_record

    try:
        _save_document_db(resolved_job_postings_db_path, next_job_postings_db)
        try:
            _save_document_db(resolved_dispatcher_db_path, next_dispatcher_db)
        except Exception:
            _save_document_db(resolved_job_postings_db_path, original_job_postings_db if isinstance(original_job_postings_db, dict) else {"schema": f"{resolved_obj_name}_db_v1", resolved_obj_name: {}})
            raise
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "error": "atomic_upsert_failed",
                "details": f"{type(exc).__name__}: {exc}",
                "correlation_id": effective_correlation_id,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "ok": True,
            "stored": True,
            "dispatcher_updated": True,
            "correlation_id": effective_correlation_id,
            "job_postings_db_path": resolved_job_postings_db_path,
            "dispatcher_db_path": resolved_dispatcher_db_path,
            "processing_state": normalized_state,
            "processed": effective_processed,
        },
        ensure_ascii=False,
    )


def store_profile_result_tool(
    profile_result: dict[str, Any] | str,
    correlation_id: str | None = None,
    db_path: str | None = None,
    source_agent: str | None = None,
    obj_name: str | None = None,
) -> str:
    parsed_result = profile_result
    if isinstance(parsed_result, str):
        try:
            parsed_result = json.loads(parsed_result)
        except Exception:
            return json.dumps({"ok": False, "error": "invalid_profile_result_json"}, ensure_ascii=False)
    if not isinstance(parsed_result, dict):
        return json.dumps({"ok": False, "error": "profile_result_must_be_object"}, ensure_ascii=False)

    effective_correlation_id = str(
        correlation_id
        or parsed_result.get("correlation_id")
        or ((parsed_result.get("profile") or {}).get("profile_id") if isinstance(parsed_result.get("profile"), dict) else "")
        or ""
    ).strip()
    if not effective_correlation_id:
        return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

    normalized_result = deepcopy(parsed_result)
    if source_agent:
        normalized_result["agent"] = str(source_agent)

    result = persist_profile_result(
        correlation_id=effective_correlation_id,
        profile_result=normalized_result,
        db_path=db_path or (str(parsed_result.get(f"{_normalize_document_obj_name(obj_name, 'profiles')}_db_path") or "").strip() or None),
        obj=obj_name or "profiles",
    )
    return json.dumps(result, ensure_ascii=False)


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
    parsed_result = profile_result
    if isinstance(parsed_result, str):
        try:
            parsed_result = json.loads(parsed_result)
        except Exception:
            return json.dumps({"ok": False, "error": "invalid_profile_result_json"}, ensure_ascii=False)

    if parsed_result is None:
        request_payload: dict[str, Any] | None = None
        if isinstance(applicant_profile, dict):
            request_payload = applicant_profile
        elif isinstance(profile, dict):
            request_payload = {"source": "text", "value": profile}
        if not isinstance(request_payload, dict):
            return json.dumps({"ok": False, "error": "missing_profile_payload"}, ensure_ascii=False)
        parsed_result = _build_profile_result_from_request(request_payload)

    if not isinstance(parsed_result, dict):
        return json.dumps({"ok": False, "error": "profile_result_must_be_object"}, ensure_ascii=False)

    effective_correlation_id = str(
        correlation_id
        or parsed_result.get("correlation_id")
        or ((parsed_result.get("profile") or {}).get("profile_id") if isinstance(parsed_result.get("profile"), dict) else "")
        or ((source_payload or {}).get("profile_id") if isinstance(source_payload, dict) else "")
        or ""
    ).strip()
    if not effective_correlation_id:
        return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

    normalized_result = deepcopy(parsed_result)
    normalized_result["correlation_id"] = effective_correlation_id
    if source_agent:
        normalized_result["agent"] = str(source_agent)
    if isinstance(source_payload, dict):
        normalized_result["source_payload"] = deepcopy(source_payload)

    return store_profile_result_tool(
        profile_result=normalized_result,
        correlation_id=effective_correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        obj_name=obj_name,
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
    parsed_result = job_posting_result
    if isinstance(parsed_result, str):
        try:
            parsed_result = json.loads(parsed_result)
        except Exception:
            return json.dumps({"ok": False, "error": "invalid_job_posting_result_json"}, ensure_ascii=False)

    if parsed_result is None:
        if not isinstance(job_posting, dict):
            return json.dumps({"ok": False, "error": "missing_job_posting_payload"}, ensure_ascii=False)
        parsed_result = {
            "agent": str(source_agent or "job_platform_ingest"),
            "correlation_id": correlation_id,
            "parse": deepcopy(parse) if isinstance(parse, dict) else {"is_job_posting": True, "errors": [], "warnings": []},
            "job_posting": deepcopy(job_posting),
        }

    if not isinstance(parsed_result, dict):
        return json.dumps({"ok": False, "error": "job_posting_result_must_be_object"}, ensure_ascii=False)

    inferred_job_posting = parsed_result.get("job_posting") if isinstance(parsed_result.get("job_posting"), dict) else {}
    inferred_source_payload = source_payload if isinstance(source_payload, dict) else {}
    effective_correlation_id = str(
        correlation_id
        or parsed_result.get("correlation_id")
        or ((parsed_result.get("file") or {}).get("content_sha256") if isinstance(parsed_result.get("file"), dict) else "")
        or inferred_job_posting.get("job_id")
        or inferred_job_posting.get("external_id")
        or inferred_source_payload.get("record_id")
        or inferred_source_payload.get("id")
        or inferred_source_payload.get("url")
        or ""
    ).strip()
    if not effective_correlation_id:
        return json.dumps({"ok": False, "error": "missing_correlation_id"}, ensure_ascii=False)

    normalized_result = deepcopy(parsed_result)
    normalized_result["correlation_id"] = effective_correlation_id
    if source_agent:
        normalized_result["agent"] = str(source_agent)
    if not isinstance(normalized_result.get("parse"), dict):
        normalized_result["parse"] = deepcopy(parse) if isinstance(parse, dict) else {"is_job_posting": True, "errors": [], "warnings": []}

    return store_job_posting_result_tool(
        job_posting_result=normalized_result,
        correlation_id=effective_correlation_id,
        db_path=db_path,
        source_agent=source_agent,
        source_payload=inferred_source_payload or None,
        obj_name=obj_name,
    )


def get_persisted_document_result(
    correlation_id: str,
    *,
    obj: str,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    resolved_obj = _normalize_document_obj_name(obj)
    resolved_section_key = _document_section_key(resolved_obj)
    resolved_db_path = os.path.abspath(os.path.expanduser(str(db_path or _default_document_db_path(resolved_obj))))
    db = _load_document_db(resolved_db_path, resolved_obj)
    document_records = db.get(resolved_obj) if isinstance(db, dict) else None
    if not isinstance(document_records, dict):
        return None
    record = document_records.get(correlation_id)
    if not isinstance(record, dict):
        return None

    return {
        "agent": str(record.get("source_agent") or record.get("agent") or _document_default_agent(resolved_obj)),
        "correlation_id": str(record.get("correlation_id") or correlation_id),
        "link": deepcopy(record.get("link") or {}),
        "file": deepcopy(record.get("file") or {}),
        "parse": deepcopy(record.get("parse") or {}),
        resolved_section_key: deepcopy(record.get(resolved_section_key) or record.get(resolved_obj) or {}),
        "db_updates": deepcopy(record.get("db_updates") or {}),
    }


def persist_profile_result(
    *,
    correlation_id: str,
    profile_result: dict[str, Any],
    db_path: str | None = None,
    obj: str = "profiles",
) -> dict[str, Any]:
    return persist_document_result(
        correlation_id=correlation_id,
        result_payload=profile_result,
        obj=obj,
        db_path=db_path,
    )


def get_persisted_profile_result(
    correlation_id: str,
    *,
    db_path: str | None = None,
    obj_name: str | None = None,
) -> dict[str, Any] | None:
    stored = get_persisted_document_result(
        correlation_id,
        db_path=db_path,
        obj=obj_name or "profiles",
    )
    if not isinstance(stored, dict):
        return None
    return {
        "agent": str(stored.get("agent") or "profile_parser"),
        "correlation_id": str(stored.get("correlation_id") or correlation_id),
        "parse": deepcopy(stored.get("parse") or {}),
        "profile": deepcopy(stored.get("profile") or {}),
    }


def get_persisted_job_posting_result(
    correlation_id: str,
    *,
    db_path: str | None = None,
    obj_name: str | None = None,
) -> dict[str, Any] | None:
    resolution_config = dict(get_action_request_schema_config("ingest_job_posting").get("request_resolution") or {})
    resolved_obj_name = str(obj_name or resolution_config.get("job_posting_obj_name") or "job_postings").strip() or "job_postings"
    stored = get_persisted_document_result(
        correlation_id,
        db_path=db_path,
        obj=resolved_obj_name,
    )
    if not isinstance(stored, dict):
        return None
    resolved_section_key = _document_section_key(resolved_obj_name)
    return {
        "agent": str(stored.get("agent") or _document_default_agent(resolved_obj_name)),
        "correlation_id": str(stored.get("correlation_id") or correlation_id),
        "link": deepcopy(stored.get("link") or {}),
        "file": deepcopy(stored.get("file") or {}),
        "parse": deepcopy(stored.get("parse") or {}),
        "job_posting": deepcopy(stored.get(resolved_section_key) or {}),
        "db_updates": deepcopy(stored.get("db_updates") or {}),
    }


def _build_profile_result_from_request(profile_payload: Any) -> dict[str, Any] | None:
    if not isinstance(profile_payload, dict):
        return None

    source = str(profile_payload.get("source") or "").strip().lower()
    value = profile_payload.get("value")

    def _profile_result_from_profile(profile: Any, *, source_path: str | None = None) -> dict[str, Any] | None:
        if not isinstance(profile, dict):
            return None
        profile_copy = deepcopy(profile)
        if source_path:
            profile_copy.setdefault("source_path", source_path)
        preferences = profile_copy.get("preferences") if isinstance(profile_copy.get("preferences"), dict) else {}
        return {
            "agent": "profile_parser",
            "correlation_id": profile_copy.get("profile_id"),
            "parse": {
                "language": preferences.get("language", "de"),
                "errors": [],
                "warnings": [],
            },
            "profile": profile_copy,
        }

    def _parse_profile_file(candidate_path: str) -> dict[str, Any] | None:
        resolved_path = os.path.abspath(os.path.expanduser(candidate_path))
        if not os.path.isfile(resolved_path):
            return None
        try:
            loaded = _load_json_file(resolved_path)
        except Exception:
            try:
                with open(resolved_path, "r", encoding="utf-8") as f:
                    content = f.read()
                loaded = json.loads(content)
            except Exception:
                return None
        return _profile_result_from_profile(loaded, source_path=resolved_path)

    if source in {"profile_result", "resolved_profile", "parsed_profile"} and isinstance(value, dict):
        return deepcopy(value)

    if source in {"profile_id", "profiles_db", "stored_profile", "persisted_profile"}:
        correlation_id = ""
        if isinstance(value, str):
            correlation_id = value.strip()
        elif isinstance(value, dict):
            correlation_id = str(
                value.get("correlation_id")
                or value.get("profile_id")
                or value.get("id")
                or ""
            ).strip()
        if not correlation_id:
            correlation_id = str(
                profile_payload.get("correlation_id")
                or profile_payload.get("profile_id")
                or ""
            ).strip()
        if not correlation_id:
            return None
        db_path = str(
            profile_payload.get("db_path")
            or profile_payload.get("profiles_db_path")
            or ""
        ).strip() or None
        stored_profile = get_persisted_profile_result(correlation_id, db_path=db_path)
        if isinstance(stored_profile, dict):
            return stored_profile
        return None

    if source in {"file", "path", "json_file", "structured_file", "document_file"}:
        candidate_path = ""
        if isinstance(value, str):
            candidate_path = value.strip()
        elif isinstance(value, dict):
            candidate_path = str(
                value.get("path")
                or value.get("file_path")
                or value.get("value")
                or value.get("source_path")
                or ""
            ).strip()
        if not candidate_path:
            candidate_path = str(
                profile_payload.get("path")
                or profile_payload.get("file_path")
                or profile_payload.get("source_path")
                or ""
            ).strip()
        if candidate_path:
            return _parse_profile_file(candidate_path)

    if source not in {"text", "json", "dict", "object", "structured", "inline"}:
        return None

    if isinstance(value, dict):
        return _profile_result_from_profile(value)
    if isinstance(value, str):
        return _profile_result_from_profile({"raw_text": value})
    return None


def _build_job_posting_result_from_request(
    job_posting_payload: Any,
    *,
    resolution_config: dict[str, Any] | None = None,
    fallback_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(job_posting_payload, dict):
        return None

    resolution = dict(resolution_config or {})
    fallback = dict(fallback_payload or {})
    source = str(job_posting_payload.get("source") or "").strip().lower()
    value = job_posting_payload.get("value")
    store_sources = {
        str(item).strip().lower()
        for item in (resolution.get("job_posting_store_sources") or [])
        if str(item).strip()
    } or {"correlation_id", "job_postings_db", "stored_job_posting", "persisted_job_posting"}
    file_sources = {
        str(item).strip().lower()
        for item in (resolution.get("job_posting_file_sources") or [])
        if str(item).strip()
    } or {"file", "path", "text_file", "document_file", "structured_file", "json_file"}
    inline_sources = {
        str(item).strip().lower()
        for item in (resolution.get("job_posting_inline_sources") or [])
        if str(item).strip()
    } or {"text", "json", "dict", "object", "structured", "inline"}
    resolved_obj_name = str(
        job_posting_payload.get("obj_name")
        or fallback.get("obj_name")
        or resolution.get("job_posting_obj_name")
        or "job_postings"
    ).strip() or "job_postings"
    resolved_db_path_field = str(
        (
            f"{resolved_obj_name}_db_path"
            if (job_posting_payload.get("obj_name") or fallback.get("obj_name"))
            else resolution.get("job_posting_db_path_field")
        )
        or f"{resolved_obj_name}_db_path"
    ).strip() or f"{resolved_obj_name}_db_path"

    def _inline_result(raw_value: Any) -> dict[str, Any] | None:
        if isinstance(raw_value, dict):
            job_posting = deepcopy(raw_value)
            title = str(job_posting.get("job_title") or job_posting.get("title") or job_posting.get("position") or "").strip()
            if title:
                job_posting["job_title"] = title
            if not str(job_posting.get("company_name") or "").strip() and isinstance(job_posting.get("company"), dict):
                company_name = str(job_posting["company"].get("name") or job_posting["company"].get("about") or "").strip()
                if company_name:
                    job_posting["company_name"] = company_name
            correlation_id = str(
                job_posting.get("correlation_id")
                or job_posting.get("job_id")
                or job_posting.get("external_id")
                or title
                or ""
            ).strip() or None
            return {
                "agent": "job_posting_parser",
                "correlation_id": correlation_id,
                "parse": {"is_job_posting": True, "errors": [], "warnings": []},
                "job_posting": job_posting,
            }
        if isinstance(raw_value, str):
            raw_text = raw_value.strip()
            if not raw_text:
                return None
            return {
                "agent": "job_posting_parser",
                "correlation_id": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "parse": {"is_job_posting": True, "errors": [], "warnings": []},
                "job_posting": {"raw_text": raw_text},
            }
        return None

    if source in store_sources:
        correlation_id = ""
        if isinstance(value, str):
            correlation_id = value.strip()
        elif isinstance(value, dict):
            correlation_id = str(
                value.get("correlation_id")
                or value.get("content_sha256")
                or value.get("job_id")
                or value.get("id")
                or ""
            ).strip()
        if not correlation_id:
            correlation_id = str(job_posting_payload.get("correlation_id") or job_posting_payload.get("content_sha256") or "").strip()
        if not correlation_id:
            return None
        db_path = str(
            job_posting_payload.get("db_path")
            or job_posting_payload.get(resolved_db_path_field)
            or fallback.get(resolved_db_path_field)
            or ""
        ).strip() or None
        return get_persisted_job_posting_result(correlation_id, db_path=db_path, obj_name=resolved_obj_name)

    if source in file_sources:
        candidate_path = ""
        if isinstance(value, str):
            candidate_path = value.strip()
        elif isinstance(value, dict):
            candidate_path = str(
                value.get("path")
                or value.get("file_path")
                or value.get("value")
                or value.get("source_path")
                or ""
            ).strip()
        if not candidate_path:
            candidate_path = str(job_posting_payload.get("path") or job_posting_payload.get("file_path") or job_posting_payload.get("source_path") or "").strip()
        if not candidate_path:
            return None
        resolved_path = os.path.abspath(os.path.expanduser(candidate_path))
        if not os.path.isfile(resolved_path):
            return None
        content_sha256 = _sha256_file(resolved_path)
        result = None
        try:
            result = _inline_result(_load_json_file(resolved_path))
        except Exception:
            result = None
        if not isinstance(result, dict):
            try:
                with open(resolved_path, "r", encoding="utf-8") as f:
                    result = _inline_result(f.read())
            except Exception:
                return None
        if not isinstance(result, dict):
            return None
        result["correlation_id"] = str(result.get("correlation_id") or content_sha256)
        result["file"] = {
            "path": resolved_path,
            "content_sha256": content_sha256,
        }
        return result

    if source in inline_sources or (not source and value is not None):
        return _inline_result(value)

    return None


def resolve_configured_request_payload(payload: Any) -> Any:
    raw_payload = payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return raw_payload

    if not isinstance(payload, dict):
        return raw_payload
    action = str(payload.get("action") or "").strip().lower()
    schema_config = get_action_request_schema_config(action)
    resolution_config = dict(schema_config.get("request_resolution") or {})
    if not resolution_config:
        return raw_payload

    enriched_payload = deepcopy(payload)

    if not isinstance(enriched_payload.get("profile_result"), dict):
        profile_result = _build_profile_result_from_request(enriched_payload.get("applicant_profile"))
        if isinstance(profile_result, dict):
            enriched_payload["profile_result"] = profile_result

    batch_workflow_name = str(resolution_config.get("batch_workflow_name") or "").strip()
    batch_tool_name = normalize_tool_name(str(resolution_config.get("batch_tool_name") or ""))
    if batch_workflow_name:
        enriched_payload.setdefault("batch_workflow_name", batch_workflow_name)
    if batch_tool_name:
        enriched_payload.setdefault("batch_tool_name", batch_tool_name)

    if not isinstance(enriched_payload.get("job_posting_result"), dict):
        job_posting_result = _build_job_posting_result_from_request(
            enriched_payload.get("job_posting"),
            resolution_config=resolution_config,
            fallback_payload=enriched_payload,
        )
        if isinstance(job_posting_result, dict):
            enriched_payload["job_posting_result"] = job_posting_result

    if isinstance(enriched_payload.get("job_posting_result"), dict):
        enriched_payload.pop("job_posting", None)
        job_posting_db_path_field = str(resolution_config.get("job_posting_db_path_field") or "job_postings_db_path").strip() or "job_postings_db_path"
        enriched_payload.pop(job_posting_db_path_field, None)
        return enriched_payload

    job_posting = enriched_payload.get("job_posting")
    if not isinstance(job_posting, dict):
        return enriched_payload

    source = str(job_posting.get("source") or "").strip().lower()
    job_posting_store_sources = {
        str(value).strip().lower()
        for value in (resolution_config.get("job_posting_store_sources") or [])
        if str(value).strip()
    }
    job_posting_obj_name = str(
        job_posting.get("obj_name")
        or enriched_payload.get("obj_name")
        or resolution_config.get("job_posting_obj_name")
        or "job_postings"
    ).strip() or "job_postings"
    job_posting_db_path_field = str(
        (
            f"{job_posting_obj_name}_db_path"
            if (job_posting.get("obj_name") or enriched_payload.get("obj_name"))
            else resolution_config.get("job_posting_db_path_field")
        )
        or f"{job_posting_obj_name}_db_path"
    ).strip() or f"{job_posting_obj_name}_db_path"
    if not job_posting_store_sources:
        job_posting_store_sources = {"correlation_id", "job_postings_db", "stored_job_posting", "persisted_job_posting"}
    if source not in job_posting_store_sources:
        return enriched_payload

    correlation_id = ""
    value = job_posting.get("value")
    if isinstance(value, str):
        correlation_id = value.strip()
    elif isinstance(value, dict):
        correlation_id = str(value.get("correlation_id") or value.get("content_sha256") or value.get("id") or "").strip()
    if not correlation_id:
        correlation_id = str(job_posting.get("correlation_id") or job_posting.get("content_sha256") or "").strip()
    if not correlation_id:
        return enriched_payload

    db_path = str(
        job_posting.get("db_path")
        or enriched_payload.get(job_posting_db_path_field)
        or ""
    ).strip() or None

    stored_result = get_persisted_job_posting_result(
        correlation_id,
        db_path=db_path,
        obj_name=job_posting_obj_name,
    )
    if not isinstance(stored_result, dict):
        return enriched_payload

    enriched_job_posting = dict(enriched_payload.get("job_posting") or {})
    enriched_job_posting["resolved_from_store"] = True
    enriched_job_posting["resolved_correlation_id"] = correlation_id
    enriched_job_posting["resolved_obj_name"] = job_posting_obj_name
    if db_path:
        enriched_payload[job_posting_db_path_field] = db_path
    enriched_payload["job_posting"] = enriched_job_posting
    enriched_payload["job_posting_result"] = stored_result
    return enriched_payload


def execute_deterministic_action_request(payload: Any) -> str | None:
    raw_payload = payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None

    if not isinstance(payload, dict):
        return None

    action = str(payload.get("action") or "").strip().lower()
    if not action:
        return None

    schema_config = get_action_request_schema_config(action)
    resolution_config = dict(schema_config.get("request_resolution") or {}) if isinstance(schema_config, dict) else {}
    if schema_config:
        validation = validate_action_request(action, payload)
        if not validation.get("valid"):
            return json.dumps(
                {
                    "ok": False,
                    "error": "invalid_action_request",
                    "action": action,
                    "schema_name": validation.get("schema_name") or "",
                    "errors": list(validation.get("errors") or []),
                    "warnings": list(validation.get("warnings") or []),
                },
                ensure_ascii=False,
            )

    if action in {"ingest_profile", "store_profile", "store_profile_result", "persist_profile"}:
        resolved_profile_obj_name = str(
            payload.get("obj_name")
            or resolution_config.get("profile_obj_name")
            or "profiles"
        ).strip() or "profiles"
        resolved_profile_db_path_field = str(
            (
                f"{resolved_profile_obj_name}_db_path"
                if payload.get("obj_name")
                else resolution_config.get("profile_db_path_field")
            )
            or f"{resolved_profile_obj_name}_db_path"
        ).strip() or f"{resolved_profile_obj_name}_db_path"
        return ingest_profile_tool(
            profile=payload.get("profile") if isinstance(payload.get("profile"), dict) else None,
            applicant_profile=payload.get("applicant_profile") if isinstance(payload.get("applicant_profile"), dict) else None,
            profile_result=payload.get("profile_result"),
            correlation_id=payload.get("correlation_id"),
            db_path=payload.get(resolved_profile_db_path_field) or payload.get("profiles_db_path") or payload.get("db_path"),
            source_agent=payload.get("source_agent"),
            source_payload=payload.get("source_payload") if isinstance(payload.get("source_payload"), dict) else None,
            obj_name=resolved_profile_obj_name,
        )

    if action in {"ingest_job_posting", "store_job_posting", "store_job_posting_result"}:
        resolved_job_posting_obj_name = str(
            payload.get("obj_name")
            or resolution_config.get("job_posting_obj_name")
            or "job_postings"
        ).strip() or "job_postings"
        resolved_job_posting_db_path_field = str(
            (
                f"{resolved_job_posting_obj_name}_db_path"
                if payload.get("obj_name")
                else resolution_config.get("job_posting_db_path_field")
            )
            or f"{resolved_job_posting_obj_name}_db_path"
        ).strip() or f"{resolved_job_posting_obj_name}_db_path"
        return ingest_job_posting_tool(
            job_posting=payload.get("job_posting") if isinstance(payload.get("job_posting"), dict) else None,
            job_posting_result=payload.get("job_posting_result"),
            correlation_id=payload.get("correlation_id"),
            db_path=payload.get(resolved_job_posting_db_path_field) or payload.get("job_postings_db_path") or payload.get("db_path"),
            source_agent=payload.get("source_agent"),
            source_payload=payload.get("source_payload") if isinstance(payload.get("source_payload"), dict) else None,
            parse=payload.get("parse") if isinstance(payload.get("parse"), dict) else None,
            obj_name=resolved_job_posting_obj_name,
        )

    if action in {"upsert_dispatcher_job_record", "upsert_job_record"}:
        resolved_job_posting_obj_name = str(
            payload.get("obj_name")
            or resolution_config.get("job_posting_obj_name")
            or "job_postings"
        ).strip() or "job_postings"
        resolved_job_posting_db_path_field = str(
            (
                f"{resolved_job_posting_obj_name}_db_path"
                if payload.get("obj_name")
                else resolution_config.get("job_posting_db_path_field")
            )
            or f"{resolved_job_posting_obj_name}_db_path"
        ).strip() or f"{resolved_job_posting_obj_name}_db_path"
        return upsert_dispatcher_job_record_tool(
            job_posting_result=payload.get("job_posting_result") if payload.get("job_posting_result") is not None else payload.get("job_posting") or {},
            correlation_id=payload.get("correlation_id"),
            dispatcher_db_path=payload.get("dispatcher_db_path"),
            job_postings_db_path=payload.get(resolved_job_posting_db_path_field) or payload.get("job_postings_db_path") or payload.get("db_path"),
            obj_name=resolved_job_posting_obj_name,
            processing_state=payload.get("processing_state"),
            processed=payload.get("processed") if isinstance(payload.get("processed"), bool) else None,
            failed_reason=payload.get("failed_reason"),
            source_agent=payload.get("source_agent"),
            source_payload=payload.get("source_payload") if isinstance(payload.get("source_payload"), dict) else None,
            dispatcher_updates=payload.get("dispatcher_updates") if isinstance(payload.get("dispatcher_updates"), dict) else None,
        )

    return None


def execute_action_request_tool(
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

    result = execute_deterministic_action_request(request_payload)
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
    resolved_db_path = os.path.abspath(os.path.expanduser(str(db_path or _default_dispatcher_db_path())))
    db = _load_dispatcher_db(resolved_db_path)
    if not isinstance(db, dict):
        db = {"schema": "dispatcher_doc_db_v1", "documents": {}}
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
                record[key] = None
            elif value is not None:
                record[str(key)] = value

    docs[correlation_id] = record
    _save_dispatcher_db(resolved_db_path, db)
    return {
        "ok": True,
        "db_path": resolved_db_path,
        "correlation_id": correlation_id,
        "processing_state": normalized_state,
        "processed": effective_processed,
    }


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
    """Discover PDFs, fingerprint them, check/update a small DB, and prepare parser handoffs.

    This is intentionally deterministic and does not read/parse PDF contents.
    """

    ts = _now_utc_iso()
    dispatch_policy = dict((get_tool_config("dispatch_documents") or {}).get("dispatch_policy") or {})
    scan_dir_original = str(scan_dir or "")
    scan_dir = os.path.abspath(os.path.expanduser(scan_dir_original))
    thread_id = (thread_id or "UNKNOWN")
    dispatcher_message_id = (dispatcher_message_id or "UNKNOWN")
    agent_name = str(
        agent_name
        or dispatch_policy.get("default_target_agent")
        or "_job_posting_parser"
    ).strip() or "_job_posting_parser"
    resolved_obj_name = str(
        obj_name
        or obj
        or dispatch_policy.get("obj_name")
        or "job_postings"
    ).strip() or "job_postings"
    resolved_obj_db_path_field = str(
        dispatch_policy.get("obj_db_path_field")
        or f"{resolved_obj_name}_db_path"
    ).strip() or f"{resolved_obj_name}_db_path"

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

        metadata_defaults = dict(dispatch_policy.get("metadata_defaults") or {})
        obj_db_path = None
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
            obj_db_path = _default_document_db_path(resolver_obj_name)
        elif isinstance(obj_db_default.get("value"), str) and str(obj_db_default.get("value") or "").strip():
            obj_db_path = os.path.abspath(os.path.expanduser(str(obj_db_default.get("value"))))

        payload = {
            "type": str(dispatch_policy.get("document_type") or "file"),
            "correlation_id": sha,
            "obj_name": resolved_obj_name,
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
            "requested_actions": list(dispatch_policy.get("requested_actions") or ["parse", "extract_text", "store_job_posting", "mark_processed_on_success"]),
        }

        if dry_run:
            continue

        forwarded.append({
            "path": item["path"],
            "content_sha256": sha,
            "link": {"thread_id": thread_id, "message_id": "PENDING"},
        })
        handoff_metadata = {
            "correlation_id": sha,
            "dispatcher_message_id": dispatcher_message_id,
            "dispatcher_db_path": resolved_db_path,
            "obj_name": resolved_obj_name,
            resolved_obj_db_path_field: obj_db_path,
        }
        if resolved_obj_db_path_field != "job_postings_db_path":
            handoff_metadata["job_postings_db_path"] = obj_db_path

        handoff = build_agent_handoff(
            source_agent_label=str(dispatch_policy.get("source_agent") or "_data_dispatcher"),
            target_agent=agent_name,
            protocol=str(dispatch_policy.get("handoff_protocol") or "agent_handoff_v1"),
            agent_response={
                "agent_label": str(dispatch_policy.get("source_agent") or "_data_dispatcher"),
                "output": payload,
                "handoff_to": agent_name,
            },
            handoff_metadata=handoff_metadata,
        )
        handoff_messages.append({
            "target_agent": agent_name,
            "handoff_protocol": handoff["protocol"],
            "message_text": handoff["message_text"],
            "handoff_payload": handoff["handoff_payload"],
            "handoff_metadata": handoff["metadata"],
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
            "parser_agent_name": agent_name,
            "dry_run": bool(dry_run),
        },
    }
    return report


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
    "execute_action_request": execute_action_request_tool,
    "upsert_dispatcher_job_record": upsert_dispatcher_job_record_tool,
    "ingest_profile": ingest_profile_tool,
    "ingest_job_posting": ingest_job_posting_tool,
    "store_job_posting_result": store_job_posting_result_tool,
    "store_profile_result": store_profile_result_tool,
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
    "dispatch_documents": dispatch_docs,
    "dispatch_docs": dispatch_docs,
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