from __future__ import annotations
from importlib import metadata

from sqlalchemy import literal

#  August 2025
# Maintainer contact: see repository README.
#  Module: vstores.py
# ───────────────────────────── Imports ──────────────────────────────

import json
import sys
from pathlib import Path
from typing import Iterable, List, Set, Dict, Any
import os
import time
import logging
from datetime import datetime
from dataclasses import dataclass, field

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from contextlib import suppress
from langchain_core.documents import Document
from langchain_community.document_loaders import (  # add PyPDFLoader + custom loader
    PyPDFLoader,
    TextLoader,
    PythonLoader,
    DirectoryLoader
)
try:
    from .embed_tool import build  # type: ignore
except Exception:
    from embed_tool import build  # type: ignore

try:
    from . import torch_init  # type: ignore
except Exception:
    import torch_init  # type: ignore

try:
    from .get_path import GetPath  # type: ignore
except ImportError as e:
    msg = str(e)
    if "no known parent package" in msg or "attempted relative import" in msg:
        from get_path import GetPath  # type: ignore
    else:
        raise
# ───────────────────────────── Modul-Variablen ─────────────────────────────
__all__ = ["VectorStore"]  # stellt sicher, dass nur das Public-API exportiert wird
# ─────────────────────── Konfigurations-Konstanten ──────────────────────
# Ordner, der indiziert wird. Kann beim CLI-Aufruf über --path überschrieben werden.
DEFAULT_PROJECT_ROOT = GetPath().get_path(parg = f"{__file__}", opt = 'p')
# Ablageort für Index + Metadaten (FAISS benötigt ein Verzeichnis, kein File)
FAISS_INDEX_PATH:GetPath = GetPath()._parent(parg = f"{__file__}") + f"AppData/VSM_0_Data"

if not os.path.isdir(FAISS_INDEX_PATH):
    os.makedirs(FAISS_INDEX_PATH, exist_ok=True)

# Hugging-Face Modell
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Text-Chunk Parameter
CHUNK_SIZE = 1_000
CHUNK_OVERLAP = 150
# Trefferzahl für query()
DEFAULT_TOP_K = 50
# Datei, in der bereits indizierte Quell­pfade gespeichert werden
MANIFEST_FILE:GetPath = GetPath()._parent(parg = f"{__file__}") + f"AppData/VSM_0_Data/manifest.json"

# Embeddings device selection.
# - Set `AI_IDE_EMBEDDINGS_DEVICE=cuda` (or `cuda:0`) to force GPU.
# - Set `AI_IDE_EMBEDDINGS_DEVICE=cpu` to force CPU.
# - Default: `auto` (use GPU if available, else CPU).
EMBEDDINGS_DEVICE = os.getenv("AI_IDE_EMBEDDINGS_DEVICE", "auto")


def _select_embeddings_device() -> str:
    desired = (EMBEDDINGS_DEVICE or "auto").strip()
    if desired and desired.lower() != "auto":
        return desired

    # Auto: prefer CUDA if available.
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"

# Use multithreading only when explicitly enabled; some native stacks (torch/faiss)
# can crash when combined with aggressive multithreading.
USE_MULTITHREADING = os.getenv("AI_IDE_VSTORE_MULTITHREAD", "0").strip() in {"1", "true", "True"}

# Retrieval tuning
VSTORE_DEDUP = os.getenv("AI_IDE_VSTORE_DEDUP", "1").strip() in {"1", "true", "True"}
VSTORE_RERANK = os.getenv("AI_IDE_VSTORE_RERANK", "1").strip() in {"1", "true", "True"}
VSTORE_RERANK_METHOD = os.getenv("AI_IDE_VSTORE_RERANK_METHOD", "mmr").strip().lower()
VSTORE_RERANK_MODEL = os.getenv(
    "AI_IDE_VSTORE_RERANK_MODEL",
    # multilingual + reasonably small
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
)
VSTORE_FETCH_K = int(os.getenv("AI_IDE_VSTORE_FETCH_K", "0") or 0)  # 0 => auto
VSTORE_MAX_CONTENT_CHARS = int(os.getenv("AI_IDE_VSTORE_MAX_CONTENT_CHARS", "2000") or 2000)
VSTORE_INCLUDE_METADATA = os.getenv("AI_IDE_VSTORE_INCLUDE_METADATA", "1").strip() in {"1", "true", "True"}

