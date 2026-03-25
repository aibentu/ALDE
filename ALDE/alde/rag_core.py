"""
RAG (Retrieval-Augmented Generation) Reference Implementation for AI IDE

This module provides a robust, production-grade RAG system that:
1. Handles embeddings via sentence-transformers or fallback embeddings
2. Manages vector stores with FAISS
3. Provides document chunking and retrieval
4. Integrates seamlessly with the agent system

ARCHITECTURE:
    Document → Chunking → Embedding → FAISS Storage → Query → Retrieval
                                                          ↓
                                                    RAG Context
                                                          ↓
                                                    Agent LLM

USAGE:
    from rag_core import RAGSystem
    
    # Initialize
    rag = RAGSystem(store_path="AppData/VSM_1_Data")
    
    # Build index from documents
    rag.build(root_dir="./documents", chunk_size=1000)
    
    # Query for relevant context
    results = rag.query("How to implement feature X?", k=5)
    
    # Use results in agent prompts
    context = "\n".join([doc.page_content for doc, score in results])

REFERENCE IMPLEMENTATION FOR:
    - Document embedding strategies
    - Similarity search configuration
    - Vector store persistence
    - Chunk optimization
    - RAG context injection patterns
"""

from __future__ import annotations

import json
import os
import sys
import hashlib
from pathlib import Path
from typing import Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from datetime import datetime, timezone
import logging

# ────────────────────── Optional Imports ──────────────────────
# Try multiple embedding backends: OpenAI, sentence-transformers, HuggingFace

_HAS_OPENAI_EMBEDDINGS = False
_HAS_SENTENCE_TRANSFORMERS = False
_HAS_HUGGINGFACE_EMBEDDINGS = False

try:
    from openai import OpenAI
    _HAS_OPENAI_EMBEDDINGS = True
except ImportError:
    pass

try:
    from sentence_transformers import SentenceTransformer
    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    pass

if not _HAS_SENTENCE_TRANSFORMERS:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        _HAS_HUGGINGFACE_EMBEDDINGS = True
    except ImportError:
        pass

# FAISS is always required for vector store
try:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
except ImportError:
    print("[RAG] Warning: FAISS/LangChain not available. Some features disabled.")
    FAISS = None
    Document = None

# ────────────────────── Constants ──────────────────────

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_TOP_K = 5
MAX_CHUNK_SIZE = 4000
MIN_CHUNK_SIZE = 100

# ────────────────────── Logging ──────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[RAG] %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _try_chathistory_log(event: str, *, data: dict | None = None) -> None:
    """Best-effort ChatHistory logging; never breaks RAG flows."""
    try:
        try:
            from .ccompletion import ChatHistory  # type: ignore
        except Exception:
                from ccompletion import ChatHistory  # type: ignore
        ChatHistory().log(
            _role="tool",
            _content=event,
            _obj="model",
            _data=data or {},
            _thread_name="model",
            _name_tool="openai.embeddings.create",  
        ),            
        return _utc_now_iso()

    except Exception:
        return


# ────────────────────── Data Classes ──────────────────────

@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""
    model_name: str = DEFAULT_MODEL
    backend: str = "auto"  # "auto", "openai", "sentence-transformers", "huggingface"
    device: str = ""  # "cpu" or "cuda"
    normalize_embeddings: bool = True
    batch_size: int = 32
    show_progress_bar: bool = False
    openai_api_key: str | None = None  # Optional: read from env if None
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChunkingConfig:
    """Configuration for document chunking."""
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    separator: str = "\n\n"
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievalResult:
    """Single retrieval result with metadata."""
    content: str
    source: str
    relevance_score: float
    chunk_index: int = 0
    title: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


# ────────────────────── Embedding Engine ──────────────────────

