from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "ALDE"
for import_root in (REPO_ROOT, PACKAGE_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

try:
    from ALDE.alde.agents_dbs import (
        MongoKnowledgeRepository,
        MongoKnowledgeService,
        build_demo_seed_objects,
        load_mongodb_runtime_config_from_env,
        load_mongodb_pipeline_service,
    )
except Exception:
    from alde.knowledge_mongodb_example import (  # type: ignore
        MongoKnowledgeRepository,
        MongoKnowledgeService,
        build_demo_seed_objects,
        load_mongodb_runtime_config_from_env,
        load_mongodb_pipeline_service,
    )


class MongoKnowledgeSeedRunner:
    def __init__(self, mongo_uri: str, database_name: str) -> None:
        self._mongo_uri = mongo_uri
        self._database_name = database_name

    def load_repository(self) -> MongoKnowledgeRepository:
        repository = MongoKnowledgeRepository.create_from_uri(self._mongo_uri, self._database_name)
        repository.ensure_index_objects()
        return repository

    def load_service(self) -> MongoKnowledgeService:
        return MongoKnowledgeService(self.load_repository())

    def store_demo_objects(self) -> dict[str, Any]:
        service = self.load_service()
        seed_objects = build_demo_seed_objects()
        service.store_namespace_object(seed_objects["namespace"])
        service.store_entity_object(seed_objects["entity"])
        service.store_document_object(seed_objects["document"])
        service.store_relation_object(seed_objects["relation"])
        service.store_dispatcher_run_object(seed_objects["dispatcher_run"])
        service.store_retrieval_run_object(seed_objects["retrieval_run"])
        return {
            "namespace_id": seed_objects["namespace"].id,
            "document_id": seed_objects["document"].id,
            "dispatcher_run_id": seed_objects["dispatcher_run"].id,
            "retrieval_run_id": seed_objects["retrieval_run"].id,
        }

    def store_pipeline_examples(self) -> dict[str, Any] | None:
        runtime_config = load_mongodb_runtime_config_from_env()
        if runtime_config is None:
            return None
        pipeline_service = load_mongodb_pipeline_service(runtime_config)
        document_result = pipeline_service.store_document_result(
            correlation_id="seed-doc-0001",
            obj_name="job_postings",
            stored_record={
                "source_agent": "seed_runner",
                "job_posting": {
                    "job_title": "AgentDB Knowledge Pipeline Engineer",
                    "company_name": "Example GmbH",
                    "summary": "Builds AgentDB-compatible mirrors for ALDE runtime data.",
                },
                "parse": {"raw_text": "Builds AgentDB-compatible mirrors for ALDE runtime data."},
                "db_updates": {"processing_state": "processed", "processed": True},
            },
            handoff_metadata={"source_agent": "seed_runner"},
            handoff_payload={"agent_label": "seed_runner"},
            db_path="AppData/job_postings_db.json",
        )
        dispatcher_result = pipeline_service.store_dispatcher_status(
            correlation_id="seed-doc-0001",
            dispatcher_record={
                "processing_state": "processed",
                "processed": True,
                "source_agent": "seed_runner",
            },
            db_path="AppData/dispatcher_db.json",
        )
        retrieval_result = pipeline_service.store_retrieval_run(
            tool_name="vectordb",
            query_event={
                "event_id": "seed-retrieval-0001",
                "query_text": "AgentDB pipeline engineer",
                "k": 3,
                "session_id": os.getenv("AI_IDE_SESSION_ID", "seed-session"),
                "agent": "seed_runner",
                "policy_snapshot": {"fetch_k": 0, "rerank_method": "mmr", "metadata_filters": {}},
            },
            outcome_event={
                "query_event_id": "seed-retrieval-0001",
                "success": True,
                "latency_ms": 1,
                "reward": 1.0,
            },
            retrieval_result=[
                {
                    "document_id": "doc_job_0001",
                    "title": "Senior Python Engineer",
                    "score": 0.93,
                    "source": "https://example.org/jobs/0001",
                },
            ],
        )
        return {
            "document_result": document_result,
            "dispatcher_result": dispatcher_result,
            "retrieval_result": retrieval_result,
        }

    def run(self) -> dict[str, Any]:
        summary = {"demo_seed": self.store_demo_objects()}
        pipeline_summary = self.store_pipeline_examples()
        if pipeline_summary is not None:
            summary["pipeline_seed"] = pipeline_summary
        return summary


def _load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the optional ALDE AgentDB knowledge mirror.")
    parser.add_argument(
        "--mongo-uri",
        default=os.getenv("AI_IDE_KNOWLEDGE_MONGO_URI", "mongodb://localhost:27017"),
        help="MongoDB connection URI.",
    )
    parser.add_argument(
        "--database-name",
        default=os.getenv("AI_IDE_KNOWLEDGE_MONGO_DB", "alde_knowledge"),
        help="MongoDB database name.",
    )
    return parser.parse_args()


def main() -> int:
    args = _load_args()
    runner = MongoKnowledgeSeedRunner(args.mongo_uri, args.database_name)
    print(json.dumps(runner.run(), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())