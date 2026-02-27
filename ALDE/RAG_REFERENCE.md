# RAG System - Referenz-Implementierung

## Übersicht

Das AI IDE RAG-System ist eine produktionsreife **Retrieval-Augmented Generation** Implementierung, die mehrere Embedding-Backends unterstützt und nahtlos mit dem Agent-System integriert.

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                    RAG System Pipeline                      │
└─────────────────────────────────────────────────────────────┘

Dokumente → Chunking → Embedding → FAISS Index → Query → Retrieval
                                                     ↓
                                            RAG Context
                                                     ↓
                                           Agent LLM (GPT-4)
```

## Komponenten

### 1. **Embedding-Backends** (Multi-Backend-Support)

Das System unterstützt automatisches Fallback zwischen verschiedenen Embedding-Engines:

#### OpenAI Embeddings (Empfohlen für Produktion)
- **Modell**: `text-embedding-3-small`
- **Vorteile**: Hochqualität, konsistent, keine lokale Installation nötig
- **Setup**:
  ```bash
  pip install openai
  export OPENAI_API_KEY="your-api-key"
  ```
- **Verwendung**:
  ```python
  from rag_core import create_rag_system, EmbeddingConfig
  
  config = EmbeddingConfig(backend="openai", openai_api_key="...")
  rag = create_rag_system(embedding_config=config)
  ```

#### HuggingFace Embeddings (Lokal, kostenlos)
- **Modell**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- **Vorteile**: Völlig lokal, keine API-Kosten, multilingual
- **Setup**:
  ```bash
  pip install langchain-huggingface
  ```
- **Verwendung**: Automatisch aktiviert wenn verfügbar

#### Sentence-Transformers (Direkt, lokal)
- **Modell**: Konfigurierbar
- **Vorteile**: Volle Kontrolle, viele Modelle verfügbar
- **Setup**:
  ```bash
  pip install sentence-transformers
  ```
- **Hinweis**: Kann torchvision Dependency-Probleme haben

### 2. **Vector Store** (FAISS)

- **Persistierung**: Index wird auf Disk gespeichert
- **Schnelle Suche**: Optimiert für Similarity Search
- **Manifest-Datei**: Trackt indizierte Dokumente und Metadaten

### 3. **Document Chunker**

- **Strategie**: Recursive Character Text Splitter
- **Standard-Chunk-Size**: 1000 Zeichen
- **Overlap**: 150 Zeichen für Kontext-Kontinuität
- **Separator**: `\n\n` (Absätze)

## Installation

### Minimal (mit OpenAI):
```bash
pip install openai faiss-cpu langchain-community langchain-core
```

### Lokal (HuggingFace):
```bash
pip install langchain-huggingface faiss-cpu langchain-community langchain-core
```

### Vollständig (alle Backends):
```bash
pip install openai sentence-transformers langchain-huggingface faiss-cpu langchain-community langchain-core
```

## Verwendung

### Basis-Setup

```python
from rag_core import create_rag_system

# Einfachste Verwendung (automatisches Backend)
rag = create_rag_system()

# Mit spezifischem Backend
from rag_core import RAGSystem, EmbeddingConfig

config = EmbeddingConfig(
    backend="openai",  # oder "huggingface", "sentence-transformers", "auto"
    openai_api_key=os.environ.get("OPENAI_API_KEY")
)
rag = RAGSystem(
    store_path="AppData/VSM_1_Data",
    embedding_config=config
)
```

### Dokumente hinzufügen

```python
# Einzelnes Dokument
rag.add_document(
    content="Das ist ein Beispieldokument über Machine Learning...",
    source="docs/ml_guide.md",
    title="ML Guide"
)

# Mehrere Dokumente
for doc in documents:
    rag.add_document(doc["content"], doc["source"], doc["title"])
```

### Kontext abrufen

```python
# Retrieve relevante Dokumente
results = rag.retrieve(
    query="Wie implementiere ich einen Transformer?",
    k=5  # Top 5 Ergebnisse
)

