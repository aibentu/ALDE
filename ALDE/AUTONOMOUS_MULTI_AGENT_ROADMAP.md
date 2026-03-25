# Autonomous Multi-Agent Learning Roadmap (ALDE)

## 1) Zielbild
Dieses Roadmap-Dokument beschreibt, wie ALDE von regelbasiertem Retrieval zu einem adaptiven, autonomen Multi-Agent-System weiterentwickelt wird, das aus Interaktionen lernt (unsupervised), ohne die Stabilitaet des aktuellen Workflows zu verlieren.

Aktueller Ausgangspunkt fuer diese Roadmap:
- Die Agent-Laufzeit ist bereits manifestbasiert zentralisiert.
- `alde/agents_config.py` ist die Source of Truth fuer Runtime-Instruktionen, Rollen, Skill-Profile, Tool-Policy und Workflow-Definitionen.
- `alde/agents_factory.py` und `alde/chat_completion.py` konsumieren diese Definitionen bereits fuer Routing, Tool-Ausfuehrung, History-Shaping und scoped instance reuse.
- Diese Roadmap beschreibt die naechste Ausbaustufe: adaptive Learning- und Policy-Schichten auf dem bestehenden Runtime-Fundament.

Leitziele:
- Besseres Retrieval durch adaptive Strategiewahl (k, fetch_k, rerank, source-prior).
- Kontextgenauere Antworten durch reichere Metadaten und agentenuebergreifende Signalspeicherung.
- Autonomes Lernen ueber Reward-Signale aus realen Sessions (ohne manuelle Labels als Pflicht).
- Sichere, reproduzierbare Weiterentwicklung per Offline-Evaluation und Canary-Rollout.

## 2) Ausgangslage im aktuellen Code
Relevante Komponenten:
- `alde/vstores.py`: Indexaufbau, Retrieval, Reranking, Manifest, Query-Output.
- `alde/tools.py`: Tool-Entry-Points (`memorydb`, `vectordb`) und Runtime-Tool-Adapter.
- `alde/agents_config.py`: Manifeste, Rollen, Skill-Profile, Tool-Policy und Workflow-Schemas.
- `alde/agents_registry.py`, `alde/agents_factory.py`: Manifest-gebundenes Routing, Tool-Ausfuehrung, Workflow-Scopes.
- `alde/chat_completion.py`, `alde/ai_ide_v1756.py`: Tool-Call-Ausfuehrung, Session-Verlauf und Runtime-Metadaten.
- `AppData/VSM_3_Data/history.json`: wertvolle Lernquelle fuer erfolgreiche/erfolglose Retrievals.

## 3) Architekturziel (Learning Loop)

Datenfluss:
1. User-Request -> Router entscheidet Agent + Tool.
2. Retrieval liefert Kandidaten + Scores + Metadaten.
3. Antwort wird generiert.
4. Session-Signale werden extrahiert (Follow-up, Korrekturen, erneute Suche, Tool-Erfolg).
5. Learning-Engine aktualisiert Strategietabellen und Prior-Gewichte.
6. Naechste Anfrage nutzt adaptive Parameter.

Neue Kernmodule:
- `alde/retrieval_policy.py`: entscheidet dynamisch `k`, `fetch_k`, rerank, source boosts.
- `alde/learning_signals.py`: extrahiert Reward-Signale aus Chat-/Tool-Verlauf.
- `alde/policy_store.py`: persistiert erlernte Policy-States (JSON/SQLite).
- `alde/offline_eval.py`: Replay/Evaluation auf historischen Logs.

## 4) Datenmodell fuer quasi-unsupervised Learning

### 4.1 QueryEvent
Pflichtfelder:
- `event_id`, `session_id`, `agent`, `tool`, `query_text`, `timestamp`
- `policy_snapshot`: `{k, fetch_k, rerank_method, source_boosts, metadata_filters}`
- `retrieval_result`: Top-N mit `source`, `score`, `metadata_keys`
- `latency_ms`

### 4.2 OutcomeEvent
Automatisch ableitbar:
- `followup_within_60s` (bool)
- `query_rephrase_count`
- `tool_retry_count`
- `answer_used_signal` (heuristisch): keine unmittelbare Korrektur + kein erneuter identischer Abruf
- `explicit_feedback` (optional): up/down

### 4.3 Reward-Schema
Start-Heuristik (keine manuellen Labels noetig):
- +1.0 wenn keine Rephrase und kein Retry
- +0.5 wenn Top-1 Quelle in finaler Antwort referenziert wird
- -0.7 bei direktem Follow-up "nicht gefunden/falsch"
- -1.0 bei Tool-Fehler oder Timeout

Reward glatten:
- Exponential Moving Average pro `(intent_cluster, tool, agent)`

## 5) Adaptive Retrieval Policy

Policy-Features:
- Query-Laenge, Sprache, erkannte Entitaeten (Person, Firma, Datum, Ort).
- Agent-Typ (`_data_dispatcher`, `_cover_letter_agent`, ...).
- Historische Erfolgsrate pro Quelle und Metadatenprofil.