_CROSS_ENCODER = None


def _get_cross_encoder():
    global _CROSS_ENCODER
    if VSTORE_RERANK_METHOD != "crossencoder":
        return None
    if _CROSS_ENCODER is not None:
        return _CROSS_ENCODER
    try:
        from sentence_transformers import CrossEncoder

        _CROSS_ENCODER = CrossEncoder(VSTORE_RERANK_MODEL, device=_select_embeddings_device())
    except Exception:
        _CROSS_ENCODER = None
    return _CROSS_ENCODER
# ─────────────────────── Performance Monitoring ───────────────────────


# ─────────────────────── Metadata-Normalisierung ───────────────────────
def _norm_source(value: object) -> str:
    """Normalisiert Document.metadata['source'] zu einem hashbaren String.

    Einige Loader liefern strukturierte Werte (z.B. dict) als `source`.
    Diese sind nicht hashbar und brechen Set/Dict-Operationen.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return str(value)
    return str(value)


def _safe_title_from_source(source: str) -> str:
    with suppress(Exception):
        return Path(source).name
    return (source or "unknown")

# ─────────────────────── Hilfs-/Utility-Funktionen ───────────────────────
def _log(e:str=None, msg:str="") -> None:
        """'Einfaches Konsolen-Logging."""
        #print(f"{e}\n[VectorStoreProject]{msg}\n")


class SafeTextLoader(TextLoader):
    """
    Erweiterung von LangChains TextLoader, die *jedes* Encoding akzeptiert.
    Fehlschläge beim Lesen einzelner Dateien werden nicht propagiert, sondern
    lediglich protokolliert.  Dadurch bricht der Build-Vorgang nie wegen
    UnicodeDecodeError ab.
    """
    def load(self) -> List[Document]:                           # type: ignore[override]
        try:
            return super().load()
        except Exception as err:
            _log(err, f"Überspringe Datei (Encoding-Fehler): {self.file_path}")
            return []

def _load_json(path) -> List[Document]:
        """Return the list of text snippets contained in *path*."""
        is_json = Path(f"{path} **/*.json")
        if not is_json.is_file():
                _log("", f"File is not a JSON: {path}")
                return []
        else:
            with open(is_json ,"r", encoding="utf-8") as fh:
                data = json.load(fh)
        
        documents = []
        for idx, item in enumerate(data):
            # Erstelle eindeutigen Source-Key mit Index und Content-Hash
            content_str = str(item["content"])
            source_key = hex(hash(f"{item['role']}{item['thread-id']}{item['time']}{item['date']}{idx}{content_str}"))
            
            doc = Document(
                page_content=content_str,
                metadata={
                    "source-key": str(source_key),
                    "role": item["role"],
                    "message-id": item["message-id"],
                    "thread-id": item["thread-id"], 
                    "time": item["time"],
                    "date": item["date"],
                    "index": idx,
                    "vector": item.get("vec", None),
                    "id": item.get("id", None)
                }
            )
            documents.append(doc)
            # print(f"JSON Doc {idx}: source={source_key}")
        
        return documents
# ──────────────────────────────────────────────────────────────────────────    
    # 2) HELPER: robuster PDF-Loader  ──────────────────────────────────────────