# Formatierter Kontext für Agent-Prompts
context = rag.get_context(
    query="Transformer implementation",
    k=3
)
print(context)
```

### Agent-Integration

```python
from rag_integration import get_global_rag_manager

# RAG Manager initialisieren
manager = get_global_rag_manager()

# Kontext für Agent abrufen
context = manager.retrieve_for_agent(
    agent_name="_cover_letter_generator",
    query="Best practices for cover letters",
    k=5
)

# In Agent-Prompt einbinden
prompt = f"""
System: Du bist ein Cover Letter Generator.

Kontext aus Wissensdatenbank:
{context}

User Request: Erstelle ein Anschreiben für...
"""
```

## Agent-System-Integration

### vectordb_tool

```python
# Agent ruft vectordb_tool auf
result = vectordb_tool_rag(
    query="Find resume templates",
    k=3
)

# Result-Format:
{
    "ok": True,
    "result": [
        {
            "content": "Resume template content...",
            "source": "templates/resume.md",
            "score": 0.89,
            "chunk_index": 0
        },
        ...
    ],
    "query": "Find resume templates",
    "count": 3
}
```

### memorydb_tool

Ähnlich wie `vectordb_tool`, aber für session-spezifische Speicher:

```python
result = memorydb_tool_rag(
    query="Previous conversation about Python",
    k=5
)
```

## Verzeichnisstruktur

```
AppData/
├── VSM_0_Data/          # Legacy vector store
├── VSM_1_Data/          # Persistent vectordb
│   ├── index.faiss      # FAISS Index
│   ├── index.pkl        # Metadata
│   └── manifest.json    # Document tracking
├── VSM_2_Data/          # Reserved
├── VSM_3_Data/          # Session memorydb
└── VSM_4_Data/          # Custom stores
```

## Konfiguration

### EmbeddingConfig

```python
from rag_core import EmbeddingConfig

config = EmbeddingConfig(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    backend="auto",  # "auto", "openai", "huggingface", "sentence-transformers"
    device="cpu",    # "cpu" oder "cuda"
    normalize_embeddings=True,
    batch_size=32,
    show_progress_bar=False,
    openai_api_key=None  # Falls None, wird aus Environment gelesen
)
```

### ChunkingConfig

```python
from rag_core import ChunkingConfig

config = ChunkingConfig(
    chunk_size=1000,      # Größe pro Chunk in Zeichen
    chunk_overlap=150,    # Overlap für Kontext
    separator="\n\n"      # Separator für Splitting
)
```

## Performance-Tipps

### 1. Backend-Wahl

- **OpenAI**: Beste Qualität, API-Kosten, keine lokale GPU nötig
- **HuggingFace**: Kostenlos, lokal, gut für deutsche Texte
- **Sentence-Transformers**: Flexibel, aber Setup komplexer

### 2. Chunk-Size

- **Zu klein** (< 500): Kontext geht verloren
- **Optimal** (800-1200): Gute Balance
- **Zu groß** (> 2000): Irrelevanter Content in Ergebnissen

### 3. Top-K Werte

- **k=3-5**: Für spezifische Fragen
- **k=10-15**: Für breite Recherche
- **k>20**: Nur bei großen Datenmengen sinnvoll

## Fehlerbehandlung

### Kein Backend verfügbar

```python
stats = rag.get_stats()
if stats["active_backend"] == "dummy":
    print("⚠️ Kein Embedding-Backend verfügbar!")
    print("Installiere: pip install openai ODER pip install langchain-huggingface")
```

### FAISS Import-Fehler

```bash
# CPU-Version (einfacher)
pip install faiss-cpu

# GPU-Version (schneller, wenn CUDA verfügbar)
pip install faiss-gpu
```

### OpenAI API-Fehler

```python
import os

# API Key setzen
os.environ["OPENAI_API_KEY"] = "YOUR_OPENAI_API_KEY"

# Oder in Config übergeben
config = EmbeddingConfig(
    backend="openai",
    openai_api_key="YOUR_OPENAI_API_KEY"
)
```

## Beispiel: Vollständiger Workflow

```python
from rag_core import create_rag_system
from rag_integration import init_global_rag_manager