Policy-Aktionen:
- `k` dynamisch waehlen (z. B. 3..15)
- `fetch_k` dynamisch waehlen (z. B. 10..60)
- Rerank-Modus: `none | mmr | crossencoder`
- Metadatenfilter auto-setzen (`thread-id`, `date range`, `doc_type`)

Sicherheitskorridor:
- Harte Bounds fuer alle Parameter.
- Fallback auf konservative Baseline bei Unsicherheit.

## 6) Multi-Agent-spezifische Erweiterungen

### 6.1 Shared Episodic Memory
- Zentraler, agentenuebergreifender Speicher fuer kurzlebige Erkenntnisse:
  - "welche Quelle hat fuer diesen Intent funktioniert"
  - "welcher Agent-Transfer war erfolgreich"
- TTL-basiert (z. B. 24-72h), um Drift zu reduzieren.

### 6.2 Agent Credit Assignment
- Reward nicht nur global, sondern anteilig auf Agenten verteilen:
  - Router-Entscheidung
  - Retrieval-Agent
  - Antwort-Agent
- Ermoeglicht gezielte Verbesserung von Routing vs. Retrieval.

### 6.3 Unsupervised Intent Clustering
- Embeddings fuer Queries bilden und in Clustern speichern.
- Policy pro Cluster lernen statt nur global.
- Neue Cluster starten mit Baseline und adaptieren nach wenigen Events.

## 7) Guardrails und Governance

Pflicht-Guardrails:
- Kein unkontrolliertes Selbst-Ueberschreiben produktiver Policies.
- Policy-Updates nur in Versionen (`policy_vN.json`) + Rollback.
- Canary-Phase: nur x% Sessions mit neuer Policy.
- Drift-Alarm bei KPI-Abfall > Schwellwert.

Datenschutz/Sicherheit:
- PII-Minimierung in Lern-Events.
- Hashing fuer sensible Felder (`email`, `telefon`) wenn moeglich.
- Konfigurierbare Retention fuer Logs/Signals.

## 8) KPI-Set (ab Tag 1 messen)

Online:
- Retrieval latency p50/p95
- Hit@k
- Follow-up rate innerhalb 60s
- Tool error rate
- Timeout rate

Qualitaet:
- Rephrase rate
- Answer acceptance proxy
- Source precision@k

Stabilitaet:
- Policy rollback count
- Canary failure rate

## 9) Umsetzungsplan in 4 Phasen

### Phase 1 (1-2 Wochen): Instrumentierung
Deliverables:
- `learning_events.jsonl` Writer in `alde/tools.py`, `alde/agents_factory.py` und der Tool-Call-Pipeline.
- Query/Outcome Events mit minimalem Schema.
- KPI-Dashboard als einfache Reports (`/AppData/generated/metrics_*.json`).

Akzeptanzkriterien:
- >=95% Tool-Calls erzeugen valides Event.
- Kein Einfluss auf bestehende Antworten/Protokolle.

### Phase 2 (2-3 Wochen): Offline-Lernen + Replay
Deliverables:
- `alde/offline_eval.py` (Replay aus `history.json` + `learning_events.jsonl`).
- Baseline vs. adaptive Policy Vergleich.
- Erste Policy-Datei `policy_v1.json`.

Akzeptanzkriterien:
- Offline >=5% Verbesserung in Follow-up rate oder Hit@k.
- Keine signifikante Latenzverschlechterung (>10%).

### Phase 3 (2 Wochen): Online-Canary
Deliverables:
- Canary-Switch (z. B. `AI_IDE_POLICY_CANARY=0.1`).
- Runtime-Policy-Loader + Safe-Fallback in `retrieval_policy.py`.
- Rollback-Mechanismus auf letzte stabile Version.

Akzeptanzkriterien:
- Canary stabil ueber 7 Tage.
- Kein Anstieg kritischer Fehler.

### Phase 4 (fortlaufend): Agentic Autonomy
Deliverables:
- Shared episodic memory fuer Agenten.
- Credit assignment fuer Multi-Agent-Ketten.
- Clusterbasierte Policies pro Intent-Gruppe.

Akzeptanzkriterien:
- Messbar bessere Routing- und Retrieval-Entscheidungen pro Cluster.
- Weniger Korrektur- und Rephrase-Interaktionen.

## 10) Konkrete Backlog-Items (technisch)

P0:
- Add event schema + logger hooks (`tools.py`, `chat_completion.py`).
- Stabiler policy loader + fallback defaults.
- Unit tests fuer JSON schema und reward computation.

P1:
- Implement `retrieval_policy.py` + integration in `memorydb/vectordb` path.
- Implement `offline_eval.py` with report output.
- Add canary env flags.

P2:
- Intent clustering service.
- Agent credit assignment.
- Auto-tuning cadence (daily batch update).

## 11) Minimaler Start (diese Woche)
Sofort umsetzbar:
1. Learning-Events erfassen (ohne Verhalten zu aendern).
2. Reward-Heuristik rechnen und reporten.
3. Nur `k` und `fetch_k` adaptiv machen, alles andere fix.

Damit entsteht schnell ein sicherer Lernkreislauf, der bereits Nutzen liefert und spaeter zu vollwertiger autonomer Multi-Agent-Optimierung ausgebaut werden kann.