class EmbeddingEngine:
    """Handles text embedding with automatic fallback."""
    
    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig()
        self.model = None
        self.embeddings_obj = None
        self.openai_client = None
        self.backend_type = None
        self._init_embeddings()
    
    def _init_embeddings(self) -> None:
        """Initialize embeddings using best available method."""
        backend = self.config.backend.lower()
        
        # Try OpenAI first if explicitly requested or auto with API key
        if (backend in {"auto", "openai"}) and _HAS_OPENAI_EMBEDDINGS:
            try:
                api_key = self.config.openai_api_key or os.environ.get("OPENAI_API_KEY")
                if api_key:
                    self.openai_client = OpenAI(api_key=api_key)
                    # Test with a quick embedding
                    _try_chathistory_log(
                        "openai.embeddings.create request",
                        data={"model": "text-embedding-3-small", "n_inputs": 1, "stage": "init_test"},
                    )
                    try:
                        test = self.openai_client.embeddings.create(
                            input="test",
                            model="text-embedding-3-small",
                        )
                    except Exception as e:
                        _try_chathistory_log(
                            "openai.embeddings.create error",
                            data={"model": "text-embedding-3-small", "stage": "init_test", "error": f"{type(e).__name__}: {e}"},
                        )
                        raise
                    _try_chathistory_log(
                        "openai.embeddings.create response",
                        data={"model": "text-embedding-3-small", "response_id": getattr(test, "id", None), "stage": "init_test"},
                    )
                    self.backend_type = "openai"
                    logger.info(f"Using OpenAI embeddings: text-embedding-3-small")
                    return
            except Exception as e:
                logger.warning(f"OpenAI embeddings failed: {e}")
        
        # Try HuggingFace embeddings (most stable for local)
        if (backend in {"auto", "huggingface"}) and _HAS_HUGGINGFACE_EMBEDDINGS:
            try:
                self.embeddings_obj = HuggingFaceEmbeddings(
                    model_name=self.config.model_name
                )
                self.backend_type = "huggingface"
                logger.info(f"Using HuggingFaceEmbeddings: {self.config.model_name}")
                return
            except Exception as e:
                logger.warning(f"HuggingFaceEmbeddings failed: {e}")
        
        # Try sentence-transformers (if available)
        if (backend in {"auto", "sentence-transformers"}) and _HAS_SENTENCE_TRANSFORMERS:
            try:
                self.model = SentenceTransformer(
                    self.config.model_name,
                    device=self.config.device
                )
                self.backend_type = "sentence-transformers"
                logger.info(f"Using sentence-transformers: {self.config.model_name}")
                return
            except Exception as e:
                logger.warning(f"sentence-transformers failed: {e}")
        
        # Final fallback: dummy embeddings (for testing only)
        logger.error("No embedding library available! Install: pip install openai OR pip install langchain-huggingface")
        self.model = None
        self.embeddings_obj = None
        self.backend_type = "dummy"
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []
        
        if self.openai_client is not None:
            # OpenAI embeddings (preferred for production)
            try:
                _try_chathistory_log(
                    "openai.embeddings.create request",
                    data={"model": "text-embedding-3-small", "n_inputs": len(texts)},
                )
                response = self.openai_client.embeddings.create(
                    input=texts,
                    model="text-embedding-3-small"  # Fast and cost-effective
                )
                _try_chathistory_log(
                    "openai.embeddings.create response",
                    data={"model": "text-embedding-3-small", "response_id": getattr(response, "id", None), "n_outputs": len(getattr(response, "data", []) or [])},
                )
                return [item.embedding for item in response.data]
            except Exception as e:
                _try_chathistory_log(
                    "openai.embeddings.create error",
                    data={"model": "text-embedding-3-small", "error": f"{type(e).__name__}: {e}"},
                )
                logger.error(f"OpenAI embeddings failed: {e}")
        
        if self.embeddings_obj is not None:
            # HuggingFace embeddings (local)
            try:
                return self.embeddings_obj.embed_documents(texts)
            except Exception as e:
                logger.error(f"HuggingFaceEmbeddings failed: {e}")
        
        if self.model is not None:
            # sentence-transformers (local)
            try:
                embeddings = self.model.encode(
                    texts,
                    batch_size=self.config.batch_size,
                    show_progress_bar=self.config.show_progress_bar,
                    normalize_embeddings=self.config.normalize_embeddings
                )
                return embeddings.tolist()
            except Exception as e:
                logger.error(f"sentence-transformers encoding failed: {e}")
        
        # Dummy fallback (all zeros)
        logger.warning(f"Using dummy embeddings for {len(texts)} texts")
        embedding_dim = 384  # Default for paraphrase-MiniLM
        return [[0.0] * embedding_dim for _ in texts]
    
    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a single query."""
        if self.openai_client is not None:
            try:
                _try_chathistory_log(
                    "openai.embeddings.create request",
                    data={"model": "text-embedding-3-small", "n_inputs": 1, "stage": "query"},
                )
                response = self.openai_client.embeddings.create(
                    input=query,
                    model="text-embedding-3-small"
                )
                _try_chathistory_log(
                    "openai.embeddings.create response",
                    data={"model": "text-embedding-3-small", "response_id": getattr(response, "id", None), "stage": "query"},
                )
                return response.data[0].embedding
            except Exception as e:
                _try_chathistory_log(
                    "openai.embeddings.create error",
                    data={"model": "text-embedding-3-small", "stage": "query", "error": f"{type(e).__name__}: {e}"},
                )
                logger.error(f"OpenAI query embedding failed: {e}")
        
        if self.embeddings_obj is not None:
            try:
                return self.embeddings_obj.embed_query(query)
            except Exception as e:
                logger.error(f"Query embedding failed: {e}")
        
        if self.model is not None:
            try:
                embedding = self.model.encode(query, normalize_embeddings=self.config.normalize_embeddings)
                return embedding.tolist()
            except Exception as e:
                logger.error(f"Query encoding failed: {e}")
        
        # Dummy fallback
        return [0.0] * 384
    
    # FAISS compatibility methods
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Alias for embed_texts (FAISS compatibility)."""
        return self.embed_texts(texts)
    
    def __call__(self, text: str) -> List[float]:
        """Make EmbeddingEngine callable for FAISS compatibility."""
        return self.embed_query(text)


