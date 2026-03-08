from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _parse_bool_flag(value: str | None) -> bool | None:
    """Parse common CLI bool-ish values; return None when omitted."""
    if value is None:
        return None
    s = str(value).strip().lower()
    return s in {"1", "true", "yes", "y", "on", "enable", "enabled", "autobuild"}


def _resolve_store_paths(
    kind: str,
    store_dir: str | None,
    manifest_file: str | None,
) -> tuple[str, str]:
    """Resolve inputs into (store_dir, manifest_file).

    - If store_dir looks like a filesystem path: use it.
    - Else interpret as store id/name under <pkg_root>/AppData.
    - If missing: default to memorydb=>VSM_3_Data, vectordb=>VSM_1_Data.
    """
    pkg_root = Path(__file__).resolve().parents[1]
    appdata = pkg_root / "AppData"

    if not store_dir:
        d = appdata / ("VSM_3_Data" if kind == "memorydb" else "VSM_1_Data")
        m = Path(manifest_file) if manifest_file else (d / "manifest.json")
        return str(d), str(m)

    raw = str(store_dir).strip()
    looks_like_path = raw.startswith(("/", "./", "../", "~")) or ("/" in raw) or ("\\" in raw)
    if looks_like_path:
        d = Path(os.path.abspath(os.path.expanduser(raw)))
        m = Path(manifest_file) if manifest_file else (d / "manifest.json")
        return str(d), str(m)

    if raw.isdigit():
        name = f"VSM_{raw}_Data"
    else:
        name = raw
        if not (name.startswith("VSM_") and name.endswith("_Data")):
            if name.startswith("VSM_"):
                name = f"{name}_Data"
            else:
                name = f"VSM_{name}_Data"
    d = appdata / name
    m = Path(manifest_file) if manifest_file else (d / "manifest.json")
    return str(d), str(m)


def _run(
    kind: str,
    query: str,
    k: int,
    *,
    store_dir: str | None = None,
    manifest_file: str | None = None,
    root_dir: str | None = None,
    autobuild: bool | None = None,
) -> dict[str, Any]:
    try:
        import importlib

        # Support both package mode and direct script execution.
        try:
            from .vstores import VectorStore  # type: ignore
        except ImportError:
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

        pkg_root = Path(__file__).resolve().parents[1]

        resolved_store_dir, resolved_manifest = _resolve_store_paths(kind, store_dir, manifest_file)
        Path(resolved_store_dir).mkdir(parents=True, exist_ok=True)
        mf = Path(resolved_manifest)
        if not mf.exists():
            mf.write_text("[]\n", encoding="utf-8")

        db = VectorStore(store_path=str(resolved_store_dir), manifest_file=str(resolved_manifest))

        do_autobuild = os.getenv("AI_IDE_VSTORE_AUTOBUILD", "0").strip() in {"1", "true", "True"}
        if autobuild is not None:
            do_autobuild = bool(autobuild)
        if do_autobuild:
            if root_dir:
                build_root = Path(root_dir)
            else:
                store_path = Path(resolved_store_dir)
                if kind == "memorydb" and store_path.name == "memorydb" and store_path.parent.name == "autobuild":
                    # Typical layout: .../VSM_3_Data/autobuild/memorydb -> index source is VSM_3_Data
                    build_root = store_path.parent.parent
                elif kind == "memorydb":
                    # Memory store defaults to its own data directory instead of full repo scan.
                    build_root = store_path
                else:
                    build_root = pkg_root
            db.build(str(build_root))

        result = db.query(query, k=int(k))
        return {"ok": True, "result": result}
    except BaseException as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alde.vdb_worker_cli")
    p.add_argument("kind", choices=["memorydb", "vectordb"], help="Which store to query")
    p.add_argument("query", help="Query text")
    p.add_argument("-k", type=int, default=5, help="Top-k")
    p.add_argument("--store_dir", type=str, default=None, help="Vector store dir path OR store id/name")
    p.add_argument("--manifest_file", type=str, default=None, help="manifest.json path (optional)")
    p.add_argument("--root_dir", type=str, default=None, help="Root directory to index when autobuild is enabled")
    p.add_argument("--autobuild", type=str, default=None, help="Override autobuild (1/0)")
    p.add_argument("--pretty", type=str, default="1", help="Pretty-print JSON output (1/0, default: 1)")
    args = p.parse_args(argv)

    autobuild_val = _parse_bool_flag(args.autobuild)
    pretty = bool(_parse_bool_flag(args.pretty))

    payload = _run(
        args.kind,
        args.query,
        int(args.k),
        store_dir=args.store_dir,
        manifest_file=args.manifest_file,
        root_dir=args.root_dir,
        autobuild=autobuild_val,
    )
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
