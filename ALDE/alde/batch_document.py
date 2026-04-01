from __future__ import annotations

import argparse
import json
import os
import textwrap
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

try:
    from openai import OpenAI  # type: ignore
except Exception as exc:  # pragma: no cover
    OpenAI = None  # type: ignore
    _OPENAI_IMPORT_ERROR = exc
else:
    _OPENAI_IMPORT_ERROR = None

try:
    from dotenv import load_dotenv  # type: ignore
except Exception as exc:  # pragma: no cover
    load_dotenv = None  # type: ignore
    _DOTENV_IMPORT_ERROR = exc
else:
    _DOTENV_IMPORT_ERROR = None


def _try_chathistory_log(
    event: str,
    *,
    messages: list[dict[str, Any]] | None = None,
    data: dict | None = None,
    generated: str | None = None,
    name_tool: str | None = None,
) -> None:
    """Best-effort ChatHistory logging; safe to call from batch scripts.

    Logging schema for this batch script:
    - `_content`: the OpenAI `messages` payload (prompt)
    - `_data`: metadata + generated model text (when available)
    """
    try:
        try:
            from .chat_completion import ChatHistory  # type: ignore
        except Exception:
            from alde.chat_completion import ChatHistory  # type: ignore

        payload: dict[str, Any] = {"event": event}
        if data:
            payload.update(data)
        if generated is not None:
            payload["generated"] = generated

        # Use agent label for the tool message name (shown in ChatHistory UI).
        # Fall back to stage/agent from metadata, and finally to the OpenAI method.
        tool_label: str | None = None
        if isinstance(name_tool, str) and name_tool.strip():
            tool_label = name_tool.strip()
        else:
            cand = None
            if isinstance(data, dict):
                cand = data.get("stage") or data.get("agent") or data.get("name")
            if isinstance(cand, str) and cand.strip():
                tool_label = cand.strip()
        if not tool_label:
            tool_label = "openai.chat.completions.create"

        ChatHistory().log(
            _role="tool",
            _content=messages if messages is not None else event,
            _obj="model",
            _data=payload,
            _thread_name="model",
            _name_tool=tool_label,
        )
    except Exception:
        return

try:
    from .agents_config import get_batch_workflow_config, get_specialized_system_prompt, validate_batch_workflow_config  # type: ignore
except Exception:
    from ALDE.alde.agents_config import get_batch_workflow_config, get_specialized_system_prompt, validate_batch_workflow_config  # type: ignore

try:
    from .tools import DOCUMENT_DISPATCH_SERVICE, DOCUMENT_REPOSITORY, write_document  # type: ignore
except Exception:
    from alde.tools import DOCUMENT_DISPATCH_SERVICE, DOCUMENT_REPOSITORY, write_document  # type: ignore

try:
    from pypdf import PdfReader  # type: ignore
except Exception as exc:  # pragma: no cover
    PdfReader = None  # type: ignore
    _PDF_IMPORT_ERROR = exc
else:
    _PDF_IMPORT_ERROR = None


try:
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.lib.units import mm  # type: ignore
    from reportlab.pdfbase.pdfmetrics import stringWidth  # type: ignore
    from reportlab.pdfgen import canvas  # type: ignore
except Exception as exc:  # pragma: no cover
    canvas = None  # type: ignore
    _REPORTLAB_IMPORT_ERROR = exc
else:
    _REPORTLAB_IMPORT_ERROR = None


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_pdf_text(pdf_path: str) -> str:
    if PdfReader is None:
        raise RuntimeError(f"pypdf unavailable: {_PDF_IMPORT_ERROR}")
    reader = PdfReader(pdf_path)
    parts: list[str] = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            parts.append(txt)
    return "\n\n".join(parts)