def _load_pdf(path: str | Path) -> list[Document]:
    """
    Liefert eine Liste Document-Objekte für *path*.

    • 1. Versuch:  PyPDFLoader  (schnell, nutzt Text-Layer des PDF)
    • 2. Fallback: UnstructuredPDFLoader mit OCR
                   (wenn PyPDF keine verwertbaren Texte liefert)
    
    OCR-Sprache: Deutsch (deu) für bessere Texterkennung bei deutschen PDFs.
    Tesseract muss mit deutschen Sprachdaten installiert sein:
        sudo apt install tesseract-ocr tesseract-ocr-deu
    """
    _log("", f"Versuche PDF zu laden: {path}")
    docs = None  # Ensure docs is always defined
    # --- 1) PyPDFLoader ---------------------------------------------------
    try:
        docs = PyPDFLoader(str(path)).load()
        docs = [d for d in docs if d.page_content.strip()]
        for d in docs:
            d.metadata["source"] = str(path)
            d.metadata["titel"] = Path(path).name
            d.metadata['applied']  = 'no'
            d.metadata['id']       = hex(hash(f"{d.metadata['source']}{d.page_content[:100]}"))
            #print(f'PDF Doc: source= {d.metadata["source"]} titel= {d.metadata["titel"]} id= {d.metadata["id"]} applied= {d.metadata["applied"]}')



           
        if docs:                       # Erfolg → sofort zurück
                _log("", f"✓ PDF erfolgreich mit PyPDFLoader geladen: {path} ({len(docs)} Seiten)")
                # Zeige ersten Text-Ausschnitt für Debugging
                _log("", f"  Preview: {preview}...")

                return docs
        #else:
         #   _log("", f"⚠ PyPDFLoader fand keine Textinhalte in: {path}")
    except Exception as e:

    # --- 2) Fallback: OCR -------------------------------------------------
            if docs:                       # Erfolg → sofort zurück
              _log("", f"✓ PDF erfolgreich mit PyPDFLoader geladen: {path} ({len(docs)} Seiten)")
            # Zeige ersten Text-Ausschnitt für Debugging
            preview = docs[0].page_content[:200].replace('\n', ' ')
        
            if docs:
        
              _log("", f"✓ OCR-Fallback erfolgreich für PDF: {path} ({len(docs)} Elemente)")
           # Zeige ersten Text-Ausschnitt für Debugging
           # preview = docs[0].page_content[:200].replace('\n', ' ')
           #_log("", f"  Preview: {preview}...")
        
            return docs