# ────────────────────── Document Chunker ──────────────────────

class DocumentChunker:
    """Splits documents into overlapping chunks."""
    
    def __init__(self, config: ChunkingConfig | None = None):
        self.config = config or ChunkingConfig()
    
    def chunk(self, text: str, source: str = "", title: str = "") -> List[dict]:
        """Split text into chunks with metadata."""
        if not text:
            return []
        
        # Validate config
        chunk_size = max(MIN_CHUNK_SIZE, min(self.config.chunk_size, MAX_CHUNK_SIZE))
        overlap = min(self.config.chunk_overlap, chunk_size // 2)
        
        chunks = []
        sep = self.config.separator
        
        # Split by separator first
        paragraphs = text.split(sep)
        
        current_chunk = ""
        chunk_index = 0
        
        for para in paragraphs:
            if len(current_chunk) + len(para) + len(sep) <= chunk_size:
                current_chunk += para + sep
            else:
                # Save current chunk if not empty
                if current_chunk.strip():
                    chunks.append({
                        "content": current_chunk.strip(),
                        "source": source,
                        "title": title,
                        "chunk_index": chunk_index,
                        "size": len(current_chunk),
                        "timestamp": _utc_now_iso()
                    })
                    chunk_index += 1
                
                # Start new chunk with overlap
                if overlap > 0:
                    # Try to maintain overlap from previous chunk
                    split_point = max(0, len(current_chunk) - overlap)
                    current_chunk = current_chunk[split_point:] + para + sep
                else:
                    current_chunk = para + sep
        
        # Add last chunk
        if current_chunk.strip():
            chunks.append({
                "content": current_chunk.strip(),
                "source": source,
                "title": title,
                "chunk_index": chunk_index,
                "size": len(current_chunk),
                "timestamp": _utc_now_iso()
            })
        
        logger.debug(f"Chunked '{source}': {len(chunks)} chunks")
        return chunks


# ────────────────────── Vector Store Manager ──────────────────────

class VectorStoreManager:
    """Manages FAISS vector store with persistence."""
    
    def __init__(
        self,
        store_path: str,
        embedding_engine: EmbeddingEngine | None = None,
        chunking_config: ChunkingConfig | None = None
    ):
        self.store_path = Path(store_path).expanduser().resolve()
        self.store_path.mkdir(parents=True, exist_ok=True)
        
        self.embedding_engine = embedding_engine or EmbeddingEngine()
        self.chunking_config = chunking_config or ChunkingConfig()
        
        self.chunker = DocumentChunker(self.chunking_config)
        self.faiss_store = None
        self.manifest = self._load_manifest()
        
        self._load_store()
    
    def _manifest_path(self) -> Path:
        return self.store_path / "manifest.json"
    
    def _load_manifest(self) -> dict:
        """Load or initialize manifest file."""
        manifest_file = self._manifest_path()
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load manifest: {e}")
        
        return {
            "schema": "rag_manifest_v1",
            "created": _utc_now_iso(),
            "documents": {},
            "chunk_count": 0,
            "indexed_sources": []
        }
    
    def _save_manifest(self) -> None:
        """Persist manifest to disk."""
        try:
            manifest_file = self._manifest_path()
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(self.manifest, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Could not save manifest: {e}")
    
    def _load_store(self) -> None:
        """Load existing FAISS store from disk."""
        if FAISS is None:
            logger.warning("FAISS not available, vector store disabled")
            return
        
        index_file = self.store_path / "index.faiss"
        if not index_file.exists():
            logger.debug(f"No existing index at {self.store_path}")
            return
        
        try:
            # Load with LangChain's FAISS wrapper
            dummy_embeddings = self.embedding_engine
            self.faiss_store = FAISS.load_local(
                str(self.store_path),
                embeddings=dummy_embeddings.embeddings_obj or dummy_embeddings,
                allow_dangerous_deserialization=True
            )
            logger.info(f"Loaded FAISS store from {self.store_path}")
        except Exception as e:
            logger.warning(f"Could not load FAISS store: {e}")
            self.faiss_store = None
    
    def add_document(
        self,
        content: str,
        source: str,
        title: str = ""
    ) -> int:
        """Add document to index."""
        if not content:
            return 0
        
        # Create chunks
        chunks = self.chunker.chunk(content, source, title)
        if not chunks:
            return 0
        
        # Generate embeddings
        chunk_texts = [chunk["content"] for chunk in chunks]
        try:
            embeddings_list = self.embedding_engine.embed_texts(chunk_texts)
        except Exception as e:
            logger.error(f"Embedding failed for {source}: {e}")
            return 0
        
        # Create documents
        try:
            if Document:
                documents = [
                    Document(
                        page_content=chunk["content"],
                        metadata={
                            "source": source,
                            "title": title,
                            "chunk_index": chunk["chunk_index"],
                            "size": chunk["size"]
                        }
                    )
                    for chunk in chunks
                ]
        except Exception as e:
            logger.error(f"Could not create documents: {e}")
            return 0
        
        # Add to FAISS
        if FAISS and self.faiss_store is None:
            try:
                self.faiss_store = FAISS.from_documents(
                    documents,
                    self.embedding_engine.embeddings_obj or self.embedding_engine
                )
            except Exception as e:
                logger.error(f"Could not create FAISS store: {e}")
                return 0
        elif FAISS and self.faiss_store:
            try:
                self.faiss_store.add_documents(documents)
            except Exception as e:
                logger.error(f"Could not add documents to FAISS: {e}")
                return 0
        
        # Update manifest
        source_hash = hashlib.sha256(source.encode()).hexdigest()[:16]
        self.manifest["documents"][source_hash] = {
            "source": source,
            "title": title,
            "chunk_count": len(chunks),
            "added": _utc_now_iso()
        }
        self.manifest["chunk_count"] = self.manifest.get("chunk_count", 0) + len(chunks)
        if source not in self.manifest["indexed_sources"]:
            self.manifest["indexed_sources"].append(source)
        
        self._save_manifest()
        self._save_store()
        
        logger.info(f"Added {len(chunks)} chunks from {source}")
        return len(chunks)
    
    def _save_store(self) -> None:
        """Persist FAISS index to disk."""
        if self.faiss_store is None or FAISS is None:
            return
        
        try:
            self.faiss_store.save_local(str(self.store_path))
            logger.debug(f"Saved FAISS store to {self.store_path}")
        except Exception as e:
            logger.error(f"Could not save FAISS store: {e}")
    
    def query(self, query_text: str, k: int = DEFAULT_TOP_K) -> List[RetrievalResult]:
        """Search vector store for relevant documents."""
        if self.faiss_store is None:
            logger.warning("Vector store not initialized")
            return []
        
        k = max(1, min(k, 50))  # Reasonable bounds
        
        try:
            results = self.faiss_store.similarity_search_with_score(query_text, k=k)
            
            retrieval_results = []
            for doc, score in results:
                result = RetrievalResult(
                    content=doc.page_content,
                    source=doc.metadata.get("source", "unknown"),
                    relevance_score=float(score),
                    chunk_index=doc.metadata.get("chunk_index", 0),
                    title=doc.metadata.get("title", "")
                )
                retrieval_results.append(result)
            
            return retrieval_results
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []


# ────────────────────── RAG System (Main API) ──────────────────────

class RAGSystem:
    """Complete RAG system combining all components."""
    
    def __init__(
        self,
        store_path: str = "AppData/VSM_1_Data",
        embedding_config: EmbeddingConfig | None = None,
        chunking_config: ChunkingConfig | None = None
    ):
        self.store_path = store_path
        self.embedding_config = embedding_config or EmbeddingConfig()
        self.chunking_config = chunking_config or ChunkingConfig()
        
        self.embedding_engine = EmbeddingEngine(self.embedding_config)
        self.vector_store = VectorStoreManager(
            store_path,
            self.embedding_engine,
            self.chunking_config
        )
    
    def add_document(self, content: str, source: str, title: str = "") -> int:
        """Add document to RAG index."""
        return self.vector_store.add_document(content, source, title)
    
    def retrieve(self, query: str, k: int = DEFAULT_TOP_K) -> List[RetrievalResult]:
        """Retrieve relevant documents for a query."""
        return self.vector_store.query(query, k)
    
    def get_context(self, query: str, k: int = 5) -> str:
        """Get RAG context as formatted string (for agent prompts)."""
        results = self.retrieve(query, k)
        if not results:
            return "(No relevant context found)"
        
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[{i}] (Score: {result.relevance_score:.3f}, Source: {result.source})\n"
                f"{result.content}"
            )
        
        return "\n\n".join(context_parts)
    
    def get_stats(self) -> dict:
        """Get index statistics."""
        return {
            "store_path": self.store_path,
            "total_chunks": self.vector_store.manifest.get("chunk_count", 0),
            "indexed_sources": len(self.vector_store.manifest.get("indexed_sources", [])),
            "embedding_model": self.embedding_config.model_name,
            "chunk_size": self.chunking_config.chunk_size,
            "chunk_overlap": self.chunking_config.chunk_overlap,
            "available_backends": {
                "openai": _HAS_OPENAI_EMBEDDINGS,
                "sentence_transformers": _HAS_SENTENCE_TRANSFORMERS,
                "huggingface_embeddings": _HAS_HUGGINGFACE_EMBEDDINGS,
                "faiss": FAISS is not None
            },
            "active_backend": self.embedding_engine.backend_type
        }


# ────────────────────── Helper Functions ──────────────────────

def create_rag_system(
    store_path: str = "AppData/VSM_1_Data",
    model_name: str = DEFAULT_MODEL,
    chunk_size: int = DEFAULT_CHUNK_SIZE
) -> RAGSystem:
    """Convenience function to create RAG system with defaults."""
    embedding_config = EmbeddingConfig(model_name=model_name)
    chunking_config = ChunkingConfig(chunk_size=chunk_size)
    return RAGSystem(store_path, embedding_config, chunking_config)


if __name__ == "__main__":
    # Simple usage example
    print("RAG Core Module - Reference Implementation")
    print("=" * 50)
    
    rag = create_rag_system()
    stats = rag.get_stats()
    
    print(f"\nRAG System Status:")
    for key, value in stats.items():
        if key != "available_backends":
            print(f"  {key}: {value}")
    
    print(f"\nAvailable Backends:")
    for backend, available in stats["available_backends"].items():
        print(f"  {backend}: {'✓' if available else '✗'}")