def _write_pdf(*, content: str, out_dir: str, doc_id: str) -> str:
    """Write `content` as a simple, text-only PDF and return the file path."""
    if canvas is None:
        raise RuntimeError(f"reportlab unavailable: {_REPORTLAB_IMPORT_ERROR}")

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{doc_id}.pdf")

    page_w, page_h = A4
    margin = 18 * mm
    x0 = margin
    y = page_h - margin

    font_name = "Helvetica"
    font_size = 11
    leading = 14
    max_width = page_w - 2 * margin

    c = canvas.Canvas(out_path, pagesize=A4)
    c.setTitle(doc_id)
    c.setFont(font_name, font_size)

    def _new_page() -> None:
        nonlocal y
        c.showPage()
        c.setFont(font_name, font_size)
        y = page_h - margin

    def _wrap_line(line: str) -> list[str]:
        s = (line or "").rstrip("\n")
        if not s.strip():
            return [""]

        words = s.split(" ")
        out: list[str] = []
        cur = ""

        for w in words:
            candidate = (cur + " " + w).strip() if cur else w
            if stringWidth(candidate, font_name, font_size) <= max_width:
                cur = candidate
                continue

            if cur:
                out.append(cur)
                cur = ""

            # If a single word is too long, hard-wrap it.
            if stringWidth(w, font_name, font_size) > max_width:
                # Estimate characters per line by average character width.
                avg = max(3.0, stringWidth("abcdefghijklmnopqrstuvwxyz", font_name, font_size) / 26.0)
                est = max(10, int(max_width / avg))
                for chunk in textwrap.wrap(w, width=est, break_long_words=True, break_on_hyphens=False):
                    out.append(chunk)
            else:
                cur = w

        if cur:
            out.append(cur)
        return out

    for raw_line in (content or "").splitlines():
        for line in _wrap_line(raw_line):
            if y < margin + leading:
                _new_page()
            c.drawString(x0, y, line)
            y -= leading

    c.save()
    return out_path


def _utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_loads_loose(s: str) -> Any:
    s = (s or "").strip()
    if not s:
        raise ValueError("empty response")
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Try to recover if the model wrapped JSON in extra text.
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start : end + 1])
        raise


def _job_payload_from_scan_item(
    item: dict,
    thread_id: str,
    message_id: str,
    *,
    requested_actions: list[str] | None = None,
) -> dict:
    return {
        "type": "file",
        "correlation_id": item.get("content_sha256"),
        "link": {"thread_id": thread_id, "message_id": message_id},
        "file": {
            "path": item.get("path"),
            "name": item.get("name"),
            "content_sha256": item.get("content_sha256"),
            "file_size_bytes": item.get("file_size_bytes"),
            "mtime_epoch": item.get("mtime_epoch"),
        },
        "db": {
            "existing_record_id": (item.get("db") or {}).get("existing_record_id"),
            "processing_state": (item.get("db") or {}).get("processing_state") or "new",
        },
        "requested_actions": list(requested_actions or ["parse", "extract_text", "store_file", "mark_processed_on_success"]),
    }


_DEPRECATED_OR_INCOMPATIBLE_MODEL_ALIASES: dict[str, str] = {
    # Legacy Completions-era models (deprecated) — map to a modern chat model.
    "text-davinci-002": "gpt-4o-mini",
    "text-davinci-003": "gpt-4o-mini",
    "code-davinci-002": "gpt-4o-mini",
    # Completions-only model; this pipeline uses Chat Completions.
    "gpt-3.5-turbo-instruct": "gpt-4o-mini",
}


