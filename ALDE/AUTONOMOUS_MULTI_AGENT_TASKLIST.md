# Konkrete Task-Liste (Autonomous Multi-Agent / Quasi-Unsupervised)

## Scope
Diese Liste ist direkt auf ALDE zugeschnitten und priorisiert in `P0 -> P1 -> P2`.
Jede Task nennt Ziel-Datei(en), konkrete Funktion(en) und Done-Kriterien.

## P0 - Instrumentierung und sichere Basis

### 1) Event-Schema definieren
- Dateien:
  - `alde/learning_signals.py` (neu)
- Tasks:
  - Erstelle Dataclasses/TypedDicts:
    - `QueryEvent`
    - `OutcomeEvent`
    - `PolicySnapshot`
  - Implementiere Validator:
    - `def validate_query_event(evt: dict) -> tuple[bool, str]: ...`
    - `def validate_outcome_event(evt: dict) -> tuple[bool, str]: ...`
- Done:
  - Ungueltige Events werden mit Fehlergrund abgewiesen.
  - Unit-Tests fuer Pflichtfelder vorhanden.

### 2) Event-Logger mit JSONL
- Dateien:
  - `alde/policy_store.py` (neu)
- Tasks:
  - Implementiere Logger:
    - `def append_event(event_type: str, payload: dict, base_dir: str | None = None) -> str: ...`
  - Dateiziele:
    - `AppData/generated/learning_events.jsonl`
    - optional rotiert pro Tag: `learning_events_YYYYMMDD.jsonl`
- Done:
  - Atomic append (kein Datenverlust bei Parallelzugriffen).
  - Logger scheitert fail-soft (App laeuft weiter, Fehler wird geloggt).

### 3) Tool-Hooks in Retrieval-Pfad
- Dateien:
  - `alde/tools.py`
- Tasks:
  - Vor Retrieval in `memorydb`/`vectordb`:
    - `QueryEvent` schreiben (query, k, tool, agent-label, timestamp)
  - Nach Retrieval:
    - Ergebnis-Metadaten und Latenz in `OutcomeEvent` schreiben
  - Helper-Funktionen:
    - `def _emit_query_event(...): ...`
    - `def _emit_outcome_event(...): ...`
- Done:
  - >=95% der erfolgreichen Tool-Calls erzeugen beide Events.
  - Keine Regression in bestehendem Tool-Output.

### 4) Reward-Heuristik (unsupervised proxy)
- Dateien:
  - `alde/learning_signals.py`
- Tasks:
  - Implementiere:
    - `def compute_reward(query_evt: dict, outcome_evt: dict) -> float: ...`
  - Startregeln:
    - +1.0 kein retry/rephrase
    - -1.0 bei Tool-Error/Timeout
    - +0.5 bei Quellreuse in finaler Antwort (falls messbar)
- Done:
  - Reward in OutcomeEvent persistiert.
  - Unit-Tests fuer Kernregeln.

### 5) Baseline-Metrikreport
- Dateien:
  - `alde/offline_eval.py` (neu)
- Tasks:
  - Implementiere CLI:
    - `python -m alde.offline_eval --from-events AppData/generated/learning_events.jsonl`
  - Kennzahlen:
    - error_rate, timeout_rate, avg_latency_ms, topk_hit_proxy, followup_proxy
  - Report-Ausgabe:
    - `AppData/generated/metrics_latest.json`
- Done:
  - Report wird stabil aus Event-Log erzeugt.

## P1 - Adaptive Policy in Runtime

### 6) Retrieval-Policy Modul
- Dateien:
  - `alde/retrieval_policy.py` (neu)
- Tasks:
  - Definiere Policy-Struktur:
    - `PolicyConfig`, `IntentStats`, `SourceStats`
  - Implementiere:
    - `def choose_params(query: str, tool: str, agent: str, base_k: int) -> dict: ...`
    - Rueckgabe: `k`, `fetch_k`, `rerank_method`, `metadata_filters`
- Done:
  - Safe bounds: `k` und `fetch_k` immer in erlaubtem Bereich.

### 7) Policy-Integration in `vstores.py`
- Dateien:
  - `alde/vstores.py`