# ──────────────────────────────────────────────────────────────────────────
# 3)  _iter_documents  (komplett ersetzen)  
def _iter_documents(root: str | Path) -> list[Document]:
    """
    Traversiert *root* rekursiv und erzeugt LangChain-Document-Objekte für

        • *.py                 → PythonLoader
    _log("", f"✗ PDF übersprungen (kein Text extrahierbar): {path}")
        • *.pdf                → PyPDFLoader;  Fallback: OCR

    Binäre / kaputte Dateien werden stumm übersprungen, damit der
    Vector-Store-Build niemals abbricht.
    """
    root = Path(root).expanduser().resolve()
    docs: list[Document] = []

    # Verzeichnisse die übersprungen werden sollen (normalerweise keine relevanten Dokumente)
    SKIP_DIRS ={
        'venv', '.venv', '__pycache__', '.git', 'node_modules','venv/lib/python3.13/site-packages'
        'site-packages', '.pytest_cache', '.mypy_cache',
        'matplotlib/mpl-data/images', 
        } # matplotlib icons - meist nur Grafiken ohne Text
    

    def should_skip_path(path: Path) -> bool:
        """Prüft ob ein Pfad übersprungen werden soll"""
        path_str = str(path)  
        return any( skip_dir  in path_str for skip_dir in SKIP_DIRS)
        


    # 1) ------------ Python-Quelltexte -----------------------------------
    py_loader = DirectoryLoader(
        str(root),
        glob="*.py",
        loader_cls=PythonLoader,
        use_multithreading=USE_MULTITHREADING,
        show_progress=False,
    )
    py_docs = py_loader.load()
    for d in py_docs:
        d
        d.metadata["source"] = _norm_source(d.metadata.get("source"))
        d.metadata["titel"] = _safe_title_from_source(d.metadata["source"])
        d.metadata['id'] = hex(hash(f"{d.metadata['source']}{d.page_content[:100]}"))
    docs.extend(py_docs)
    

    # 2) ------------ Reine Textformate -----------------------------------
    text_patterns = (
        "**/*.txt", "**/*.md", "**/*.rst",
        "**/*.yaml", "**/*.yml",
        "**/*.sqlite", "**/*.sqlite3", "**/*.toml",                                 
    )
    for pattern in text_patterns:
        for path in root.rglob(pattern):
            if should_skip_path(path):
                continue
            with suppress(Exception):                      # Encoding-Fehler ignorieren
                t_loader = SafeTextLoader(str(path), autodetect_encoding=True)
                dokument = t_loader.load()
                for d in dokument:
                    d.metadata["source"] = str(path)
                    d.metadata["titel"] = path.name
                    d.metadata['id'] = hex(hash(f"{d.metadata['source']}{d.page_content[:100]}"))
                docs.extend(dokument)
    # 2) ------------ Reine Textformate -----------------------------------
   
    

    # 2.1) ------------ JSON-Dateien ---------------------------------------`
    docs.extend(_load_json(root))
    # 3) ------------ PDF-Dateien  (mit robustem Loader) ------------------
    pdf_count = 0
    pdf_success_count = 0
    for pdf_path in root.rglob("*.pdf"):
        if should_skip_path(pdf_path):
            # _log("", f"Überspringe PDF (ausgeschlossenes Verzeichnis): {pdf_path}")
            continue
            
        pdf_count += 1
        pdf_docs = _load_pdf(pdf_path)
        if pdf_docs:
            docs.extend(pdf_docs)
            pdf_success_count += 1
            _log("", f"✓ PDF indexiert: {pdf_path} ({len(pdf_docs)} Dokumente)")
    
    _log("", f"PDF-Verarbeitung: {pdf_success_count}/{pdf_count} erfolgreich")

    # 4) ------------ Duplikate entfernen ---------------------------------
    unique: dict[str, Document] = {}
    for d in docs:
        d.metadata["source"] = _norm_source(d.metadata.get("source"))
        unique.setdefault(str(d.metadata["source"]), d)
        #print(d.metadata["source"])     # Quelle als Key
    
    print("", f"Dokumente vor Duplikat-Entfernung: {len(docs)}")
    print("", f"Dokumente nach Duplikat-Entfernung: {len(unique)}")

    
    return list(unique.values())