def _normalize_chat_model_name(model: str) -> tuple[str, str | None]:
    """Normalize model names for this module.

    This pipeline calls `client.chat.completions.create(...)`.
    If callers pass deprecated/incompatible model ids (often from old history),
    we transparently map them to a supported chat model.

    Returns: (model_used, warning_or_none)
    """
    requested = (model or "").strip()
    if not requested:
        return "gpt-4o-mini", "Empty model id; defaulted to gpt-4o-mini."

    mapped = _DEPRECATED_OR_INCOMPATIBLE_MODEL_ALIASES.get(requested)
    if mapped:
        return mapped, f"Model '{requested}' is deprecated/incompatible; using '{mapped}'."

    # Heuristic guard for other legacy davinci ids.
    low = requested.lower()
    if low.startswith("text-davinci-") or low.startswith("code-davinci-"):
        return "gpt-4o-mini", f"Model '{requested}' is deprecated/incompatible; using 'gpt-4o-mini'."

    return requested, None


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    current: Any = payload
    for segment in str(key or "").split("."):
        if not segment:
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _resolve_batch_template(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [_resolve_batch_template(item, context) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)

    special_keys = {"literal", "from_context", "from_profile", "default"}
    if any(key in value for key in special_keys):
        if "literal" in value:
            return deepcopy(value.get("literal"))
        default = deepcopy(value.get("default"))
        if "from_context" in value:
            resolved = _payload_value(context, str(value.get("from_context") or ""))
            return deepcopy(default if resolved is None else resolved)
        if "from_profile" in value:
            profile = context.get("profile") if isinstance(context.get("profile"), dict) else {}
            resolved = _payload_value(profile, str(value.get("from_profile") or ""))
            return deepcopy(default if resolved is None else resolved)
    return {key: _resolve_batch_template(item, context) for key, item in value.items()}


def _resolve_batch_tool(tool_name: str) -> Any:
    normalized = str(tool_name or "").strip()
    if normalized in {"dispatch_documents", "dispatch_docs"}:
        return DOCUMENT_DISPATCH_SERVICE.dispatch_documents
    if normalized == "write_document":
        return write_document
    if normalized == "internal_text_pdf":
        return _write_pdf
    raise KeyError(f"Unsupported batch workflow tool: {tool_name}")


def _build_profile_result(profile: dict[str, Any], workflow_config: dict[str, Any]) -> dict[str, Any]:
    profile_config = dict(workflow_config.get("profile_result") or {})
    correlation_id_path = str(profile_config.get("correlation_id_path") or "profile_id")
    language_path = str(profile_config.get("language_path") or "preferences.language")
    correlation_id = _payload_value(profile, correlation_id_path)
    language = _payload_value(profile, language_path) or profile_config.get("default_language") or "de"
    return {
        "agent": str(profile_config.get("agent") or "xworker"),
        "correlation_id": correlation_id,
        "parse": {"language": language, "errors": [], "warnings": []},
        "profile": profile,
    }


def _run_model_stage(
    client: Any,
    *,
    model: str,
    stage_config: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    prompt_config = dict(stage_config.get("prompt") or {})
    agent_type = str(prompt_config.get("agent_type") or "").strip()
    task_name = str(prompt_config.get("task_name") or "").strip()
    system_prompt = get_specialized_system_prompt(agent_type, task_name)
    if not system_prompt:
        raise KeyError(f"Missing specialized system prompt for {agent_type}:{task_name}")

    if "input_template" in stage_config:
        stage_input = _resolve_batch_template(stage_config.get("input_template"), context)
    else:
        stage_input = _resolve_batch_template(stage_config.get("input"), context)

    stage_name = str(stage_config.get("name") or f"{agent_type}:{task_name}")
    history = dict(stage_config.get("history") or {})
    history_stage = str(history.get("request_stage") or stage_name)
    history_name = str(history.get("tool_name") or stage_name)
    temperature = float(stage_config.get("temperature") or 0.2)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(stage_input, ensure_ascii=False)},
    ]
    _try_chathistory_log(
        "openai.chat.completions.create request",
        messages=messages,
        data={"model": model, "n_messages": len(messages), "temperature": temperature, "stage": history_stage},
        name_tool=history_name,
    )
    try:
        raw_response = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
    except Exception as exc:
        _try_chathistory_log(
            "openai.chat.completions.create error",
            messages=messages,
            data={"model": model, "stage": history_stage, "error": f"{type(exc).__name__}: {exc}"},
            name_tool=history_name,
        )
        raise

    response_text = (raw_response.choices[0].message.content or "").strip()
    _try_chathistory_log(
        "openai.chat.completions.create response",
        messages=messages,
        data={"model": model, "response_id": getattr(raw_response, "id", None), "stage": str(history.get("response_stage") or history_stage)},
        generated=response_text,
        name_tool=history_name,
    )

    response_format = str(stage_config.get("response_format") or "json").strip().lower()
    result: Any = response_text if response_format == "text" else _json_loads_loose(response_text)
    store_as = str(stage_config.get("store_as") or "").strip()
    if store_as:
        context[store_as] = deepcopy(result)
    stage_results = context.setdefault("stage_results", {})
    if isinstance(stage_results, dict):
        stage_results[stage_name] = deepcopy(result)
    return result


