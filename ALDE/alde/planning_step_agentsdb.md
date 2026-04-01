# Zwischenziel

## Fokus
Das naechste Zwischenziel fuer die agents_db Pipeline ist kein weiterer Einzelbaustein,
sondern eine durchgaengige End-to-End Strecke:

1. Dokument aufnehmen
2. Dokument parsen
3. Parser-Ergebnis persistieren
4. Knowledge-Objekte ableiten
5. MongoDB / Retrieval-Index befuellen
6. Retrieval auf denselben Daten pruefen

Der bestehende Workflow fuer Dokumentaufnahme, Parsing und Basis-Persistenz existiert bereits.
Der Schwerpunkt liegt jetzt auf dem Anschluss der nachgelagerten Knowledge-Stufen.

## End-to-End Pipeline

### Stage 1: Input / Ingestion
Eingang:

- PDF oder Textdokument
- Dispatcher-Metadaten
- correlation_id / content_sha256

Verantwortliche Objekte:

- DocumentDispatcherService
- DocumentRepository
- DispatcherDocumentDbRepository

Output:

- raw_text
- file metadata
- dispatcher status record

### Stage 2: Parsing / Normalisierung
Ziel:

- Aus raw_text wird ein stabiles parser_result Objekt.
- Das parser_result bleibt die kanonische fachliche Zwischenform fuer den weiteren Build.

Erwarteter Output:

- job_posting oder generisches object_result
- parse metadata
- db_updates
- handoff_metadata

Verantwortliche Objekte:

- ParserAgentService
- ObjectResultBuilder

### Stage 3: Persistenz der operativen Wahrheit
Ziel:

- Parser-Ergebnis wird in die operative DB geschrieben.
- Dispatcher-Status und Objekt-Store bleiben synchron.

Persistierte Stores:

- job_postings_db.json oder entsprechender object store
- dispatcher_doc_db.json

Verantwortliche Objekte:

- ObjectStoreRepository
- DispatcherStateRepository
- UpsertObjectRecordService

Ergebnis:

- Ein Dokument ist fachlich verarbeitet und technisch als processed markiert.

### Stage 4: Build des Knowledge-Datasets
Ziel:

- Aus dem parser_result wird ein vollstaendiges Knowledge-Dataset erzeugt.
- Diese Stufe trennt operative Verarbeitung von Knowledge-Projektion.

Abzuleitende Objekte:

- NamespaceObject
- DocumentObject
- BlockObject
- EntityObject
- RelationObject
- EmbeddingObject
- IndexObject

Empfohlene Service-Objekte:

- KnowledgeDatasetBuilderService
- BlockProjectionService
- EntityProjectionService
- RelationProjectionService
- EmbeddingProjectionService

Ergebnis:

- ein serialisierbares knowledge_dataset fuer Persistenz und Demo-Seeding

### Stage 5: MongoDB Projection Layer
Ziel:

- Das erzeugte knowledge_dataset wird in das MongoDB Dokumente-Backend gespiegelt.
- MongoDB wird die dokumentorientierte Wahrheit fuer Namespace, Dokument, Blocks,
  Entitaeten, Relationen und Retrieval-Runs.

Collections / Layer:

- knowledge_namespaces
- documents
- entities
- entity_relations
- embeddings
- retrieval_runs

Verantwortliche Objekte:

- MongoKnowledgeRepository
- MongoKnowledgeService
- MongoKnowledgePipelineService

Ergebnis:

- Ein verarbeiteter Record ist nicht nur im JSON-Store, sondern auch im Mongo-Knowledge-Layer verfuegbar.

### Stage 6: Index / Retrieval
Ziel:

- Blocks und Dokumente muessen aus derselben Knowledge-Projektion auffindbar sein.
- Retrieval darf nicht auf einem separaten, fachlich losgeloesten Build-Pfad basieren.

Retrieval Inputs:

- query_text
- namespace_id
- optional filters

Retrieval Output:

- document hits
- block hits
- entity hits
- relation context

Verantwortliche Objekte:

- RetrievalRunService
- HybridRetriever
- VectorIndexGateway

## Zielbild der Datenfluss-Kette

```text
document file
-> dispatcher scan
-> parser agent
-> object_result
-> operational persistence
-> knowledge_dataset build
-> Mongo knowledge projection
-> embeddings / index update
-> retrieval query
-> grounded result
```

## Strukturabbildung der vorhandenen Klassen

### Service-Layer in tools.py
Diese Klassen bilden die operative Pipeline und den Runtime-Zugriff auf Persistenz und Dispatcher-Logik:

- `MongoDocumentBackend`
	Verantwortet den Backend-Zugriff fuer dokumentorientierte operative Stores.
- `DocumentRepository`
	Kapselt `load_db`, `save_db`, `upsert_db`, `persist_document`, `get_document` und Dispatcher-Zugriff.
- `RequestObjectResolutionService`
	Loest Request-Payloads in generische `object_name` und `object_result` Bindings auf.
- `DocumentObjectService`
	Haelt die objektbezogenen Persistenz-Operationen fuer `store_object_result` und `ingest_object`.
- `ActionRequestService`
	Fuehrt deterministische Action-Requests aus und verbindet Request-Schema mit den Service-Operationen.
- `DocumentDispatchService`
	Orchestriert Scan, Fingerprinting, Dispatcher-Status und Parser-Handoffs.

### Objekt- und Knowledge-Layer in agents_dbs.py
Diese Klassen bilden das kanonische Knowledge-Modell und die Mongo-Projektion:

- Objektklassen:
	`NamespaceObject`, `DocumentObject`, `BlockObject`, `EntityObject`, `EntityRelationObject`, `EmbeddingObject`, `RetrievalRunObject`, `DispatcherRunObject`
- Hilfsobjekte:
	`EntityMentionObject`, `EntityAliasObject`, `RelationEvidenceObject`
- Repository- und Serviceklassen:
	`KnowledgeRepository`, `KnowledgeObjectService`, `PipelineService`, `ObjectMappingService`

### Bruecke zwischen beiden Modulen
Die eigentliche Laufzeitbruecke ist bereits vorhanden:

- `DocumentRepository.persist_document(...)` speichert die operative Wahrheit.
- Der darueberliegende Objekt-/Action-Pfad in `tools.py` ruft danach `sync_parser_result_to_mongodb_knowledge(...)` auf.
- In `agents_dbs.py` mappt `ObjectMappingService.store_mapped_object(...)` das Parser-Ergebnis auf `DocumentObject`, `BlockObject`, `EntityObject` und `EntityRelationObject`.
- Retrieval-Events werden ueber `sync_retrieval_run_to_mongodb_knowledge(...)` in `RetrievalRunObject` projiziert.

Damit ist die Architektur bereits als reale Kette vorhanden, aber noch nicht als explizite Struktur- und Workflow-Konfiguration persistiert.

## Was als Naechstes konkret fehlt

### 1. Kanonisches knowledge_dataset Schema festziehen
Es braucht ein einziges internes Austauschformat zwischen Parser-Persistenz und Mongo-Projektion.

Minimal erforderlich:

- dataset_metadata
- source document metadata
- db_record snapshot
- mongodb_objects
- entity_relation_graph

Ohne dieses feste Schema bleibt jeder nachgelagerte Builder implizit und fragil.

### 2. Builder-Schritt als eigene Service-Schicht isolieren
Der Build von Namespace-, Dokument-, Block-, Entity- und Relation-Objekten darf nicht in Parser,
Dispatcher oder Seed-Skripten verstreut sein.

Empfohlen:

- KnowledgeDatasetBuilderService.build_object(object_result, object_name)

Dadurch bleibt die Verantwortung sauber:

- Parser extrahiert
- Store persistiert
- Builder bzw. Mapping-Service projiziert
- Mongo service speichert

### 3. Embedding-Strategie an den Build koppeln
Embeddings muessen aus denselben BlockObjects entstehen, die auch im Mongo-Dokument landen.