# ───────────────────────── VectorStoreManager ──────────────────────────
class VectorStore():
    '''
    Verwaltet den kompletten Lebens­zyklus eines FAISS Vector-Stores.

    Methoden
    --------
    build(path: Path | str = DEFAULT_PROJECT_ROOT)
        Erstellt / aktualisiert den Index (inkrementell).

    query(text: str, k: int = DEFAULT_TOP_K)
        Führt eine Ähnlichkeitssuche durch und gibt Top-K Treffer auf der Konsole aus.

    wipe()
        Löscht Index + Manifest (für Neustart oder Debugging).
    '''
    # Temporärer Speicher für Dokumente
    # ------------------------------------------------------------
    doc_mem: dict[str, list[Document]] = None
    _initialized: bool = False


    def __init__(self, store_path: str = None, manifest_file: str = None, enable_monitoring: bool = True) -> None:
        # Lazy initialization - don't load embeddings until needed
        self.embeddings = None
        self.store = None
        self.FAISS_INDEX_PATH = store_path if store_path else FAISS_INDEX_PATH
        self.MANIFEST_FILE = manifest_file if manifest_file else MANIFEST_FILE
        self.manifest: Set[str] = self._load_manifest()
        # Performance Monitor
        self._initialized = False   

        if os.path.isdir(self.FAISS_INDEX_PATH):
            print(f'APP DIR: {self.FAISS_INDEX_PATH} OK')
        else:
            os.mkdir(self.FAISS_INDEX_PATH)
        # VectorStoreManager.doc_mem = self.load_directorys()
        print(f'ALL DOCS LENGTH: {len(self.manifest)}')
    # extract root paths from manifest and avoid duplicates
    def load_directorys(self) -> list:
        seen_path: list = [] # seen paths to avoid duplicates
        all_docs: list = []
        for d in self.manifest:
            project_path = GetPath().get_path(parg=d, opt='p')
            #print(f'Checking path: {project_path}')
            if project_path not in seen_path:
                #print(f'Adding path: {project_path}')
                seen_path.append(project_path)
                # extend() statt append() um flache Liste zu erhalten
                all_docs.extend(_iter_documents(project_path))
                #print(f'seen path: {len(seen_path)}')
        docs_injected = self.metadata_injection(all_docs)
        return docs_injected

    def _load_manifest(self) -> Set[str]:
        """
        Liest bereits indizierte File-Pfade aus manifest.json und gibt sie
        als Set[str] zurück. Uses instance-level MANIFEST_FILE.
        """
        if not Path(self.MANIFEST_FILE).exists():
            return set()
        try:
            with open(self.MANIFEST_FILE, encoding="utf-8") as fh:
                raw_items = json.load(fh)
                # Manifest may contain mixed numeric/string entries from older runs; normalize to str.
                return {str(item) for item in raw_items}
        except Exception as err:
            _log(err, "Warnung: manifest.json defekt – wird neu aufgebaut.")
            return set()

    def _save_manifest(self, paths: Iterable[str]) -> None:
        """Saves manifest using instance-level MANIFEST_FILE."""
        normalized = [str(p) for p in paths]
        data = json.dumps(sorted(normalized, key=str), indent=2, ensure_ascii=False)
        with open(self.MANIFEST_FILE, "w", encoding="utf-8") as f:
            f.write(data)

    def _initialize(self) -> None:
        """Lazy initialization of embeddings and store."""
        if self._initialized:
            return
        self._initialized = True
        # Embeddings (CPU/GPU automatisch via HF-Transformers)
        device = _select_embeddings_device()
        try:
            # langchain-huggingface forwards model_kwargs to sentence-transformers
            self.embeddings = HuggingFaceEmbeddings(
                model_name=MODEL_NAME,
                model_kwargs={"device": device},
            )
        except TypeError:
            # Backward-compat: older versions may not accept model_kwargs.
            self.embeddings = HuggingFaceEmbeddings(model_name=MODEL_NAME)
        device: str = str(self.embeddings._client.device)
        print(  f"HuggingFace-Embeddings fuer VectorStore geladen auf Gerät: {device}")

    def _load_faiss_store(self) -> None:
        # Persistierten Index laden – falls vorhanden
        # FAISS save_local/load_local expect a DIRECTORY containing index.faiss and index.pkl 
        #if self.store is not None:
        #    return
        store_dir = Path(self.FAISS_INDEX_PATH)
        index_faiss_file = store_dir / "index.faiss"
        if store_dir.exists() and index_faiss_file.exists():
            try:
                self.store: FAISS = FAISS.load_local(
                    str(store_dir), 
                    self.embeddings, 
                    allow_dangerous_deserialization=True
                )
                print(f"Persistierter Index geladen – Vektoren: {self.store.index.ntotal}")
            except Exception as e:
                _log(f"Fehler beim Laden des Index: {e}")
                self.store = None
        else:
            self.store = None
            _log("Kein existierender Index gefunden – wird beim ausfuehren von build() erstellt.")
        return self.store

            
    def metadata_injection(self, all_docs: list[Document]) -> list[Document]:
        """Injiziert Metadata in page_content für bessere Suche."""
        new_docs: list[Document] = []
        for d in all_docs:
            d.metadata["source"] = _norm_source(d.metadata.get("source"))
            if d.metadata["source"] not in self.manifest:
                metadata_str = " | ".join([f"{k}: {v}" for k, v in d.metadata.items()])
                enriched_content = f"{d.page_content}\n\nMetadata: {metadata_str}"
                new_docs.append(Document(page_content=enriched_content, metadata=d.metadata))
        print(f'New doc added with metadata injection for {len(new_docs)} documents.')
        if not new_docs:
            _log("Keine neuen Dateien – Index ist aktuell.")
            return []
        return new_docs
        # Persistierten Index laden – falls vorhanden
        # FAISS save_local/load_local expect a DIRECTORY containing index.faiss and index.pkl
    # ------------------------------------------------------------
    def build(self, path: Path | str = DEFAULT_PROJECT_ROOT) -> None:
        '''Erstellt oder erweitert den Vector-Store um neue Dateien.'''
        # Initialize embeddings if not already done
        self._initialize()
        project_root = Path(path).expanduser().resolve()
        #_log(f"Suche nach neuen Dateien in: {project_root}")
        self.all_docs = _iter_documents(project_root)
        for d in self.all_docs:
            d.metadata["source"] = _norm_source(d.metadata.get("source"))
        new_docs = [d for d in self.all_docs if d.metadata["source"] not in self.manifest]
        # Korrekte Implementierung für Metadata-Injektion in page_content
        injected_docs: list[Document] = self.metadata_injection(new_docs)
        # ------------------------------------------------------------
        _log(f"{len(injected_docs)} neue Dateien – erstelle Text-Chunks …")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
        )
        # -------------------------------------------------------------
        chunks = splitter.split_documents(injected_docs)
        _log(f"Insgesamt {len(chunks)} Chunks generiert.")
        
        # Check if chunks is empty before creating index
        if not chunks:
            _log("Keine Chunks zum Indizieren vorhanden. Überspringe Index-Erstellung.")
            return
        
        # Index initial erstellen oder erweitern
        if self.store is None:
            # Embeddings (CPU/GPU automatisch via HF-Transformers)
            self.store = FAISS.from_documents(chunks, self.embeddings)
            _log("Neuer FAISS-Index erstellt.")
        elif chunks:
            self.store.add_documents(chunks)

            _log("Bestehender Index erweitert.")
        self.store.save_local(self.FAISS_INDEX_PATH)
        _log(f"Index gespeichert → {self.FAISS_INDEX_PATH}")
        # Manifest aktualisieren
        self.manifest.update(_norm_source(d.metadata.get("source")) for d in new_docs)
        self._save_manifest(self.manifest)
        _log("Manifest aktualisiert.")
            # ------------------------------------------------------------ 

    def query(self,query: str|None = None, k: int = DEFAULT_TOP_K,
            filter_dict:dict|None = None) -> list:
        '''Lädt vollständigen Quellcode der ähnlichsten
            Chunks mit Performance-Monitoring.'''
        query=query
        filter_dict = filter_dict if filter_dict is not None else {}
        print(f'Filter Dict im Query: {filter_dict}')
        for key in filter_dict:
            print(f'Filter Key im Query: {key} ')
        results=''
        full_content: list=[]


        self._initialize()
        self._load_faiss_store()
        if self.store is None:
            _log("Kein Index vorhanden – bitte zuerst build() ausführen.")
            return []
        _log(f'Query: "{query}"  (Top-{k})')
        if query:
            fetch_k = VSTORE_FETCH_K
            if fetch_k <= 0:
                fetch_k = max(int(k) * 4, 10)
                fetch_k = min(fetch_k, 50)

            results = self.store.similarity_search_with_score(query=query, k=fetch_k)
                                                              
                            
            if not results:
                print("   ↳ Keine Treffer.")
            pairs: list[tuple[Document, float]] = [(d, float(s)) for (d, s) in results]

            # Rerank/diversify
            if VSTORE_RERANK and pairs and VSTORE_RERANK_METHOD == "mmr":
                try:
                    # LangChain FAISS MMR (diversity-aware selection)
                    mmr_docs = self.store.max_marginal_relevance_search(
                        query,
                        k=min(int(k), len(pairs)),
                        fetch_k=fetch_k,
                    )
                    # Attach approximate distance score by source (best match wins)
                    best_score_by_source: dict[str, float] = {}
                    for d, s in pairs:
                        src = _norm_source(d.metadata.get("source", ""))
                        prev = best_score_by_source.get(src)
                        if prev is None or float(s) < prev:
                            best_score_by_source[src] = float(s)
                    pairs = [(d, best_score_by_source.get(_norm_source(d.metadata.get("source", "")), float("inf"))) for d in mmr_docs]
                except Exception:
                    # Fallback: plain distance ordering
                    pairs.sort(key=lambda x: x[1])

            if VSTORE_DEDUP and pairs:
                best_by_source: dict[str, tuple[Document, float]] = {}
                for doc, score in pairs:
                    source = _norm_source(doc.metadata.get("source", ""))
                    prev = best_by_source.get(source)
                    # FAISS distance: smaller is better
                    if prev is None or score < prev[1]:
                        best_by_source[source] = (doc, score)
                pairs = list(best_by_source.values())

            if VSTORE_RERANK and pairs and VSTORE_RERANK_METHOD == "crossencoder":
                ce = _get_cross_encoder()
                if ce is not None:
                    try:
                        rerank_inputs = [(query, (doc.page_content or "")[:4000]) for doc, _ in pairs]
                        rerank_scores = ce.predict(rerank_inputs)
                        pairs = [p for _, p in sorted(
                            zip(rerank_scores, pairs),
                            key=lambda x: float(x[0]),
                            reverse=True,
                        )]
                    except Exception:
                        pairs.sort(key=lambda x: x[1])
                else:
                    pairs.sort(key=lambda x: x[1])

            if not (VSTORE_RERANK and VSTORE_RERANK_METHOD in {"mmr", "crossencoder"}):
                pairs.sort(key=lambda x: x[1])

            pairs = pairs[: int(k)]

            payload: list[dict[str, Any]] = []
            for rank, (doc, score) in enumerate(pairs, 1):
                source = _norm_source(doc.metadata.get("source", ""))
                title = doc.metadata.get("titel") or _safe_title_from_source(source)
                content = (doc.page_content or "").strip()
                if VSTORE_MAX_CONTENT_CHARS > 0 and len(content) > VSTORE_MAX_CONTENT_CHARS:
                    content = content[:VSTORE_MAX_CONTENT_CHARS] + "\n…[truncated]"
                item: dict[str, Any] = {
                    "rank": rank,
                    "score": float(score),
                    "source": source,
                    "title": title,
                    "page": doc.metadata.get("page"),
                    "content": content,
                    "metadata": doc.metadata
                }
                if VSTORE_INCLUDE_METADATA:
                    item["metadata"] = dict(doc.metadata)
                payload.append(item)
            return payload
            # Fllbk: exact filename match in docstore (useful when the query is a filename)
        """
            for itms in payload:
                match = True
                for ky in filter_dict:
                    if ky in itms.metadata:
                        if str(itms.metadata[ky]) != str(filter_dict[ky]):
                            match = False
                            break
                    else:
                        match = False
                        break
                if match:
                    full_content.append(itms)
            print(full_content)
            return payload, full_content"""
               