def _apply_record_updates(record: dict[str, Any], update_template: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    updates = _resolve_batch_template(update_template, context)
    if isinstance(updates, dict):
        updated.update(updates)
    return updated


class BatchDocumentGenerationService:
    def normalize_paths(
        self,
        *,
        scan_dir: str,
        profile_path: str,
        dispatcher_db_path: str,
        out_dir: str | None,
    ) -> tuple[str, str, str, str, str]:
        resolved_scan_dir = os.path.abspath(os.path.expanduser(scan_dir))
        resolved_profile_path = os.path.abspath(os.path.expanduser(profile_path))
        resolved_dispatcher_db_path = os.path.abspath(os.path.expanduser(dispatcher_db_path))
        resolved_out_dir = os.path.abspath(os.path.expanduser(out_dir or os.path.join(resolved_scan_dir, "Cover_letters")))
        os.makedirs(resolved_out_dir, exist_ok=True)
        return (
            resolved_scan_dir,
            resolved_profile_path,
            resolved_dispatcher_db_path,
            resolved_out_dir,
            os.path.realpath(resolved_out_dir),
        )

    def load_workflow_config(self, workflow_name: str) -> dict[str, Any]:
        workflow_config = get_batch_workflow_config(workflow_name)
        validation = validate_batch_workflow_config(workflow_name, workflow_config)
        if not validation.get("valid"):
            raise ValueError("Invalid batch workflow config '" + workflow_name + "': " + "; ".join(validation.get("errors") or []))
        return workflow_config

    def load_profile_context(self, *, profile_path: str, workflow_config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = _load_json(profile_path)
        profile_dict = profile if isinstance(profile, dict) else {}
        return profile_dict, _build_profile_result(profile_dict, workflow_config)

    def load_env(self) -> None:
        if load_dotenv is None:
            return
        try:
            repo_root = Path(__file__).resolve().parent.parent
            env_path = repo_root / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path, override=False)
        except Exception:
            return

    def create_model_client(self, *, dry_run: bool) -> Any | None:
        if dry_run:
            return None
        if OpenAI is None:
            raise RuntimeError(f"openai unavailable: {_OPENAI_IMPORT_ERROR}")
        return OpenAI()

    def build_scan_report(
        self,
        *,
        scan_dir: str,
        dispatcher_db_path: str,
        dispatcher_config: dict[str, Any],
        max_files: int | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        dispatch_tool = _resolve_batch_tool(str(dispatcher_config.get("tool_name") or "dispatch_documents"))
        report = dispatch_tool(
            scan_dir=scan_dir,
            db_path=dispatcher_db_path,
            thread_id=str(dispatcher_config.get("thread_id") or "batch"),
            dispatcher_message_id=str(dispatcher_config.get("dispatcher_message_id") or "batch"),
            recursive=bool(dispatcher_config.get("recursive", True)),
            max_files=max_files,
            dry_run=dry_run,
        )
        return report if isinstance(report, dict) else {}

    def collect_process_items(
        self,
        *,
        scan_report: dict[str, Any],
        dispatcher_config: dict[str, Any],
        rerun_processed: bool,
    ) -> list[dict[str, Any]]:
        classified = scan_report.get("classified") if isinstance(scan_report.get("classified"), dict) else {}
        buckets = [
            str(bucket)
            for bucket in (dispatcher_config.get("bucket_order") or ["new", "known_unprocessed", "known_processing"])
            if str(bucket).strip()
        ]
        if rerun_processed:
            rerun_bucket = str(dispatcher_config.get("rerun_bucket") or "known_processed").strip()
            if rerun_bucket:
                buckets.append(rerun_bucket)

        items_to_process: list[dict[str, Any]] = []
        for bucket in buckets:
            items = classified.get(bucket) or []
            if isinstance(items, list):
                items_to_process.extend(item for item in items if isinstance(item, dict))
        return items_to_process

    def prepare_item(
        self,
        *,
        item: dict[str, Any],
        scan_dir: str,
        out_dir_real: str,
        skip_basenames: set[str],
        skip_output_dir_inputs: bool,
        rerun_processed: bool,
        dry_run: bool,
        dispatcher_db_path: str,
    ) -> tuple[str, str] | None:
        pdf_path = item.get("path")
        if not pdf_path or not isinstance(pdf_path, str):
            raise ValueError("missing_pdf_path")

        resolved_pdf_path = os.path.abspath(os.path.expanduser(pdf_path))
        if skip_output_dir_inputs and os.path.realpath(resolved_pdf_path).startswith(out_dir_real + os.sep):
            return None

        base_name = os.path.basename(resolved_pdf_path)
        if base_name in skip_basenames:
            return None

        correlation_id = item.get("content_sha256")
        if not correlation_id or not isinstance(correlation_id, str):
            raise ValueError("missing_sha")

        record = item.get("db") if isinstance(item.get("db"), dict) else {}
        if record.get("processed") is True or str(record.get("processing_state") or "").lower() == "processed":
            if not rerun_processed:
                return None
            if not dry_run:
                try:
                    DOCUMENT_REPOSITORY.update_dispatcher_status(
                        correlation_id=correlation_id,
                        processing_state="queued",
                        db_path=dispatcher_db_path,
                        processed=False,
                        failed_reason=None,
                        extra_updates={
                            "last_error": None,
                            "last_error_at": None,
                            "failed_reason": None,
                        },
                    )
                except Exception:
                    pass

        if not os.path.exists(resolved_pdf_path):
            fallback_path = os.path.join(scan_dir, base_name)
            if os.path.exists(fallback_path):
                resolved_pdf_path = fallback_path
            else:
                raise FileNotFoundError(resolved_pdf_path)

        return resolved_pdf_path, correlation_id

    def build_job_payload(
        self,
        *,
        item: dict[str, Any],
        dispatcher_config: dict[str, Any],
        job_payload_config: dict[str, Any],
        extracted_text: str,
    ) -> dict[str, Any]:
        payload = _job_payload_from_scan_item(
            item,
            thread_id=str(dispatcher_config.get("thread_id") or "batch"),
            message_id="PENDING",
            requested_actions=[str(action) for action in (job_payload_config.get("requested_actions") or []) if str(action).strip()] or None,
        )
        if bool(job_payload_config.get("include_extracted_text", True)):
            payload["extracted_text"] = extracted_text
        return payload

    def build_generation_context(
        self,
        *,
        profile: dict[str, Any],
        profile_result: dict[str, Any],
        job_payload: dict[str, Any],
        out_dir: str,
        write_pdf: bool,
        dispatcher_db_path: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        base_name = os.path.basename(str(item.get("path") or "document"))
        document_id = os.path.splitext(base_name)[0]
        return {
            "profile": deepcopy(profile),
            "profile_result": deepcopy(profile_result),
            "job_payload": deepcopy(job_payload),
            "correlation_id": str(item.get("content_sha256") or "").strip() or None,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "out_dir": out_dir,
            "write_pdf": write_pdf,
            "doc_id": document_id,
            "dispatcher_db_path": dispatcher_db_path,
            "job_postings_db_path": "",
            "item": deepcopy(item),
            "stage_results": {},
        }

    def run_stage_sequence(
        self,
        *,
        client: Any,
        model: str,
        stages: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> None:
        if client is None:
            raise RuntimeError("OpenAI client unavailable (dry_run=True)")
        for stage_config in stages:
            _run_model_stage(client, model=model, stage_config=stage_config, context=context)

    def write_output_documents(
        self,
        *,
        context: dict[str, Any],
        document_output: dict[str, Any],
    ) -> tuple[str, str | None]:
        full_text = _resolve_batch_template({"from_context": "cover_letter_result.cover_letter.full_text"}, context)
        if not full_text or not isinstance(full_text, str):
            raise ValueError("cover_letter_missing_full_text")

        text_writer = _resolve_batch_tool(str(document_output.get("text_writer_tool") or "write_document"))
        text_writer_input = _resolve_batch_template(document_output.get("text_writer_input") or {}, context)
        saved = text_writer(**text_writer_input)
        if isinstance(saved, dict):
            saved_text_path = str(
                saved.get("path")
                or saved.get("file_path")
                or saved.get("document_path")
                or saved.get("md_path")
                or ""
            ).strip()
        else:
            saved_text_path = str(saved).split(": ", 1)[-1].strip()
        if not saved_text_path:
            raise ValueError("write_document_missing_path")
        context["saved_text_path"] = saved_text_path

        saved_pdf_path: str | None = None
        pdf_enabled = bool(
            _resolve_batch_template(
                {"from_context": str(document_output.get("enabled_context_path") or "write_pdf"), "default": False},
                context,
            )
        )
        if pdf_enabled and str(document_output.get("pdf_writer") or "").strip():
            pdf_writer = _resolve_batch_tool(str(document_output.get("pdf_writer") or ""))
            pdf_writer_input = _resolve_batch_template(document_output.get("pdf_writer_input") or {}, context)
            saved_pdf_path = pdf_writer(**pdf_writer_input)

        context["saved_pdf_path"] = saved_pdf_path
        context["saved_document_path"] = saved_pdf_path or saved_text_path
        context["utc_now"] = _utc_now_iso_z()
        return saved_text_path, saved_pdf_path

    def persist_dispatcher_record(
        self,
        *,
        dispatcher_db_path: str,
        correlation_id: str | None,
        updates: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        if not correlation_id:
            return
        record = DOCUMENT_REPOSITORY.get_dispatcher_record(correlation_id, db_path=dispatcher_db_path) or {}
        updated_record = _apply_record_updates(record, updates, context)
        DOCUMENT_REPOSITORY.upsert_dispatcher_record_fields(
            correlation_id=correlation_id,
            db_path=dispatcher_db_path,
            record_updates=updated_record,
        )

    def generate_documents(
        self,
        scan_dir: str,
        profile_path: str,
        dispatcher_db_path: str,
        out_dir: str | None = None,
        model: str = "gpt-4o-mini",
        max_files: int | None = None,
        max_text_chars: int = 20000,
        dry_run: bool = False,
        write_pdf: bool = True,
        rerun_processed: bool = False,
        workflow_name: str = "cover_letter_batch_generation",
    ) -> dict[str, Any]:
        model_requested = model
        model, model_warning = _normalize_chat_model_name(model)
        warnings_out: list[str] = []
        if model_warning:
            warnings_out.append(model_warning)

        scan_dir, profile_path, dispatcher_db_path, out_dir, out_dir_real = self.normalize_paths(
            scan_dir=scan_dir,
            profile_path=profile_path,
            dispatcher_db_path=dispatcher_db_path,
            out_dir=out_dir,
        )
        workflow_config = self.load_workflow_config(workflow_name)
        dispatcher_config = dict(workflow_config.get("dispatcher") or {})
        filter_config = dict(workflow_config.get("filters") or {})
        job_payload_config = dict(workflow_config.get("job_payload") or {})
        stages = [dict(stage or {}) for stage in (workflow_config.get("stages") or [])]
        document_output = dict(workflow_config.get("document_output") or {})
        dispatcher_record = dict(workflow_config.get("dispatcher_record") or {})

        profile, profile_result = self.load_profile_context(profile_path=profile_path, workflow_config=workflow_config)
        self.load_env()
        client = self.create_model_client(dry_run=dry_run)

        scan_report = self.build_scan_report(
            scan_dir=scan_dir,
            dispatcher_db_path=dispatcher_db_path,
            dispatcher_config=dispatcher_config,
            max_files=max_files,
            dry_run=dry_run,
        )
        items_to_process = self.collect_process_items(
            scan_report=scan_report,
            dispatcher_config=dispatcher_config,
            rerun_processed=rerun_processed,
        )

        results: list[dict[str, Any]] = []
        skip_basenames = {str(name) for name in (filter_config.get("skip_basenames") or []) if str(name).strip()}
        skip_output_dir_inputs = bool(filter_config.get("skip_output_dir_inputs", True))

        for item in items_to_process:
            correlation_id: str | None = None
            try:
                prepared_item = self.prepare_item(
                    item=item,
                    scan_dir=scan_dir,
                    out_dir_real=out_dir_real,
                    skip_basenames=skip_basenames,
                    skip_output_dir_inputs=skip_output_dir_inputs,
                    rerun_processed=rerun_processed,
                    dry_run=dry_run,
                    dispatcher_db_path=dispatcher_db_path,
                )
                if prepared_item is None:
                    continue
                pdf_path, correlation_id = prepared_item

                if dry_run:
                    results.append({"pdf": pdf_path, "sha": correlation_id, "status": "dry_run"})
                    continue

                extracted_text = _extract_pdf_text(pdf_path)
                if max_text_chars and isinstance(extracted_text, str) and len(extracted_text) > int(max_text_chars):
                    extracted_text = extracted_text[: int(max_text_chars)]

                job_payload = self.build_job_payload(
                    item=item,
                    dispatcher_config=dispatcher_config,
                    job_payload_config=job_payload_config,
                    extracted_text=extracted_text,
                )
                context = self.build_generation_context(
                    profile=profile,
                    profile_result=profile_result,
                    job_payload=job_payload,
                    out_dir=out_dir,
                    write_pdf=write_pdf,
                    dispatcher_db_path=dispatcher_db_path,
                    item=item,
                )
                self.run_stage_sequence(client=client, model=model, stages=stages, context=context)
                saved_text_path, saved_pdf_path = self.write_output_documents(context=context, document_output=document_output)
                self.persist_dispatcher_record(
                    dispatcher_db_path=dispatcher_db_path,
                    correlation_id=correlation_id,
                    updates=dict(dispatcher_record.get("success_updates") or {}),
                    context=context,
                )
                results.append(
                    {
                        "pdf": pdf_path,
                        "sha": correlation_id,
                        "status": "ok",
                        "document_text": saved_text_path,
                        "document_pdf": saved_pdf_path,
                        "document ": saved_pdf_path or saved_text_path,
                    }
                )
            except Exception as exc:
                error_context = {"error_message": f"{type(exc).__name__}: {exc}", "utc_now": _utc_now_iso_z()}
                self.persist_dispatcher_record(
                    dispatcher_db_path=dispatcher_db_path,
                    correlation_id=correlation_id or (item.get("content_sha256") if isinstance(item, dict) else None),
                    updates=dict(dispatcher_record.get("failure_updates") or {}),
                    context=error_context,
                )
                results.append(
                    {
                        "pdf": item.get("path") if isinstance(item, dict) else None,
                        "sha": correlation_id or (item.get("content_sha256") if isinstance(item, dict) else None),
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        return {
            "scan_dir": scan_dir,
            "out_dir": out_dir,
            "dispatcher_db": dispatcher_db_path,
            "workflow_name": workflow_name,
            "model_requested": model_requested,
            "model_used": model,
            "warnings": warnings_out,
            "processed": len([result for result in results if result.get("status") == "ok"]),
            "errors": len([result for result in results if result.get("status") == "error"]),
            "results": results,
        }


BATCH_DOCUMENT_GENERATION_SERVICE = BatchDocumentGenerationService()


def batch_document_generator(
    scan_dir: str,
    profile_path: str,
    dispatcher_db_path: str,
    out_dir: str | None = None,
    model: str = "gpt-4o-mini",
    max_files: int | None = None,
    max_text_chars: int = 20000,
    dry_run: bool = False,
    write_pdf: bool = True,
    rerun_processed: bool = False,
    workflow_name: str = "cover_letter_batch_generation",
) -> dict:
    return BATCH_DOCUMENT_GENERATION_SERVICE.generate_documents(
        scan_dir=scan_dir,
        profile_path=profile_path,
        dispatcher_db_path=dispatcher_db_path,
        out_dir=out_dir,
        model=model,
        max_files=max_files,
        max_text_chars=max_text_chars,
        dry_run=dry_run,
        write_pdf=write_pdf,
        rerun_processed=rerun_processed,
        workflow_name=workflow_name,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-generate files for a batch of input_files")
    ap.add_argument("--scan-dir", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--workflow-name", default="cover_letter_batch_generation")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--max-files", type=int, default=None)
    ap.add_argument("--max-text-chars", type=int, default=20000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write-pdf", action="store_true", help="Also write each cover letter as a PDF (requires reportlab)")
    args = ap.parse_args()

    report = batch_document_generator(
        scan_dir=args.scan_dir,
        profile_path=args.profile,
        dispatcher_db_path=args.db,
        out_dir=args.out_dir,
        workflow_name=args.workflow_name,
        model=args.model,
        max_files=args.max_files,
        max_text_chars=args.max_text_chars,
        dry_run=args.dry_run,
        write_pdf=args.write_pdf,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def batch_document_generate(*args: Any, **kwargs: Any) -> dict:
    return batch_document_generator(*args, **kwargs)


if __name__ == "__main__":
    main()
