# Deep‑Dive: Repo‑Analyse (Zielrolle: RAG Engineer / Applied AI/ML Engineer)

*Stand: 08.01.2026 – technisch/architektonisch, interview‑tauglich.*

## 1) Systemziel & Scope
Dieses Repo implementiert eine lokal laufende AI‑IDE, die drei Ebenen zusammenführt:

1) **User Experience** (PySide6 Desktop GUI)
2) **Agentic Runtime** (LLM + Tool‑Calling + Routing)
3) **Knowledge Layer (RAG)** (Ingestion, Chunking, Embeddings, FAISS Persistenz, Retrieval‑Tool)

Zielwirkung: lokale Wissensquellen nutzbar machen (Code, PDFs, Markdown, Chat‑History) und diese Quellen per Retrieval in Antworten/Agent‑Aktionen einfließen lassen.

---

## 2) Hauptkomponenten (Code‑Map)
### UI / Desktop Shell
- `ai_ide_v1756.py`: zentrale GUI, Docking/Viewer, Datei‑Interaktion, Chat‑UI.
- `file_viewer.py`, `editor_tab.py`, `json_tree.py`, `jstree_widget.py`: Darstellung/Interaktion mit Dateien/Strukturen.

### LLM + Agent Runtime
- `chat_completion.py`
  - OpenAI Client (API Key Loading, Client Instanz)
  - `ChatHistory`: Persistenz + Kontext-Einfügung in Requests
  - Basis für Tool‑Call Sequenzen (OpenAI verlangt valide Reihenfolge)

- `agenszie_factory.py`
  - Unified Tool Registry: `ToolSpec` / `ParamSpec`
  - Dispatcher: `execute_tool` + Special Handler
  - Tool‑Call Loop: `_handle_tool_calls(...)` (execute tools → follow‑up model call)
  - Agent‑Routing: `route_to_agent` erzeugt routing_request (messages + tools)

### RAG / Knowledge Layer
- `vstores.py`
  - FAISS‑basierter VectorStore, Build/Query
  - robuste Loader (Python/text/pdf/json-history), Metadaten‑Normalisierung
  - Embeddings: Sentence‑Transformers multilingual MiniLM

- `iter_documents.py`
  - leichter Ingestion‑Pfad (rglob + Text/PDF loader)

- `embed_tool.py`
  - CLI: build/query/stats/dump/wipe für einen "simple_index" (FAISS)

- `doc_client.py`
  - CLI: Ingestion stats/export, optional verbose

### MCP
- `mcp_server.py`: stdio MCP Server (initialize, tools/list, tools/call) delegiert an `execute_tool`.
- `mcp_servers.json`: MCP Client Config
- `mcp_health.py`: startet Server, sendet initialize + tools/list

---

## 3) RAG‑Pipeline (End‑to‑End) – technisch
### 3.1 Ingestion
Es existieren mehrere Varianten:

- **Minimal (einfach, schnell):** `iter_documents.py`
  - Traversiert Files, lädt PDF via `PyPDFLoader`, Text via `TextLoader`.
  - Skip‑Dirs: `.git`, `venv`, `__pycache__`, etc.

- **Robuster (breiter, produktionstauglicher):** `vstores.py`
  - Python via `DirectoryLoader(PythonLoader)`
  - Textformate via `SafeTextLoader` (Encoding‑Fehler werden abgefangen)
  - JSON‑History via `_load_json()` (Chat‑Log als Knowledge Source)
  - PDF: Anreicherung von Metadaten (`source`, `titel`, `id`, …)

### 3.2 Chunking
- `vstores.py`: Chunk‑Parameter als Konstanten (`CHUNK_SIZE`, `CHUNK_OVERLAP`).
- `embed_tool.py`: Chunking als expliziter Pipeline‑Step (RecursiveCharacterTextSplitter).

### 3.3 Embeddings
- Modell: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Umsetzung: `HuggingFaceEmbeddings` (LangChain)

### 3.4 Index / Persistenz
- VectorStore: LangChain `FAISS`
- Persistenz in `AppData/...` mit mehreren DB‑Ordnern je nach Zweck (Projekt, MemoryDB, simple_index).

### 3.5 Retrieval als Tool
- `agenszie_factory.execute_tool()` routet `vectordb_tool` über einen Special Handler.
- Ergebnisse werden gecached (`_TOOL_CACHE`) und dann als Tool‑Message ins History‑Log geschrieben.

### 3.6 Grounding / Tool‑Call Sequenz
- `_handle_tool_calls(...)` loggt erst die Assistant‑Nachricht mit `tool_calls`, führt dann Tool Calls aus und loggt pro Tool‑Call eine **"role=tool"**‑Message.
- Danach Follow‑up Call an das Modell, damit Tool Output in eine finale Antwort transformiert wird.

Interview‑Hook: Das ist wichtig, weil die OpenAI APIs eine *strikte* Message‑Sequenz erwarten; das Repo implementiert diesen Mechanismus.

---

## 4) MCP (Model Context Protocol) als Integrationsebene
- `mcp_server.py` exposiert die Tool‑Registry und Tool‑Execution über stdio.
- Vorteil: Tools werden nicht nur im GUI‑Chat genutzt, sondern sind für MCP‑fähige Clients konsumierbar (lokale Agenten‑Runtime als „Tool Provider“).

---

## 5) Applied‑AI Perspektive: Produktisierung & Betrieb
- Healthcheck (`mcp_health.py`) validiert Server + Tool‑Listing.
- Tests existieren im `Tests/` Ordner (u.a. Vectorstore/Performance‑Themen).
- Desktop GUI macht das System nutzbar für nicht‑CLI Nutzer.

---

## 6) Bewertung: Stärken / Risiken / Next Steps
### Stärken
- Tool Registry als Single Source of Truth (Specs → OpenAI Tool Definitions + Dispatcher)
- RAG‑Bausteine komplett vorhanden und lokal betreibbar
- MCP‑Exposition als saubere Integrations‑Story

### Risiken / Tech Debt (konkret)
- Doppelte/mehrfache Ingestion‑Implementationen (unterschiedliche Semantik, Debug‑Prints)
- Hardcoded Pfade / Rest‑Code in einzelnen Dateien (z.B. `embed_tool.py` nach `__main__`)
- Metadaten/Citations sind vorhanden, aber noch nicht als striktes Schema erzwingbar

### Nächste sinnvolle Schritte (für RAG Engineer)
- Konsolidieren auf **eine** Ingestion/Chunking Pipeline + Config (YAML/JSON)
- Hybrid Retrieval (BM25 + Vectors), optional Reranking
- Evaluation Harness (MRR/Recall@k, Golden Queries), Logging/Tracing
- Citation‑Format definieren (source + span/offset + page) und im UI darstellen

---

## 7) Interview‑Story (2–3 Minuten)
> Ich habe eine lokale AI‑IDE gebaut, die Chat‑basierte Agenten mit Tool‑Calling und RAG kombiniert. Dokumente und Code werden lokal ingestiert, gechunkt, per Sentence‑Transformer embedded und in FAISS persistiert. Retrieval läuft als Tool (`vectordb_tool`) und die Tool‑Call Sequenzen werden korrekt in der Chat‑History geführt (Assistant→Tool→Follow‑up), damit das Modell Tool‑Ergebnisse sauber in Antworten überführt. Zusätzlich exponiert ein MCP stdio Server dieselben Tools für externe MCP‑Clients.