Nicht wuenschenswert:

- separater Chunking-Pfad
- separater Embedding-Pfad ohne stabile block_id

Ziel:

- jede EmbeddingObject Instanz referenziert document_id oder block_id eindeutig

### 4. End-to-End Orchestrator definieren
Es fehlt eine klar benannte Orchestrierungsfunktion fuer den gesamten Pfad.

Empfohlene Signatur:

```python
def process_object_to_knowledge_dataset(object_name: str, object_result: dict[str, Any]) -> dict[str, Any]:
	...
```

Diese Funktion sollte:

1. object_result validieren
2. operative Persistenz bestaetigen
3. knowledge_dataset bzw. Mapping-Projektion bauen
4. optional embeddings / index aktualisieren
5. Ergebnis-Report zurueckgeben

Pragmatischer Ist-Zustand:

- Die operative Persistenz liegt in `tools.py`.
- Die Knowledge-Projektion liegt in `agents_dbs.py`.
- Die neue Persistierung in `agents_pconfig.py` soll genau diese Trennung als deklarative Struktur und Workflow-Blueprint festhalten.

### 5. Retrieval-Validierung als Abschluss des Pipelineschritts
Die Pipeline gilt erst dann als end-to-end fertig, wenn ein Query gegen das frisch gespeicherte
Dokument erfolgreiche Treffer liefert.

Minimaler Validierungsfall:

- input document verarbeiten
- knowledge_dataset speichern
- retrieval query mit Jobtitel oder Skill ausfuehren
- document_id oder block_id im Ergebnis bestaetigen

## Priorisierte naechste Schritte

### Kurzfristig
1. `build_demo_job_posting_knowledge_dataset()` als kanonischen Demo-Builder finalisieren.
2. `build_demo_seed_objects()` auf dasselbe Dataset-Schema ausrichten.
3. Die Klassenstruktur `tools.py -> agents_dbs.py` als persistierte Konfiguration in `agents_pconfig.py` ablegen.
4. Den End-to-End Workflow derselben Struktur in `agents_pconfig.py` als Blueprint ablegen.
5. `process_object_to_knowledge_dataset(object_name, object_result)` als End-to-End Einstieg einfuehren.
6. Einen kleinen Retrieval-Smoke-Test fuer ein frisch projiziertes Dokument implementieren.

### Danach
1. Parser-unabhaengig auf generische `object_name` Pipeline erweitern.
2. Hybrid Retrieval aus document + block + entity + relation konsolidieren.
3. Runtime-Metriken fuer projection_success, embedding_success und retrieval_success mitloggen.

## Definition of Done fuer das Zwischenziel
Das Zwischenziel ist erreicht, wenn ein einzelnes Job-Posting durchgaengig diesen Pfad laeuft:

1. PDF wird aufgenommen.
2. Parser liefert ein stabiles object_result.
3. Objekt-Store und Dispatcher-Store sind aktualisiert.
4. Knowledge-Dataset wird erzeugt.
5. MongoDB enthaelt Namespace-, Dokument-, Block-, Entity- und Relation-Objekte.
6. Embeddings und Indexeintraege sind erstellt.
7. Eine Retrieval-Abfrage liefert das neue Dokument oder einen zugehoerigen Block zurueck.
8. Die Struktur und der Workflow sind in `agents_pconfig.py` als persistierte Konfiguration dokumentiert.


## Persistierte Konfiguration
Die Struktur und der Workflow sollen in `agents_pconfig.py` unter eigenen Config-Namen abgelegt werden, damit klar bleibt:

- welche Service-Klassen aus `tools.py` welche Pipeline-Stufe besitzen
- welche Objekt-Klassen aus `agents_dbs.py` das kanonische Zielmodell bilden
- welche Workflow-Stages operativ, welche projektiv und welche validierend sind

Diese beiden Funktionen sollten als Referenz fuer das kanonische Dataset und fuer reproduzierbares
Seeding dienen, nicht als parallele Sonderlogik neben der eigentlichen Pipeline.