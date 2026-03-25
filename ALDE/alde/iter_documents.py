from __future__ import annotations
import os
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
    ".micromamba",
    ".tools",
    "AppData",
    "ai_ide_v1756.egg-info",
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

DEFAULT_DOC_SUFFIXES: tuple[str, ...] = (*TEXT_SUFFIXES, ".pdf", ".py")

DOC_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "text": TEXT_SUFFIXES,
    "txt": (".txt",),
    "md": (".md",),
    "markdown": (".md",),
    "rst": (".rst",),
    "yaml": (".yaml", ".yml"),
    "yml": (".yml",),
    "toml": (".toml",),
    "pdf": (".pdf",),
    "py": (".py",),
    "python": (".py",),
    "json": (".json",),
}

def _in_skipped_dir(p: Path) -> bool:
    parts = set(p.parts)
    return any(name in parts for name in SKIP_DIRS)


def _as_path_list(root: str | Path | Sequence[str | Path] | None, roots: Sequence[str | Path] | None = None) -> list[Path]:
    items: list[str | Path] = []
    if root is not None:
        if isinstance(root, (str, Path)):
            items.append(root)
        else:
            items.extend(root)
    if roots is not None:
        items.extend(roots)
    return [Path(item).expanduser().resolve() for item in items]


def _normalize_doc_types(doc_types: str | Sequence[str] | None) -> set[str]:
    if doc_types is None:
        return set(DEFAULT_DOC_SUFFIXES)

    if isinstance(doc_types, str):
        raw_items = [doc_types]
    else:
        raw_items = list(doc_types)

    suffixes: set[str] = set()
    for raw_item in raw_items:
        item = str(raw_item).strip().lower()
        if not item:
            continue
        if item in DOC_TYPE_ALIASES:
            suffixes.update(DOC_TYPE_ALIASES[item])
            continue
        if not item.startswith("."):
            item = f".{item}"
        suffixes.add(item)
    return suffixes


def _normalize_patterns(patterns: str | Sequence[str] | None) -> list[str]:
    if patterns is None:
        return []
    if isinstance(patterns, str):
        values = [patterns]
    else:
        values = list(patterns)
    return [value.strip() for value in values if str(value).strip()]


def _relative_file_depth(root: Path, path: Path) -> int:
    try:
        relative_parent = path.parent.relative_to(root)
    except ValueError:
        return 0
    if relative_parent == Path("."):
        return 0
    return len(relative_parent.parts)


def _matches_patterns(path: Path, root: Path, patterns: Sequence[str]) -> bool:
    if not patterns:
        return True

    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)

    for pattern in patterns:
        candidate_patterns = [pattern]
        if pattern.startswith("**/"):
            candidate_patterns.append(pattern[3:])
        if any(relative.match(candidate) or Path(path.name).match(candidate) for candidate in candidate_patterns):
            return True
    return False


def _is_supported_path(path: Path, root: Path, suffixes: set[str], patterns: Sequence[str], max_depth: int | None) -> bool:
    if not path.is_file():
        return False
    if _in_skipped_dir(path):
        return False
    if suffixes and path.suffix.lower() not in suffixes:
        return False
    if max_depth is not None and _relative_file_depth(root, path) > max_depth:
        return False
    return _matches_patterns(path, root, patterns)

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


def _iter_paths(
    roots: Sequence[Path],
    suffixes: set[str],
    patterns: Sequence[str],
    recursive: bool,
    max_depth: int | None,
) -> Iterable[Path]:
    seen: set[Path] = set()

    for root in roots:
        if not root.exists():
            continue

        if root.is_file():
            if root not in seen and _is_supported_path(root, root.parent, suffixes, patterns, 0):
                seen.add(root)
                yield root
            continue

        for current_root, dirnames, filenames in os.walk(root):
            current_dir = Path(current_root)
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]

            depth = 0
            if current_dir != root:
                depth = len(current_dir.relative_to(root).parts)

            if not recursive or (max_depth is not None and depth >= max_depth):
                dirnames[:] = []

            for filename in filenames:
                path = current_dir / filename
                if path in seen:
                    continue
                if not _is_supported_path(path, root, suffixes, patterns, max_depth):
                    continue
                seen.add(path)
                yield path
def iter_documents(
    root: str | Path | Sequence[str | Path] | None = None,
    *,
    roots: Sequence[str | Path] | None = None,
    doc_types: str | Sequence[str] | None = None,
    patterns: str | Sequence[str] | None = None,
    recursive: bool = True,
    max_depth: int | None = None,
) -> list[Document]:
    """Load supported documents from one or more files or directories.

    Args:
        root: Single path or multiple paths to scan.
        roots: Additional paths to scan. Useful for callers that prefer a dedicated multi-root argument.
        doc_types: Optional extension filter, e.g. ".md", "pdf", ["py", ".json"].
        patterns: Optional glob-style path filters, e.g. "**/*.md" or ["docs/**/*.md", "*.pdf"].
        recursive: Whether to recurse into subdirectories.
        max_depth: Maximum directory depth relative to each root. `0` means only the root directory itself.
    """
    root_paths = _as_path_list(root, roots)
    if not root_paths:
        raise ValueError("iter_documents requires at least one root path")
    suffixes = _normalize_doc_types(doc_types)
    normalized_patterns = _normalize_patterns(patterns)
    docs: list[Document] = []

    for path in _iter_paths(root_paths, suffixes, normalized_patterns, recursive, max_depth):
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