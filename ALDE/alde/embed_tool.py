from __future__ import annotations
"""Minimal embedding/FAISS CLI built on iter_documents.

Commands:
  build   Build or extend index from a root directory
  query   Run semantic search
  stats   Show index statistics
  wipe    Delete index directory
  dump    Export all stored documents (raw) to JSON

Examples:
    python -m alde.embed_tool build ./project
    python -m alde.embed_tool query ./project "vector store design" -k 5
    python -m alde.embed_tool stats ./project
    python -m alde.embed_tool dump ./project out.json

Environment flags:
  EMBED_VERBOSE=1  -> progress output per stage
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List

try:
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except Exception as exc:  # pragma: no cover
    print("[error] Required langchain/FAISS dependencies missing:", exc, file=sys.stderr)
    raise SystemExit(5)

#try:
 ##   from .iter_documents import iter_documents  # package relative
#except Exception:  # pragma: no cover
 #   from iter_documents import iter_documents  # type: ignore

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_INDEX_DIR = "AppData/simple_index"


def _verbose(msg: str) -> None:
    if os.getenv("EMBED_VERBOSE", "0") == "1":
        print(f"[embed] {msg}")


def _load_index(index_dir: Path, embeddings: HuggingFaceEmbeddings) -> FAISS | None:
    if not index_dir.exists():
        return None
    faiss_file = index_dir / "index.faiss"
    if not faiss_file.exists():
        return None
    try:
        _verbose("Loading existing FAISS index")
        return FAISS.load_local(str(index_dir), embeddings, allow_dangerous_deserialization=True)
    except Exception as exc:  # pragma: no cover
        print(f"[warn] Could not load index: {exc}")
        return None


def _chunk_documents(docs: List[Any], size: int, overlap: int) -> List[Any]:
    if not docs:
        return []
    try:
        splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap, length_function=len)
        return splitter.split_documents(docs)
    except Exception:  # pragma: no cover
        # Fallback: naive slicing
        out: List[Any] = []
        for d in docs:
            text = d.page_content
            for i in range(0, len(text), size):
                segment = text[i : i + size]
                new_meta = dict(d.metadata)
                new_meta["chunk_offset"] = i
                out.append(type(d)(page_content=segment, metadata=new_meta))
        return out


def build(root: Path, index_dir: Path, model: str, chunk_size: int, chunk_overlap: int) -> None:
    embeddings = HuggingFaceEmbeddings(model_name=model)
    docs = iter_documents(root)
    _verbose(f"Loaded {len(docs)} base documents")
    chunks = _chunk_documents(docs, chunk_size, chunk_overlap)
    _verbose(f"Chunked into {len(chunks)} segments")

    index_dir.mkdir(parents=True, exist_ok=True)
    store = _load_index(index_dir, embeddings)
    if store is None:
        if not chunks:
            print("[info] No documents to build index.")
            return
        store = FAISS.from_documents(chunks, embeddings)
        _verbose("Created new index")
    else:
        if chunks:
            store.add_documents(chunks)
            _verbose("Extended existing index")
        else:
            _verbose("No new chunks to add")
    store.save_local(str(index_dir))
    print(f"[ok] Index saved at {index_dir}")


def query(root: Path, index_dir: Path, model: str, text: str, k: int) -> None:
    embeddings = HuggingFaceEmbeddings(model_name=model)
    store = _load_index(index_dir, embeddings)
    if store is None:
        print("[error] Index not found. Run build first.")
        return
    results = store.similarity_search_with_score(text, k=k)
    if not results:
        print("[info] No hits.")
        return
    for rank, (doc, score) in enumerate(results, 1):
        src = doc.metadata.get("source")
        title = doc.metadata.get("titel") or (Path(str(src)).name if src else "(no-title)")
        print(f"{rank:>2}. score={float(score):.4f} title={title} source={src}")


def stats(root: Path, index_dir: Path, model: str) -> None:
    embeddings = HuggingFaceEmbeddings(model_name=model)
    store = _load_index(index_dir, embeddings)
    if store is None:
        print("[info] No index present.")
        return
    count = store.index.ntotal
    print(f"Vectors: {count}")
    # Show ext distribution from stored docs
    ext_counts: dict[str, int] = {}
    for doc in store.docstore._dict.values():
        src = str(doc.metadata.get("source", ""))
        ext = Path(src).suffix.lower()
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
    if ext_counts:
        print("Extension distribution:")
        for ext, num in sorted(ext_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {ext or '(none)'}: {num}")


def dump(root: Path, index_dir: Path, model: str, out_file: Path) -> None:
    embeddings = HuggingFaceEmbeddings(model_name=model)
    store = _load_index(index_dir, embeddings)
    if store is None:
        print("[error] Index not found.")
        return
    payload = [
        {"content": d.page_content, "metadata": d.metadata}
        for d in store.docstore._dict.values()
    ]
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] Dumped {len(payload)} documents to {out_file}")


def wipe(index_dir: Path) -> None:
    if not index_dir.exists():
        print("[info] Nothing to wipe.")
        return
    for p in index_dir.iterdir():
        if p.is_file():
            p.unlink(missing_ok=True)
    print(f"[ok] Wiped {index_dir}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("Lightweight embedding tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("root", help="Root directory to scan")
        sp.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="Directory to store FAISS index")
        sp.add_argument("--model", default=DEFAULT_MODEL, help="Sentence embedding model name")

    p_build = sub.add_parser("build", help="Build or extend index")
    add_common(p_build)
    p_build.add_argument("--chunk-size", type=int, default=1000)
    p_build.add_argument("--chunk-overlap", type=int, default=100)

    p_query = sub.add_parser("query", help="Run semantic search")
    add_common(p_query)
    p_query.add_argument("text", help="Query text")
    p_query.add_argument("-k", type=int, default=5, help="Top K results")

    p_stats = sub.add_parser("stats", help="Show index stats")
    add_common(p_stats)

    p_dump = sub.add_parser("dump", help="Export stored docs to JSON")
    add_common(p_dump)
    p_dump.add_argument("out", help="Output JSON file")

    p_wipe = sub.add_parser("wipe", help="Delete index directory")
    p_wipe.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)

    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    cmd = args.cmd
    index_dir = Path(args.index_dir).expanduser().resolve()

    if cmd == "build":
        build(Path(args.root), index_dir, args.model, args.chunk_size, args.chunk_overlap)
    elif cmd == "query":
        query(Path(args.root), index_dir, args.model, args.text, args.k)
    elif cmd == "stats":
        stats(Path(args.root), index_dir, args.model)
    elif cmd == "dump":
        dump(Path(args.root), index_dir, args.model, Path(args.out).expanduser())
    elif cmd == "wipe":
        wipe(index_dir)
    else:  # pragma: no cover
        print("[error] Unknown command")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover          
    raise SystemExit(main())

#with open(path,'r') as f:
#   jsf =  sys.stdin.read(f)
#print(jsf)