"""
               
               #payload = itms.metadata[u
         
# ──────            ───────────────────────── CLI ────────────────────────────────
# [data['title','content'] for data in payload
def _bui            ld_argparser() -> argparse.ArgumentParser:
pars            er = argparse.ArgumentParser(
        prog="vector_store_manager",.
        description="Erstellt und durchsucht einen FAISS Vector-Store.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # build
    p_build = sub.add_parser("build", help="Index erstellen / erweitern")
    p_build.add_argument(
        "--path",
        default=str(DEFAULT_PROJECT_ROOT),
        help="Projekt-Root (default: aktuelles Verzeichnis)",
    )

    # query
    p_query = sub.add_parser("query", help="Anfrage an den Vector-Store")
    p_query.add_argument("text", help="Query-Text / Suchbegriff")
    p_query.add_argument(
        "-k", "--top_k", type=int, default=DEFAULT_TOP_K, help="Anzahl der Treffer"
    )

    # wipe
    sub.add_parser("wipe", help="Index + Manifest löschen (Reset)")

    return parser

def _main() -> None:
    args = _build_argparser().parse_args()
    vs = VectorStoreManager()

    match args.cmd:
        case "build":
            vs.build(args.path)
        case "query":
            vs.query(args.text, k=args.top_k)
        case "wipe":
            vs.wipe()
        case _:  # pragma: no cover
            raise RuntimeError("Unbekannter Befehl")

               itms.metadata[ky] = filter_dict[m][ky]

if __name__ == "__main__":
    # Ermöglicht:  python -m vector_store_manager <cmd> [...]
     _main()
"""

