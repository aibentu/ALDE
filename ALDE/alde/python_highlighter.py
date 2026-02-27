
'''
***schreibe einen Vollständigen source code decoder für python3*** 


- Tokenization help for Python programs.
- tokenize(readline) is a generator that breaks a stream of bytes into
- Python tokens. It decodes the bytes according to PEP-0263 for
- determining source file encoding.
'''


from __future__ import annotations

import builtins

import io
import keyword
import sys
import token
import tokenize
from types import BuiltinFunctionType, BuiltinMethodType
from typing import Final

from PySide6.QtCore    import Qt
from PySide6.QtGui     import QColor, QFont, QTextCharFormat, QSyntaxHighlighter
from PySide6.QtWidgets import QApplication, QTextEdit


# --------------------------------------------------------------------------- #
#  Hilfs-Klasse für Farben / Schriftformat                                    #
# --------------------------------------------------------------------------- #
class _Fmt:
    @staticmethod
    def make(hex_color: str, *, bold: bool = False,
             italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(hex_color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt


# --------------------------------------------------------------------------- #
#  Highlighter                                                                #
# --------------------------------------------------------------------------- #
class VSDarkPythonHighlighter(QSyntaxHighlighter):
    """Token-basierter Python-Highlighter mit VS-Code-Dark-Farben"""

    # Farbpalette (VS Code › Dark+)
    C_KEYWORD:   Final = "#569CD6"
    C_BUILTIN:   Final = "#4FC1FF"
    C_CLASS:     Final = "#4EC9B0"
    C_FUNCTION:  Final = "#DCDCAA"
    C_NUMBER:    Final = "#B5CEA8"
    C_STRING:    Final = "#CE9178"
    C_COMMENT:   Final = "#6A9955"
    C_DECORATOR: Final = "#C586C0"
    C_OPERATOR:  Final = "#D4D4D4"
    C_BRACE:     Final = "#C8C8C8"
    C_VARIABLE:  Final = "#9CDCFE"

    def __init__(self, parent):
        super().__init__(parent)

        # QTextCharFormat-Objekte vorbereiten
        self.fmt_kw      = _Fmt.make(self.C_KEYWORD,   bold=True)
        self.fmt_builtin = _Fmt.make(self.C_BUILTIN)
        self.fmt_number  = _Fmt.make(self.C_NUMBER)
        self.fmt_string  = _Fmt.make(self.C_STRING)
        self.fmt_comment = _Fmt.make(self.C_COMMENT,   italic=True)
        self.fmt_oper    = _Fmt.make(self.C_OPERATOR)
        self.fmt_brace   = _Fmt.make(self.C_BRACE,     bold=True)
        self.fmt_var     = _Fmt.make(self.C_VARIABLE)
        self.fmt_deco    = _Fmt.make(self.C_DECORATOR)
        self.fmt_self    = _Fmt.make(self.C_VARIABLE, bold=True, italic=True)

        # Lookup-Mengen für Geschwindigkeit
        self._keywords  = set(keyword.kwlist)
        self._builtins  = {
            name for name, obj in vars(builtins).items()
            if isinstance(obj, (BuiltinFunctionType, BuiltinMethodType, type))
        }

    # --------------------------------------------------------------------- #
    def _apply(self, start: int, length: int, fmt: QTextCharFormat) -> None:
        """Zentrale Helfer-Methode zum Färben."""
        self.setFormat(start, length, fmt)

    # --------------------------------------------------------------------- #
    def highlightBlock(self, text: str) -> None:  # noqa: C901 – bewusst lang
        """Wird von Qt für **jede** Zeile aufgerufen."""
        if not text:
            return

        # tokenize benötigt ein abschließendes NL
        stream = io.StringIO(text + "\n")

        try:
            for tok in tokenize.generate_tokens(stream.readline):
                ttype, tstring, (row, col), _, _ = tok
                length = len(tstring)

                if ttype == token.NUMBER:
                    self._apply(col, length, self.fmt_number)

                elif ttype == token.STRING:
                    self._apply(col, length, self.fmt_string)

                elif ttype == tokenize.COMMENT:
                    self._apply(col, length, self.fmt_comment)

                elif ttype == token.OP:
                    if tstring in "()[]{}":
                        self._apply(col, length, self.fmt_brace)
                    else:
                        self._apply(col, length, self.fmt_oper)

                elif ttype == token.NAME:
                    if text.lstrip().startswith("@") and col == text.find("@") + 1:
                        self._apply(col, length, self.fmt_deco)
                    elif tstring in ("self", "cls"):
                        self._apply(col, length, self.fmt_self)
                    elif tstring in self._keywords:
                        self._apply(col, length, self.fmt_kw)
                    elif tstring in self._builtins:
                        self._apply(col, length, self.fmt_builtin)
                    else:
                        self._apply(col, length, self.fmt_var)
                # NEWLINE / INDENT / DEDENT werden ignoriert
        except tokenize.TokenError:
            # unvollständige letzte Zeile → einfach übergehen
            pass


# --------------------------------------------------------------------------- #
#  Demo-GUI                                                                   #
# --------------------------------------------------------------------------- #
DEMO_CODE: Final = r'''
"""
Dieser Demo-Text zeigt, dass Variablen (foo, bar),
self/cls, Dekoratoren, Klammern und mehr korrekt
hervorgehoben werden.
"""

from __future__ import annotations
from hashlib import sha1
from pathlib import Path
from typing import Iterable, Sequence
from get_path import GetPath

from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    PythonLoader,
)
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
        loader =TextLoader(str(path))
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
'''


def main() -> None:
    app = QApplication(sys.argv)

    editor = QTextEdit()
    editor.setWindowTitle("VS-Code-Dark Python Highlighter (PySide6)")
    editor.setFont(QFont("Consolas", 11))
    editor.setLineWrapMode(QTextEdit.NoWrap)

    # Highlighter aktivieren
    VSDarkPythonHighlighter(editor.document())
    editor.setPlainText(DEMO_CODE)

    editor.resize(900, 600)
    editor.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()