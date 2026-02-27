from __future__ import annotations

"""Simple CLI client for iter_documents.

Usage examples:
    python -m alde.doc_client /path/to/corpus --stats
    python -m alde.doc_client . --limit 20 --show-metadata
    python -m alde.doc_client ./docs --export out.json

Environment:
    Set AI_IDE_DOC_VERBOSE=1 for per-document progress output.
"""

import json
import os
import sys
import argparse
from pathlib import Path
from typing import Any

try:
    from .iter_documents import iter_documents  # package relative
except Exception:  # pragma: no cover
    # Fallback if run as a loose script
    from iter_documents import iter_documents  # type: ignore


def _human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("Document iteration client")
    p.add_argument("root", help="Root directory to scan")
    p.add_argument("--limit", type=int, default=None, help="Limit number of documents returned")
    p.add_argument("--export", type=str, default=None, help="Write all docs as JSON list to file")
    p.add_argument("--stats", action="store_true", help="Print summary stats")
    p.add_argument("--show-metadata", action="store_true", help="Print metadata for each document")
    p.add_argument("--filter-ext", type=str, nargs="*", help="Restrict to these extensions (e.g. .md .py)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser()
    if not root.exists():
        print(f"[error] Root path does not exist: {root}", file=sys.stderr)
        return 2

    all_docs = iter_documents(root)

    if args.filter_ext:
        allow = {ext.lower() for ext in args.filter_ext}
        all_docs = [d for d in all_docs if Path(str(d.metadata.get("source", ""))).suffix.lower() in allow]

    if args.limit is not None:
        all_docs = all_docs[: args.limit]

    verbose = os.getenv("AI_IDE_DOC_VERBOSE", "0") == "1"
    if verbose:
        for i, d in enumerate(all_docs, 1):
            print(f"[doc {i}] {d.metadata.get('source')} (id={d.metadata.get('id')})")

    if args.show_metadata:
        for d in all_docs:
            meta_str = json.dumps(d.metadata, ensure_ascii=False)
            print(f"META {meta_str}")

    if args.stats:
        exts: dict[str, int] = {}
        size_total = 0
        for d in all_docs:
            src = str(d.metadata.get("source", ""))
            ext = Path(src).suffix.lower()
            exts[ext] = exts.get(ext, 0) + 1
            size_total += len(d.page_content.encode("utf-8", errors="ignore"))
        print("Documents:", len(all_docs))
        for k, v in sorted(exts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {k or '(no-ext)'}: {v}")
        print("Approx text size:", _human_size(size_total))

    if args.export:
        out_path = Path(args.export).expanduser()
        payload: list[dict[str, Any]] = [
            {"content": d.page_content, "metadata": d.metadata} for d in all_docs
        ]
        try:
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[ok] Exported {len(payload)} documents to {out_path}")
        except Exception as exc:  # pragma: no cover
            print(f"[error] Failed to export: {exc}", file=sys.stderr)
            return 3

    # Print simple list when no other flag selected
    if not any([args.stats, args.export, args.show_metadata]):
        for d in all_docs:
            print(d.metadata.get("source"))

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