# usage eg.
# DEFAULT_PROJECT_ROOT:list|str = GetPath().get_path(f"home ben Applications Job_offers",opt="s")#
 # Index erstellen / erweitern

#def vsm_query(text: str, k:int) -> list:/VSM_4_Data/' '**.pdf')
#store_path:GetPath=GetPath()._parent( parg = f"{__file__}"        ) + "AppData/VSM_4_Data/"
#manifest_file:GetPath= GetPath()._parent(parg = f"{__file__}") + "AppData/VSM_4_Data/manifest.json"
#VectorStore(store_path   , manifest_file).build()
#vsm_application.query(text,k=k)
#text:dict[str,dict]|strvsmvsm
#query = "8 punkte learnig path fuer RAG/AI/ML mit LAngChain Torch, "
#filterquery_dict= {'mkeys': {'titel':'test_dict.py'},'rkeys':{'id','source','applied'},'ukeys':{'updated':'08.01.2026'}}

#k:int=20

#query:str = "06898 62221 116117.de - Arzt- und Psychotherapeutensuche Püttlingen"

#data = "AppData/VSM_1_Data/"

#store_path:GetPath = GetPath()._parent(parg = f"{__file__}") + data
#manifest_file:GetPath = store_path + "/manifest.json"
#vsm_projekt = VectorStore(store_path=store_path, manifest_file=manifest_file)

