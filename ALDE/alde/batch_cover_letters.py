from __future__ import annotations

import argparse
import json
import os
import textwrap
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
    from .apply_agent_prompts import SYSTEM_PROMPT  # type: ignore
except Exception:
    from apply_agent_prompts import SYSTEM_PROMPT  # type: ignore

try:
    from .tools import dispatch_job_posting_pdfs, _load_dispatcher_db, _save_dispatcher_db, write_document  # type: ignore
except Exception:
    from tools import dispatch_job_posting_pdfs, _load_dispatcher_db, _save_dispatcher_db, write_document  # type: ignore

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


def _job_payload_from_scan_item(item: dict, thread_id: str, message_id: str) -> dict:
    return {
        "type": "job_posting_pdf",
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
        "requested_actions": ["parse", "extract_text", "store_job_posting", "mark_processed_on_success"],
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


def batch_generate(
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
) -> dict:
    model_requested = model
    model, model_warning = _normalize_chat_model_name(model)
    warnings_out: list[str] = []
    if model_warning:
        warnings_out.append(model_warning)

    scan_dir = os.path.abspath(os.path.expanduser(scan_dir))
    profile_path = os.path.abspath(os.path.expanduser(profile_path))
    dispatcher_db_path = os.path.abspath(os.path.expanduser(dispatcher_db_path))
    out_dir = os.path.abspath(os.path.expanduser(out_dir or os.path.join(scan_dir, "Cover_letters")))
    os.makedirs(out_dir, exist_ok=True)
    out_dir_real = os.path.realpath(out_dir)

    profile = _load_json(profile_path)

    # Load OPENAI_API_KEY from local .env (if present).
    # NOTE: `load_dotenv()` without an explicit path can crash on some
    # Python versions/environments (it uses stack-frame inspection).
    # Passing an explicit path keeps batch runs deterministic.
    if load_dotenv is not None:
        try:
            repo_root = Path(__file__).resolve().parent.parent
            env_path = repo_root / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path, override=False)
        except Exception:
            # If something goes wrong, continue; callers may have already
            # exported OPENAI_API_KEY.
            pass
    client: OpenAI | None = None
    if not dry_run:
        if OpenAI is None:
            raise RuntimeError(f"openai unavailable: {_OPENAI_IMPORT_ERROR}")
        client = OpenAI()

    # Build a profile_result wrapper that matches the cover letter agent's input contract.
    profile_id = None
    if isinstance(profile, dict):
        profile_id = profile.get("profile_id")
    profile_result = {
        "agent": "profile_parser",
        "correlation_id": profile_id,
        "parse": {"language": (profile.get("preferences", {}) or {}).get("language", "de"), "errors": [], "warnings": []},
        "profile": profile,
    }

    # Scan PDFs and get items to process.
    scan_report = dispatch_job_posting_pdfs(
        scan_dir=scan_dir,
        db_path=dispatcher_db_path,
        thread_id="batch",
        dispatcher_message_id="batch",
        recursive=True,
        max_files=max_files,
        dry_run=dry_run,
    )

    classified = (scan_report.get("classified") or {}) if isinstance(scan_report, dict) else {}
    to_process = []
    # In this project DB, many items may remain in "queued" (classified as known_processing).
    # For batch generation, include those as well.
    buckets = ["new", "known_unprocessed", "known_processing"]
    if rerun_processed:
        buckets.append("known_processed")

    for bucket in buckets:
        items = classified.get(bucket) or []
        if isinstance(items, list):
            to_process.extend(items)

    db = _load_dispatcher_db(dispatcher_db_path)
    docs = db.setdefault("documents", {})

    results: list[dict] = []

    for item in to_process:
        try:
            pdf_path = item.get("path")
            if not pdf_path or not isinstance(pdf_path, str):
                raise ValueError("missing_pdf_path")

            pdf_path = os.path.abspath(os.path.expanduser(pdf_path))
            # Never treat our generated outputs as inputs.
            if os.path.realpath(pdf_path).startswith(out_dir_real + os.sep):
                continue

            base = os.path.basename(pdf_path)
            if base == "Muster_Anschreiben.pdf":
                continue

            sha = item.get("content_sha256")
            if not sha:
                raise ValueError("missing_sha")

            # Skip already processed items (in case DB has changed since scan).
            rec = docs.get(sha) if isinstance(docs, dict) else None
            if isinstance(rec, dict) and (rec.get("processed") is True or str(rec.get("processing_state")).lower() == "processed"):
                if not rerun_processed:
                    continue
                # Mark as queued for re-run (best-effort; safe if DB is read-only/dry_run).
                if (not dry_run) and isinstance(docs, dict):
                    try:
                        rec = dict(rec)
                        rec["processed"] = False
                        rec["processing_state"] = "queued"
                        rec["last_error"] = None
                        docs[sha] = rec
                        _save_dispatcher_db(dispatcher_db_path, db)
                    except Exception:
                        pass

            if not os.path.exists(pdf_path):
                # Try fallback to scan_dir if DB stored a different root.
                alt = os.path.join(scan_dir, base)
                if os.path.exists(alt):
                    pdf_path = alt
                else:
                    raise FileNotFoundError(pdf_path)

            if dry_run:
                results.append({"pdf": pdf_path, "sha": sha, "status": "dry_run"})
                continue

            text = _extract_pdf_text(pdf_path)
            if max_text_chars and isinstance(text, str) and len(text) > int(max_text_chars):
                text = text[: int(max_text_chars)]
            job_payload = _job_payload_from_scan_item(item, thread_id="batch", message_id="PENDING")
            job_payload["extracted_text"] = text

            if client is None:
                raise RuntimeError("OpenAI client unavailable (dry_run=True)")

            # 1) Parse job posting into structured JSON.
            parser_system = SYSTEM_PROMPT.get("_job_posting_parser_agent") or SYSTEM_PROMPT.get("_job_posting_parser")
            if not parser_system:
                raise KeyError("Missing system prompt for job posting parser (expected '_job_posting_parser' or legacy '_job_posting_parser_agent')")
            parser_messages = [
                {"role": "system", "content": parser_system},
                {"role": "user", "content": json.dumps(job_payload, ensure_ascii=False)},
            ]
            _try_chathistory_log(
                "openai.chat.completions.create request",
                messages=parser_messages,
                data={"model": model, "n_messages": len(parser_messages), "temperature": 0.2, "stage": "job_posting_parser"},
                name_tool="job_posting_parser",
            )
            try:
                parsed_job_raw = client.chat.completions.create(model=model, messages=parser_messages, temperature=0.2)
            except Exception as exc:
                _try_chathistory_log(
                    "openai.chat.completions.create error",
                    messages=parser_messages,
                    data={"model": model, "stage": "job_posting_parser", "error": f"{type(exc).__name__}: {exc}"},
                    name_tool="job_posting_parser",
                )
                raise
            job_posting_text = (parsed_job_raw.choices[0].message.content or "").strip()
            _try_chathistory_log(
                "openai.chat.completions.create response",
                messages=parser_messages,
                data={"model": model, "response_id": getattr(parsed_job_raw, "id", None), "stage": "job_posting_parser"},
                generated=job_posting_text,
                name_tool="job_posting_parser",
            )
            job_posting_result = _json_loads_loose(job_posting_text)

            # 2) Generate cover letter JSON.
            options = {
                "language": (profile.get("preferences", {}) or {}).get("language", "de"),
                "tone": (profile.get("preferences", {}) or {}).get("tone", "modern"),
                "max_words": (profile.get("preferences", {}) or {}).get("max_length", 350),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "city": None,
                "include_enclosures": True,
            }
            cover_input = {
                "job_posting_result": job_posting_result,
                "profile_result": profile_result,
                "options": options,
            }
            cover_messages = [
                {"role": "system", "content": SYSTEM_PROMPT["_cover_letter_agent"]},
                {"role": "user", "content": json.dumps(cover_input, ensure_ascii=False)},
            ]
            _try_chathistory_log(
                "openai.chat.completions.create request",
                messages=cover_messages,
                data={"model": model, "n_messages": len(cover_messages), "temperature": 0.2, "stage": "cover_letter"},
                name_tool="cover_letter",
            )
            try:
                cover_raw = client.chat.completions.create(model=model, messages=cover_messages, temperature=0.2)
            except Exception as exc:
                _try_chathistory_log(
                    "openai.chat.completions.create error",
                    messages=cover_messages,
                    data={"model": model, "stage": "cover_letter", "error": f"{type(exc).__name__}: {exc}"},
                    name_tool="cover_letter",
                )
                raise
            cover_text = (cover_raw.choices[0].message.content or "").strip()
            _try_chathistory_log(
                "openai.chat.completions.create response",
                messages=cover_messages,
                data={"model": model, "response_id": getattr(cover_raw, "id", None), "stage": "cover_letter"},
                generated=cover_text,
                name_tool="cover_letter",
            )
            cover_result = _json_loads_loose(cover_text)

            full_text = (((cover_result or {}).get("cover_letter") or {}).get("full_text"))
            if not full_text or not isinstance(full_text, str):
                raise ValueError("cover_letter_missing_full_text")

            doc_id = os.path.splitext(base)[0]

            saved = write_document(content=full_text, path=out_dir, doc_id=doc_id)
            saved_text_path = str(saved).split(": ", 1)[-1].strip()

            saved_pdf_path: str | None = None
            if write_pdf:
                saved_pdf_path = _write_pdf(content=full_text, out_dir=out_dir, doc_id=doc_id)

            # Update DB record
            if isinstance(docs, dict):
                rec = docs.get(sha) if isinstance(docs.get(sha), dict) else {}
                rec = dict(rec)
                rec["processed"] = True
                rec["processing_state"] = "processed"
                rec["processed_at"] = _utc_now_iso_z()
                rec["cover_letter_text_path"] = saved_text_path
                rec["cover_letter_pdf_path"] = saved_pdf_path
                rec["cover_letter_path"] = saved_pdf_path or saved_text_path
                rec["last_error"] = None
                docs[sha] = rec
                _save_dispatcher_db(dispatcher_db_path, db)

            results.append({
                "pdf": pdf_path,
                "sha": sha,
                "status": "ok",
                "cover_letter_text": saved_text_path,
                "cover_letter_pdf": saved_pdf_path,
                "cover_letter": saved_pdf_path or saved_text_path,
            })

        except Exception as exc:
            sha = (item or {}).get("content_sha256")
            if (not dry_run) and sha and isinstance(docs, dict):
                rec = docs.get(sha) if isinstance(docs.get(sha), dict) else {}
                rec = dict(rec)
                rec["processed"] = False
                rec["processing_state"] = "failed"
                rec["failed_reason"] = f"{type(exc).__name__}: {exc}"
                rec["last_error"] = f"{type(exc).__name__}: {exc}"
                rec["last_error_at"] = _utc_now_iso_z()
                docs[sha] = rec
                _save_dispatcher_db(dispatcher_db_path, db)
            results.append({"pdf": item.get("path"), "sha": sha, "status": "error", "error": f"{type(exc).__name__}: {exc}"})

    return {
        "scan_dir": scan_dir,
        "out_dir": out_dir,
        "dispatcher_db": dispatcher_db_path,
        "model_requested": model_requested,
        "model_used": model,
        "warnings": warnings_out,
        "processed": len([r for r in results if r.get("status") == "ok"]),
        "errors": len([r for r in results if r.get("status") == "error"]),
        "results": results,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-generate cover letters for all job-offer PDFs in a directory")
    ap.add_argument("--scan-dir", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--max-files", type=int, default=None)
    ap.add_argument("--max-text-chars", type=int, default=20000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write-pdf", action="store_true", help="Also write each cover letter as a PDF (requires reportlab)")
    args = ap.parse_args()

    report = batch_generate(
        scan_dir=args.scan_dir,
        profile_path=args.profile,
        dispatcher_db_path=args.db,
        out_dir=args.out_dir,
        model=args.model,
        max_files=args.max_files,
        max_text_chars=args.max_text_chars,
        dry_run=args.dry_run,
        write_pdf=args.write_pdf,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