# 1. RAG System initialisieren
rag = create_rag_system(
    store_path="AppData/VSM_1_Data",
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    chunk_size=1000
)

# 2. Dokumente hinzufügen
documents = [
    {
        "content": "Cover Letter Best Practices:\n1. Personalize...\n2. Match keywords...",
        "source": "guides/cover_letter_tips.md",
        "title": "Cover Letter Guide"
    },
    {
        "content": "Resume Format:\n- Use bullet points\n- Quantify achievements...",
        "source": "guides/resume_format.md",
        "title": "Resume Best Practices"
    }
]

for doc in documents:
    chunks_added = rag.add_document(
        doc["content"],
        doc["source"],
        doc["title"]
    )
    print(f"✓ Added {chunks_added} chunks from {doc['title']}")

# 3. Statistiken prüfen
stats = rag.get_stats()
print(f"\nRAG System Stats:")
print(f"  Backend: {stats['active_backend']}")
print(f"  Total Chunks: {stats['total_chunks']}")
print(f"  Indexed Sources: {stats['indexed_sources']}")

# 4. Query durchführen
query = "How to write an effective cover letter?"
results = rag.retrieve(query, k=3)

print(f"\nQuery: {query}")
for i, result in enumerate(results, 1):
    print(f"\n[{i}] Score: {result.relevance_score:.3f}")
    print(f"Source: {result.source}")
    print(f"Content: {result.content[:150]}...")

# 5. Agent-Integration
manager = init_global_rag_manager()
context = manager.retrieve_for_agent(
    "_cover_letter_generator",
    query,
    k=3
)
print(f"\nFormatted Context for Agent:\n{context}")
```

## Best Practices

### 1. Dokumenten-Metadaten

Immer aussagekräftige Metadaten setzen:

```python
rag.add_document(
    content=content,
    source="docs/product_specs/feature_X.md",  # Eindeutiger Pfad
    title="Feature X Specification"            # Lesbarer Titel
)
```

### 2. Regelmäßige Index-Updates

```python
# Manifest prüfen
manifest = rag.vector_store.manifest
indexed_sources = set(manifest.get("indexed_sources", []))

# Neue Dokumente hinzufügen
for doc in new_documents:
    if doc["source"] not in indexed_sources:
        rag.add_document(...)
```

### 3. Relevanz-Filtering

```python
from rag_integration import RAGContext

context = RAGContext(
    agent_name="my_agent",
    min_relevance_score=0.7  # Nur Ergebnisse > 70% Relevanz
)

results = context.retrieve_context(query, k=10, filter_by_score=True)
```

## Debugging

### Embedding-Test

```python
engine = rag.embedding_engine
test_embedding = engine.embed_query("test query")
print(f"Embedding dimension: {len(test_embedding)}")
print(f"Backend type: {engine.backend_type}")
```

### Vector Store inspektion

```python
# Manifest lesen
import json
manifest_path = "AppData/VSM_1_Data/manifest.json"
with open(manifest_path) as f:
    manifest = json.load(f)

print(f"Indexed documents: {len(manifest['documents'])}")
print(f"Total chunks: {manifest['chunk_count']}")
```

## Limitationen

1. **FAISS Index-Größe**: Bei >1M Vektoren kann Performance leiden
2. **OpenAI Rate Limits**: Batch-Größen beachten
3. **Memory**: Große Embeddings können viel RAM benötigen
4. **Multilingual**: Modell muss Deutsch unterstützen

## Roadmap

- [ ] Hybrid Search (Dense + Sparse Retrieval)
- [ ] Re-ranking mit Cross-Encoder
- [ ] Incremental Indexing
- [ ] Query Expansion
- [ ] Document Deduplication

## Support

Bei Problemen:
1. Prüfe `rag.get_stats()` für Backend-Status
2. Checke Logs: `[RAG]` Prefix zeigt Warnungen
3. Teste mit kleinem Datensatz erst
4. Validiere API-Keys bei OpenAI-Backend

---

**Version**: 1.0  
**Autor**: Benjamin R.  
**Datum**: Januar 2025  
**Lizenz**: Proprietary