#vsm_projekt.build(GetPath()._parent(parg = f"{__file__} AppData VSM_1_Data"))
# Example query with filter - replace with your own PDF path:
# result = vsm_projekt.query(query="", filter_dict={'source':'path/to/your/document.pdf'}, k=k)
#print(result)
#manifest_file = GetPath()._parent(    parg = f"{__file__}"        ) + "AppData/VSM_1_Data/manifest.json"   
#store_path = GetPath()._parent(    parg = f"{__file__}",        ) + "AppData/VSM_1_Data"  
#
# rvsm_history = VectorStore(        store_path=store_path,         manifest_file=manifest_file    )   
#vsm_history.build(GetPath()._parent(parg = f"{__file__}") + "AppData") 
#vsm_history._initialize()  
#print(f'\n\nMessage Content:\n\n{msg_content}\n\nMessage Metadata:\n{msg_metadata}\n\n{"="*80}\n')  

#print(vsm_history.query(query=query, k=10)[1])




""""

docs = vsm_application.store.docstore._dict   
result = vsm_application.query(text,k=k)  
for d in docs:        ,for msg in result_1
if docs[d].metadata == result.metadata:           
doc:Document=[]           
doc.append(docs[d].page_content)            
#print(f'Found full document for source: {result},{itm}')                 
#print(itm[0].id,'\n',itm[0].page_content,'\n',itm[0].metadata,'\n',itm[1],"="*80)
# #print(result)
# #print(f'\n\nFull Document:\n\n{doc}\n\n{"="*80}\n')
return doc
"""