- Tasks:
  - Vor `similarity_search_with_score` policy anwenden.
  - `fetch_k` und Rerank-Modus aus Policy lesen.
  - Optional metadata pre-filter vorbereiten (falls Feld vorhanden).
- Done:
  - Query-Verhalten adaptiv, aber kompatibel mit bisherigen Defaults.

### 8) Policy-Persistenz und Versionierung
- Dateien:
  - `alde/policy_store.py`
- Tasks:
  - Implementiere:
    - `def load_policy(path: str) -> dict: ...`
    - `def save_policy(policy: dict, version_tag: str) -> str: ...`
    - `def get_active_policy() -> dict: ...`
  - Speicherorte:
    - `AppData/generated/policies/policy_v*.json`
    - `AppData/generated/policies/active_policy.json`
- Done:
  - Rollback moeglich durch Wechsel von `active_policy.json`.

### 9) Canary-Schalter
- Dateien:
  - `alde/tools.py`
  - `alde/chat_completion.py`
- Tasks:
  - Env Flags:
    - `AI_IDE_POLICY_CANARY` (0.0..1.0)
    - `AI_IDE_POLICY_ENABLE` (0/1)
  - Session-basiertes Sampling fuer neue Policy.
- Done:
  - Canary-only Aktivierung ohne Code-Neustart.

## P2 - Multi-Agent-Autonomie

### 10) Shared Episodic Memory
- Dateien:
  - `alde/policy_store.py`
  - optional `alde/rag_core.py` oder `alde/tools.py`
- Tasks:
  - Implementiere kurzlebigen Speicher (TTL):
    - `def write_episode(key: str, value: dict, ttl_s: int = 86400) -> None: ...`
    - `def read_episode(key: str) -> dict | None: ...`
  - Keying z. B. `intent_cluster + tool + agent`
- Done:
  - Episoden beeinflussen Parameterwahl messbar.

### 11) Agent Credit Assignment
- Dateien:
  - `alde/learning_signals.py`
- Tasks:
  - Implementiere:
    - `def assign_credit(chain: list[dict], reward: float) -> list[dict]: ...`
  - Splits:
    - Router-Agent
    - Retrieval-Agent
    - Antwort-Agent
- Done:
  - Reward-Aufteilung pro Agent wird gespeichert und reportbar.

### 12) Unsupervised Intent Clustering
- Dateien:
  - `alde/retrieval_policy.py`
  - optional `alde/embed_tool.py` oder eigene Embedding-Helper
- Tasks:
  - Embedding pro Query erzeugen.
  - Online-Clustering (einfacher Start: centroid nearest + threshold).
  - Policy-Stats pro Cluster statt global pflegen.
- Done:
  - Neue Query wird Cluster zugeordnet; Cluster-ID landet im Event.

## Tests und QA (querliegend)

### 13) Unit-Tests
- Dateien:
  - `alde/Tests/test_learning_signals.py` (neu)
  - `alde/Tests/test_retrieval_policy.py` (neu)
- Tasks:
  - Event-Validation
  - Reward-Regeln
  - Policy-Bounds
  - Fallback bei defekter Policy-Datei
- Done:
  - Tests laufen lokal gruen.

### 14) Integrations-Tests
- Dateien:
  - `alde/Tests/test_memorydb_policy_integration.py` (neu)
- Tasks:
  - Simulierter memorydb-call mit Event-Emission.
  - Canary on/off Verhalten pruefen.
- Done:
  - Kein Bruch im bisherigen Tool-Protokoll.

## Betriebs-Checkliste

### 15) Feature Flags (default sicher)
- `AI_IDE_POLICY_ENABLE=0`
- `AI_IDE_POLICY_CANARY=0.0`
- `AI_IDE_POLICY_LOG_EVENTS=1`

### 16) Rollout
- Step 1: Nur Logging + Reports (kein adaptives Verhalten)
- Step 2: Canary 10%
- Step 3: 50%
- Step 4: 100% nach KPI-Freigabe

## Akzeptanzkriterien gesamt
- Keine Regression fuer bestehende `memorydb`/`vectordb` Calls.
- Messbare Verbesserung in mindestens einem KPI nach Canary-Phase:
  - weniger Follow-up/Rephrase
  - bessere Hit@k-Proxies
  - stabile Latenz
