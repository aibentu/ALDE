from __future__ import annotations
from hashlib import sha1
from pathlib import Path
from typing import Iterable, Sequence, TYPE_CHECKING

try:
    from .get_path import GetPath
except ImportError as e:  # allow running directly from the repository root
    msg = str(e)
    if "no known parent package" in msg or "attempted relative import" in msg:
        from get_path import GetPath
    else:
        raise

if TYPE_CHECKING:
    from langchain_core.documents import Document

__all__ = ["iter_documents"]


# ------------------------------- helpers ----------------------------------

SKIP_DIRS: set[str] = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "venv",
    ".venv",
    "site-packages",
}

TEXT_SUFFIXES: tuple[str, ...] = (
    ".txt",
    ".md",
    ".rst",
    ".yaml",
    ".yml",
    ".toml",
)

def _in_skipped_dir(p: Path) -> bool:
    parts = set(p.parts)
    return any(name in parts for name in SKIP_DIRS)

def _content_id(source: str ,*, page: int | str , content: str) -> str:
    h = sha1()
    h.update(source.encode("utf-8", errors="ignore"))
    if page is not None:
        h.update(f"|page={page}".encode("utf-8"))
    h.update(b"|")
    h.update(content.encode("utf-8", errors="ignore"))
    return h.hexdigest()

def _load_text(path: Path) -> list[Document]:
    """Load a PDF into page Documents using PyPDFLoader.        "industry": "str - Branche/Sektor",

    Returns only non-empty pages and enriches metadata (titel, id, applied).
    """
    try:
        from langchain_community.document_loaders import TextLoader

        loader = TextLoader(str(path))
        docs = loader.load()
    except Exception:
        return []
    out: list[Document] = []
    for d in docs:
        if d.page_content and d.metadata.get("source"):
            out.append(d)
    return out

def _load_pdf(path: Path) -> list[Document]:
    """Load a single text-like file with encoding detection.
    Uses PythonLoader for .py, TextLoader otherwise.
    """
    try:
        from langchain_community.document_loaders import PyPDFLoader

        loader = PyPDFLoader(str(path))
        docs = loader.load()
    except Exception:
        return []
    return docs

def _apply_metadata(doc: list[Document], key: list | str | dict, val: str | int | dict | list) -> list[Document]:
    """apply metadata key-value pairs to documents. The function is also a generic validation
      tool. It applyes sha1 hashes to metadata keys including long context (Text) and keys You can you 
      eg to implement Block-Chain Technology or if you change the function you can implement
      semantic similarity search tools per key-value pair.With the inherited methods it also usefull
      to ad Vectorindexing to your databases eg SQL, NoSQL or others.
      """
    docs: list[Document] = []
    ids: list[str] = []
    key = key if isinstance(key, list) else [key]
    val = val if isinstance(val, list) else [val]

    for k, v in zip(key, val):
        for d in doc:  # FIX: war `docs` (leere Liste), muss `doc` (Parameter) sein
            d.metadata[k] = _content_id(
                source=str(d.metadata.get("source", "")),
                page=d.metadata.get("page", None),
                content=d.page_content
            )
            
        for d in doc:  # FIX: war `docs` (leere Liste), muss `doc` (Parameter) sein
            d.metadata[k] = _content_id(
                source=str(d.metadata.get("source", "")),
                page=d.metadata.get("page", None),
                content=d.page_content
            )
            if v not in ids:
                ids.append(v)
            docs.append(d)
            print('\n\n',120*'-','\n',d.metadata['page'],"-","",d.metadata['p_id'],'\n',d.metadata['source'][-50:],'\n\n',120*'-','\n',120*'-','\n',d.page_content,'\n',120*'-','\n')
    
    return docs  # FIX: war unreachable due to `return print(...)`

def _iter_paths(root: Path, suffixes: Sequence[str]) -> Iterable[Path]:
    seen: set[Path] = set()  # FIX: use set for O(1) lookup
    for p in root.rglob("*"):
        if p in seen:
            continue
        seen.add(p)
        if not p.is_file():                                
            continue
        if _in_skipped_dir(p):
            continue
        if p.suffix.lower() in suffixes or p.suffix.lower() == ".pdf" or p.suffix.lower() == ".py":
            print(p)
            yield p  # FIX: yield inside the loop, not outside

def iter_documents(root: str | Path) -> list[Document]:
    """Recursively load supported documents from a root directory."""
    root_path = Path(root).expanduser().resolve()
    docs: list[Document] = []

    for path in _iter_paths(root_path, TEXT_SUFFIXES):
        try:
            if path.suffix.lower() == ".pdf":
                print(f"Loading PDF: {path}")
                docs.extend(_load_pdf(path))
            else:
                docs.extend(_load_text(path))
        except Exception as e:
            print(f"Skipping {path}: {e}")
            continue                                        
    
    return docs

# --- Test code ---
if __name__ == "__main__":
    this_dir = Path(__file__).resolve().parent.parent
    doc_path = this_dir / "AppData" / "VSM_4_Data" / "memorydb"
    
    print(f"Scanning: {doc_path}")
    if not doc_path.exists():
        print(f"ERROR: Path does not exist: {doc_path}")
    else:
        docs = iter_documents(doc_path)
        print(f"Loaded {len(docs)} documents")  # FIX: war unter falscher if-Bedingung
        
        if docs:
            result = _apply_metadata(docs, key=["p_id"], val=["source"])
            print(f"#docs after metadata: {len(result)}")
        else:
            print("No documents loaded")