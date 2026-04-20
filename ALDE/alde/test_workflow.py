from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import ALDE_Projekt.ALDE.alde.agents_ccomp as chat_mod
import alde.agents_configurator as agents_configurator
import alde.agents_factory as agents_factory
import ALDE_Projekt.ALDE.alde.agents_tools as tools_mod


SAMPLE_WORKFLOW_REQUEST = {
    "action": "generate_cover_letter",
    "job_posting": {
        "source": "text",
        "value": {"title": "Full Stack Software Engineer", "company": {"about": "Example Co"}},
    },
    "applicant_profile": {
        "source": "text",
        "value": {"profile_id": "profile:test", "preferences": {"language": "de"}},
    },
    "options": {
        "language": "de",
        "tone": "modern",
        "max_words": 350,
    },
}


class _DeterministicDispatcherChatComE:
    def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
        self._model = _model
        self._messages = list(_messages)
        self._tools = list(tools)

    def _response(self):
        message = SimpleNamespace(
            content=json.dumps(
                {
                    "cover_letter": {"full_text": "Sehr geehrtes Team,\n\nMotivation und Erfahrung."},
                    "quality": {"word_count": 5, "language": "de"},
                },
                ensure_ascii=False,
            ),
            tool_calls=None,
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _InMemoryMongoDocumentBackend:
    def __init__(self) -> None:
        self._collections: dict[tuple[str, str], dict[str, dict[str, object]]] = {}

    def _collection_name(self, *, db_name: str | None = None, obj_name: str | None = None) -> str:
        normalized_db_name = str(db_name or "").strip().lower()
        if normalized_db_name:
            return normalized_db_name
        return str(obj_name or "documents").strip() or "documents"

    def _bucket(self, *, collection_name: str, storage_key: str) -> dict[str, dict[str, object]]:
        return self._collections.setdefault((collection_name, storage_key), {})

    def load_db(
        self,
        *,
        storage_key: str,
        empty_db: dict[str, object],
        db_name: str | None = None,
        obj_name: str | None = None,
        root_key: str,
    ) -> dict[str, object]:
        collection_name = self._collection_name(db_name=db_name, obj_name=obj_name)
        bucket = self._bucket(collection_name=collection_name, storage_key=storage_key)
        loaded = json.loads(json.dumps(empty_db))
        loaded[root_key] = json.loads(json.dumps(bucket))
        return loaded

    def save_db(
        self,
        *,
        storage_key: str,
        db: dict[str, object],
        db_name: str | None = None,
        obj_name: str | None = None,
        root_key: str,
    ) -> None:
        collection_name = self._collection_name(db_name=db_name, obj_name=obj_name)
        bucket = self._bucket(collection_name=collection_name, storage_key=storage_key)
        bucket.clear()
        root_payload = db.get(root_key) if isinstance(db, dict) else None
        if isinstance(root_payload, dict):
            for record_id, record_value in root_payload.items():
                if isinstance(record_value, dict):
                    bucket[str(record_id)] = json.loads(json.dumps(record_value))

    def load_record(
        self,
        *,
        storage_key: str,
        record_id: str,
        db_name: str | None = None,
        obj_name: str | None = None,
    ) -> dict[str, object] | None:
        collection_name = self._collection_name(db_name=db_name, obj_name=obj_name)
        bucket = self._bucket(collection_name=collection_name, storage_key=storage_key)
        record = bucket.get(record_id)
        if not isinstance(record, dict):
            return None
        return json.loads(json.dumps(record))

    def upsert_record(
        self,
        *,
        storage_key: str,
        record_id: str,
        record_value: dict[str, object],
        db_name: str | None = None,
        obj_name: str | None = None,
    ) -> None:
        collection_name = self._collection_name(db_name=db_name, obj_name=obj_name)
        bucket = self._bucket(collection_name=collection_name, storage_key=storage_key)
        bucket[record_id] = json.loads(json.dumps(record_value))

    def delete_record(
        self,
        *,
        storage_key: str,
        record_id: str,
        db_name: str | None = None,
        obj_name: str | None = None,
    ) -> None:
        collection_name = self._collection_name(db_name=db_name, obj_name=obj_name)
        bucket = self._bucket(collection_name=collection_name, storage_key=storage_key)
        bucket.pop(record_id, None)


class TestWorkflowIntegration(unittest.TestCase):
    def setUp(self) -> None:
        chat_mod.ChatHistory._history_ = []
        agents_factory._WORKFLOW_SESSION_CACHE.clear()

    def test_cover_letter_request_uses_configured_forced_route(self) -> None:
        with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
            chat = chat_mod.ChatCom(
                _model="gpt-4o-mini",
                _input_text=json.dumps(SAMPLE_WORKFLOW_REQUEST, ensure_ascii=False),
                _name="test_workflow",
            )

        self.assertEqual(chat._forced_route["target_agent"], "_xworker")
        self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
        self.assertEqual(chat._forced_route["agent_response"]["job_name"], "cover_letter_writer")
        resolved_payload = chat._forced_route["agent_response"]["output"]
        self.assertEqual(resolved_payload["profile_result"]["profile"]["profile_id"], "profile:test")
        self.assertEqual(resolved_payload["profile_result"]["parse"]["language"], "de")
        self.assertEqual(resolved_payload["job_posting_result"]["job_posting"]["job_title"], "Full Stack Software Engineer")
        get_client.assert_not_called()

    def test_cover_letter_request_resolves_persisted_job_posting_before_routing(self) -> None:
        stored_request = {
            "action": "generate_cover_letter",
            "job_posting": {
                "source": "correlation_id",
                "value": "sha-stored-1",
            },
            "job_postings_db_path": "/tmp/job_postings.json",
            "applicant_profile": {
                "source": "text",
                "value": {"profile_id": "profile:test", "preferences": {"language": "de"}},
            },
            "options": {
                "language": "de",
                "tone": "modern",
                "max_words": 350,
            },
        }

        with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client, patch(
            "alde.tools.DOCUMENT_REPOSITORY.get_document",
            return_value={
                "agent": "job_posting_parser",
                "correlation_id": "sha-stored-1",
                "parse": {"is_job_posting": True},
                "job_posting": {"job_title": "Backend Engineer", "company_name": "Stored Co"},
                "db_updates": {"processing_state": "processed", "processed": True},
                "file": {"content_sha256": "sha-stored-1"},
                "link": {"thread_id": "thread-1", "message_id": "msg-1"},
            },
        ):
            chat = chat_mod.ChatCom(
                _model="gpt-4o-mini",
                _input_text=json.dumps(stored_request, ensure_ascii=False),
                _name="test_workflow",
            )

        self.assertEqual(chat._forced_route["target_agent"], "_xworker")
        self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
        resolved_payload = chat._forced_route["agent_response"]["output"]
        self.assertEqual(resolved_payload["job_posting_result"]["correlation_id"], "sha-stored-1")
        self.assertEqual(resolved_payload["job_posting_result"]["job_posting"]["job_title"], "Backend Engineer")
        self.assertNotIn("job_posting", resolved_payload)
        self.assertNotIn("job_postings_db_path", resolved_payload)
        self.assertEqual(resolved_payload["profile_result"]["profile"]["profile_id"], "profile:test")
        self.assertEqual(resolved_payload["profile_result"]["parse"]["language"], "de")
        get_client.assert_not_called()

    def test_cover_letter_request_with_structured_inputs_routes_directly_to_writer(self) -> None:
        ready_request = {
            "action": "generate_cover_letter",
            "job_posting_result": {
                "agent": "job_posting_parser",
                "correlation_id": "sha-ready-1",
                "job_posting": {"job_title": "Platform Engineer"},
            },
            "applicant_profile": {
                "source": "text",
                "value": {"profile_id": "profile:ready", "preferences": {"language": "en"}},
            },
            "options": {"language": "en", "tone": "direct", "max_words": 250},
        }

        with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
            chat = chat_mod.ChatCom(
                _model="gpt-4o-mini",
                _input_text=json.dumps(ready_request, ensure_ascii=False),
                _name="test_workflow",
            )

        self.assertEqual(chat._forced_route["target_agent"], "_xworker")
        self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
        resolved_payload = chat._forced_route["agent_response"]["output"]
        self.assertEqual(resolved_payload["job_posting_result"]["correlation_id"], "sha-ready-1")
        self.assertEqual(resolved_payload["profile_result"]["profile"]["profile_id"], "profile:ready")
        self.assertEqual(resolved_payload["profile_result"]["parse"]["language"], "en")
        get_client.assert_not_called()

    def test_cover_letter_request_with_profile_file_routes_directly_to_writer(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump({"profile_id": "profile:file", "preferences": {"language": "fr"}}, tmp, ensure_ascii=False)
            profile_path = tmp.name

        try:
            request = {
                "action": "generate_cover_letter",
                "job_posting": {
                    "source": "text",
                    "value": {"title": "API Engineer", "company": {"about": "Example Co"}},
                },
                "applicant_profile": {
                    "source": "file",
                    "value": profile_path,
                },
                "options": {"language": "fr", "tone": "formal", "max_words": 300},
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )

            self.assertEqual(chat._forced_route["target_agent"], "_xworker")
            self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
            resolved_payload = chat._forced_route["agent_response"]["output"]
            self.assertEqual(resolved_payload["profile_result"]["profile"]["profile_id"], "profile:file")
            self.assertEqual(resolved_payload["profile_result"]["parse"]["language"], "fr")
            self.assertEqual(resolved_payload["profile_result"]["profile"]["source_path"], profile_path)
            self.assertEqual(resolved_payload["job_posting_result"]["job_posting"]["job_title"], "API Engineer")
            get_client.assert_not_called()
        finally:
            os.unlink(profile_path)

    def test_cover_letter_request_with_profile_file_and_job_result_routes_directly_to_writer(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump({"profile_id": "profile:file-ready", "preferences": {"language": "it"}}, tmp, ensure_ascii=False)
            profile_path = tmp.name

        try:
            request = {
                "action": "generate_cover_letter",
                "job_posting_result": {
                    "agent": "job_posting_parser",
                    "correlation_id": "sha-file-ready",
                    "job_posting": {"job_title": "Systems Engineer"},
                },
                "applicant_profile": {
                    "source": "file",
                    "value": {"path": profile_path},
                },
                "options": {"language": "it", "tone": "precise", "max_words": 280},
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )

            self.assertEqual(chat._forced_route["target_agent"], "_xworker")
            self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
            resolved_payload = chat._forced_route["agent_response"]["output"]
            self.assertEqual(resolved_payload["profile_result"]["profile"]["profile_id"], "profile:file-ready")
            self.assertEqual(resolved_payload["profile_result"]["parse"]["language"], "it")
            self.assertEqual(resolved_payload["profile_result"]["profile"]["source_path"], profile_path)
            get_client.assert_not_called()
        finally:
            os.unlink(profile_path)

    def test_cover_letter_request_with_persisted_profile_routes_directly_to_writer(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(
                {
                    "schema": "profiles_db_v1",
                    "profiles": {
                        "profile:stored": {
                            "correlation_id": "profile:stored",
                            "source_agent": "profile_parser",
                            "parse": {"language": "es", "errors": [], "warnings": []},
                            "profile": {"profile_id": "profile:stored", "preferences": {"language": "es"}},
                        }
                    },
                },
                tmp,
                ensure_ascii=False,
            )
            profiles_db_path = tmp.name

        try:
            request = {
                "action": "generate_cover_letter",
                "job_posting": {
                    "source": "text",
                    "value": {"title": "Platform Engineer", "company": {"about": "Stored Co"}},
                },
                "applicant_profile": {
                    "source": "profile_id",
                    "value": "profile:stored",
                    "db_path": profiles_db_path,
                },
                "options": {"language": "es", "tone": "clear", "max_words": 320},
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )

            self.assertEqual(chat._forced_route["target_agent"], "_xworker")
            self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
            resolved_payload = chat._forced_route["agent_response"]["output"]
            self.assertEqual(resolved_payload["profile_result"]["correlation_id"], "profile:stored")
            self.assertEqual(resolved_payload["profile_result"]["profile"]["profile_id"], "profile:stored")
            self.assertEqual(resolved_payload["profile_result"]["parse"]["language"], "es")
            self.assertEqual(resolved_payload["job_posting_result"]["job_posting"]["job_title"], "Platform Engineer")
            get_client.assert_not_called()
        finally:
            os.unlink(profiles_db_path)

    def test_cover_letter_request_with_job_posting_file_routes_directly_to_writer(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as posting_tmp, tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as profile_tmp:
            posting_tmp.write("Support Engineer Rolle mit SQL, Kundenkontakt und ERP-Kontext.")
            posting_path = posting_tmp.name
            json.dump({"profile_id": "profile:file-job", "preferences": {"language": "de"}}, profile_tmp, ensure_ascii=False)
            profile_path = profile_tmp.name

        try:
            request = {
                "action": "generate_cover_letter",
                "job_posting": {
                    "source": "file",
                    "value": posting_path,
                },
                "applicant_profile": {
                    "source": "file",
                    "value": profile_path,
                },
                "options": {"language": "de", "tone": "modern", "max_words": 280},
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )

            self.assertEqual(chat._forced_route["target_agent"], "_xworker")
            self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
            resolved_payload = chat._forced_route["agent_response"]["output"]
            self.assertEqual(resolved_payload["job_posting_result"]["file"]["path"], posting_path)
            self.assertTrue(resolved_payload["job_posting_result"]["correlation_id"])
            self.assertIn("SQL", resolved_payload["job_posting_result"]["job_posting"]["raw_text"])
            self.assertEqual(resolved_payload["profile_result"]["profile"]["source_path"], profile_path)
            get_client.assert_not_called()
        finally:
            os.unlink(posting_path)
            os.unlink(profile_path)

    def test_cover_letter_request_with_persisted_profile_and_job_result_routes_directly_to_writer(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(
                {
                    "schema": "profiles_db_v1",
                    "profiles": {
                        "profile:stored-ready": {
                            "correlation_id": "profile:stored-ready",
                            "source_agent": "profile_parser",
                            "parse": {"language": "nl", "errors": [], "warnings": []},
                            "profile": {"profile_id": "profile:stored-ready", "preferences": {"language": "nl"}},
                        }
                    },
                },
                tmp,
                ensure_ascii=False,
            )
            profiles_db_path = tmp.name

        try:
            request = {
                "action": "generate_cover_letter",
                "job_posting_result": {
                    "agent": "job_posting_parser",
                    "correlation_id": "sha-profile-stored-ready",
                    "job_posting": {"job_title": "Site Reliability Engineer"},
                },
                "applicant_profile": {
                    "source": "profile_id",
                    "value": {"profile_id": "profile:stored-ready"},
                    "profiles_db_path": profiles_db_path,
                },
                "options": {"language": "nl", "tone": "sharp", "max_words": 260},
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )

            self.assertEqual(chat._forced_route["target_agent"], "_xworker")
            self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
            resolved_payload = chat._forced_route["agent_response"]["output"]
            self.assertEqual(resolved_payload["profile_result"]["correlation_id"], "profile:stored-ready")
            self.assertEqual(resolved_payload["profile_result"]["profile"]["profile_id"], "profile:stored-ready")
            self.assertEqual(resolved_payload["profile_result"]["parse"]["language"], "nl")
            get_client.assert_not_called()
        finally:
            os.unlink(profiles_db_path)

    def test_ready_cover_letter_forced_route_uses_structured_handoff(self) -> None:
        ready_request = {
            "action": "generate_cover_letter",
            "job_posting_result": {
                "agent": "job_posting_parser",
                "correlation_id": "sha-ready-2",
                "job_posting": {"job_title": "Support Engineer"},
            },
            "applicant_profile": {
                "source": "text",
                "value": {"profile_id": "profile:ready-2", "preferences": {"language": "de"}},
            },
            "options": {"language": "de", "tone": "modern", "max_words": 280},
        }

        chat = chat_mod.ChatCom(
            _model="gpt-4o-mini",
            _input_text=json.dumps(ready_request, ensure_ascii=False),
            _name="test_ready_handoff",
        )

        forced_route = dict(chat._forced_route)
        self.assertEqual(forced_route["target_agent"], "_xworker")
        self.assertEqual(forced_route["handoff_protocol"], "agent_handoff_v1")
        self.assertEqual(forced_route["handoff_schema"], "xplaner_to_xworker")
        self.assertEqual(forced_route["agent_response"]["handoff_to"], "_xworker")
        self.assertEqual(forced_route["agent_response"]["agent_label"], "_xplaner_xrouter")
        self.assertEqual(forced_route["agent_response"]["job_name"], "cover_letter_writer")
        self.assertEqual(forced_route["agent_response"]["output"]["job_posting_result"]["correlation_id"], "sha-ready-2")

    def test_store_job_posting_result_tool_supports_non_pdf_sources(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            result = json.loads(
                tools_mod.store_job_posting_result_tool(
                    job_posting_result={
                        "agent": "job_platform_ingest",
                        "correlation_id": "platform:job-42",
                        "parse": {"is_job_posting": True},
                        "job_posting": {
                            "job_title": "Remote Python Engineer",
                            "company_name": "Platform Co",
                        },
                    },
                    db_path=job_postings_db_path,
                    source_agent="job_platform_ingest",
                    source_payload={
                        "platform": "example_jobs",
                        "record_id": "job-42",
                        "url": "https://jobs.example.invalid/job-42",
                    },
                )
            )

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("platform:job-42", db_path=job_postings_db_path, obj_name="job_postings")
            self.assertTrue(result["ok"])
            self.assertEqual(result["correlation_id"], "platform:job-42")
            self.assertEqual(stored["job_posting"]["job_title"], "Remote Python Engineer")
            self.assertEqual(stored["parse"]["is_job_posting"], True)
        finally:
            os.unlink(job_postings_db_path)

    def test_store_job_posting_result_tool_includes_knowledge_sync_result(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            with patch.object(
                tools_mod,
                "sync_parser_result_to_mongodb_knowledge",
                return_value={
                    "ok": True,
                    "stored": True,
                    "object_name": "job_posting",
                    "entity_count": 4,
                    "relation_count": 3,
                },
            ) as sync_mock:
                result = json.loads(
                    tools_mod.store_job_posting_result_tool(
                        job_posting_result={
                            "agent": "job_platform_ingest",
                            "correlation_id": "platform:job-44",
                            "parse": {"is_job_posting": True},
                            "job_posting": {
                                "job_title": "Knowledge Graph Engineer",
                                "company_name": "Platform Co",
                                "requirements": {
                                    "technical_skills": ["Python", "Neo4j"],
                                    "languages": ["Deutsch"],
                                },
                            },
                        },
                        db_path=job_postings_db_path,
                        source_agent="job_platform_ingest",
                        source_payload={"platform": "example_jobs", "record_id": "job-44"},
                    )
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["knowledge_sync"]["stored"])
            self.assertEqual(result["knowledge_sync"]["entity_count"], 4)
            self.assertEqual(sync_mock.call_args.kwargs["object_name"], "job_postings")
            self.assertEqual(sync_mock.call_args.kwargs["correlation_id"], "platform:job-44")
        finally:
            os.unlink(job_postings_db_path)

    def test_store_job_posting_result_tool_uses_mongo_backend_as_primary_store(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            mongo_backend = _InMemoryMongoDocumentBackend()
            with patch.object(tools_mod.DOCUMENT_REPOSITORY, "_load_mongo_backend", return_value=mongo_backend):
                result = json.loads(
                    tools_mod.store_job_posting_result_tool(
                        job_posting_result={
                            "agent": "job_platform_ingest",
                            "correlation_id": "platform:job-43",
                            "parse": {"is_job_posting": True},
                            "job_posting": {
                                "job_title": "Knowledge Pipeline Engineer",
                                "company_name": "Platform Co",
                            },
                        },
                        db_path=job_postings_db_path,
                        source_agent="job_platform_ingest",
                        source_payload={"platform": "example_jobs", "record_id": "job-43"},
                    )
                )
                stored = tools_mod.DOCUMENT_REPOSITORY.get_document(
                    "platform:job-43",
                    db_path=job_postings_db_path,
                    obj_name="job_postings",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["db_path"], job_postings_db_path)
            self.assertEqual(stored["job_posting"]["job_title"], "Knowledge Pipeline Engineer")
            mongo_record = mongo_backend.load_record(
                storage_key=job_postings_db_path,
                record_id="platform:job-43",
                db_name="job_postings",
                obj_name="job_postings",
            )
            self.assertEqual(mongo_record["job_posting"]["job_title"], "Knowledge Pipeline Engineer")
        finally:
            os.unlink(job_postings_db_path)

    def test_store_job_posting_result_tool_persists_explicit_job_posting_model(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            result = json.loads(
                tools_mod.store_job_posting_result_tool(
                    job_posting_result={
                        "agent": "job_platform_ingest",
                        "correlation_id": "platform:job-explicit-55",
                        "parse": {"is_job_posting": True, "language": "de"},
                        "raw_text_document": {
                            "document_type": "job_posting",
                            "title": "Platform Support Engineer",
                            "language": "de",
                            "raw_text": "Platform Support Engineer at Example Co with Python and SQL.",
                            "sections": [
                                {
                                    "section_key": "header",
                                    "heading": "Object Header",
                                    "text": "Title: Platform Support Engineer\nOrganization: Example Co",
                                }
                            ],
                        },
                        "entity_objects": [
                            {
                                "entity_key": "subject",
                                "entity_type": "job_posting",
                                "canonical_name": "Platform Support Engineer",
                                "metadata": {"role": "subject"},
                            },
                            {
                                "entity_key": "organization:example_co",
                                "entity_type": "organization",
                                "canonical_name": "Example Co",
                            },
                            {
                                "entity_key": "skill:python",
                                "entity_type": "skill",
                                "canonical_name": "Python",
                            },
                        ],
                        "relation_objects": [
                            {
                                "source_entity_key": "subject",
                                "target_entity_key": "organization:example_co",
                                "relation_type": "offered_by",
                                "section_key": "header",
                            }
                        ],
                    },
                    db_path=job_postings_db_path,
                    source_agent="job_platform_ingest",
                )
            )

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document(
                "platform:job-explicit-55",
                db_path=job_postings_db_path,
                obj_name="job_postings",
            )
            self.assertTrue(result["ok"])
            self.assertEqual(stored["job_posting"]["job_title"], "Platform Support Engineer")
            self.assertEqual(stored["job_posting"]["company_name"], "Example Co")
            self.assertEqual(stored["raw_text_document"]["title"], "Platform Support Engineer")
            self.assertEqual(stored["entity_objects"][2]["canonical_name"], "Python")
        finally:
            os.unlink(job_postings_db_path)

    def test_update_dispatcher_status_uses_mongo_backend_as_primary_store(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            dispatcher_db_path = tmp.name

        try:
            mongo_backend = _InMemoryMongoDocumentBackend()
            with patch.object(tools_mod.DOCUMENT_REPOSITORY, "_load_mongo_backend", return_value=mongo_backend):
                result = tools_mod.DOCUMENT_REPOSITORY.update_dispatcher_status(
                    correlation_id="dispatch:job-44",
                    processing_state="processed",
                    db_path=dispatcher_db_path,
                    processed=True,
                    extra_updates={"source_agent": "job_dispatcher", "tenant_id": "tenant_demo"},
                )
                dispatcher_db = tools_mod.DOCUMENT_REPOSITORY.load_db(dispatcher_db_path, db_name="dispatcher_documents")

            self.assertTrue(result["ok"])
            self.assertEqual(dispatcher_db["documents"]["dispatch:job-44"]["processing_state"], "processed")
            self.assertEqual(dispatcher_db["documents"]["dispatch:job-44"]["source_agent"], "job_dispatcher")
        finally:
            os.unlink(dispatcher_db_path)

    def test_write_document_returns_structured_payload_and_persists_cover_letter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mongo_backend = _InMemoryMongoDocumentBackend()
            with patch.object(tools_mod.DOCUMENT_REPOSITORY, "_load_mongo_backend", return_value=mongo_backend):
                result = tools_mod.write_document(
                    content="Sehr geehrtes Team,\n\nmit Interesse bewerbe ich mich.\n",
                    path=tmpdir,
                    doc_id="bewerbung_test",
                    correlation_id="cover-letter:test-1",
                )
                stored = tools_mod.DOCUMENT_REPOSITORY.get_document("cover-letter:test-1", obj_name="cover_letters")

            self.assertTrue(result["ok"])
            self.assertTrue(os.path.exists(result["path"]))
            self.assertEqual(result["correlation_id"], "cover-letter:test-1")
            self.assertEqual(stored["cover_letter"]["document_id"], "bewerbung_test")
            self.assertIn("mit Interesse bewerbe ich mich", stored["cover_letter"]["full_text"])
            self.assertEqual(stored["file"]["path"], result["path"])

    def test_dispatch_documents_reads_existing_dispatcher_state_via_mongo_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "posting.pdf")
            with open(pdf_path, "wb") as handle:
                handle.write(b"fake-pdf-content")

            correlation_id = tools_mod._sha256_file(pdf_path)
            mongo_backend = _InMemoryMongoDocumentBackend()
            mongo_backend.upsert_record(
                storage_key=os.path.join(tools_mod.GetPath()._parent(parg=f"{tools_mod.__file__}"), "AppData", "dispatcher_doc_db.json"),
                record_id=correlation_id,
                record_value={
                    "id": correlation_id,
                    "content_sha256": correlation_id,
                    "processing_state": "processed",
                    "processed": True,
                },
                db_name="dispatcher_documents",
                obj_name="documents",
            )

            with patch.object(tools_mod.DOCUMENT_REPOSITORY, "_load_mongo_backend", return_value=mongo_backend):
                report = tools_mod.dispatch_docs(scan_dir=tmpdir, dry_run=True)

            self.assertTrue(report["db"]["reachable"])
            self.assertEqual(len(report["classified"]["known_processed"]), 1)
            self.assertEqual(report["classified"]["known_processed"][0]["content_sha256"], correlation_id)

    def test_dispatch_documents_tool_spec_accepts_current_and_legacy_agent_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "posting.pdf")
            with open(pdf_path, "wb") as handle:
                handle.write(b"fake-pdf-content")

            tool_spec = tools_mod.get_tool_spec("dispatch_documents")

            self.assertIsNotNone(tool_spec)
            self.assertIn("agent_name", [param.name for param in tool_spec.parameters])
            self.assertNotIn("parser_agent_name", [param.name for param in tool_spec.parameters])

            tool_result = tool_spec.execute({"scan_dir": tmpdir, "dry_run": True})
            legacy_result = tools_mod.dispatch_docs(
                scan_dir=tmpdir,
                dry_run=True,
                parser_agent_name="_job_posting_parser",
            )

            self.assertIsInstance(tool_result, dict)
            self.assertEqual(tool_result["agent"], "xworker")
            self.assertEqual(tool_result["job_name"], "document_dispatch")
            self.assertEqual(legacy_result["agent"], "xworker")
            self.assertEqual(legacy_result["job_name"], "document_dispatch")

    def test_read_document_uses_batch_pdf_extractor_for_pdf_files(self) -> None:
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
            tmp.write(b"fake-pdf-content")

        try:
            with patch("alde.batch_document._extract_pdf_text", return_value="Seite 1: Python\n\nSeite 2: MongoDB") as extract_mock:
                result = tools_mod.read_document(pdf_path)

            self.assertEqual(result, "Seite 1: Python\n\nSeite 2: MongoDB")
            extract_mock.assert_called_once_with(pdf_path)
        finally:
            os.unlink(pdf_path)

    def test_read_document_tool_spec_marks_direct_final_result(self) -> None:
        tool_spec = tools_mod.get_tool_spec("read_document")

        self.assertIsNotNone(tool_spec)
        self.assertTrue(tool_spec.final_result)
        self.assertFalse(tool_spec.tool_response_required)

    def test_xworker_prompt_config_supports_tool_name_selection_and_tools_task_option(self) -> None:
        prompt_config = agents_configurator.get_prompt_config("_xworker")
        task_config = prompt_config.get("task") or {}
        selection_policy = task_config.get("job_skill_profile_policy") or {}

        self.assertEqual(task_config.get("tools"), [])
        self.assertEqual(selection_policy.get("selection_mode"), "tool_name")
        self.assertEqual(selection_policy.get("fallback_selection_mode"), "job_name")
        self.assertEqual(selection_policy.get("fallback_skill_profile"), "xworker_core")

    def test_direct_file_read_guidance_prefers_read_document_over_retrieval(self) -> None:
        router_prompt = agents_configurator.get_system_prompt("_xplaner_xrouter")
        worker_prompt = agents_configurator.get_system_prompt("_xworker")
        read_document_spec = tools_mod.get_tool_spec("read_document")
        memorydb_spec = tools_mod.get_tool_spec("memorydb")
        vectordb_spec = tools_mod.get_tool_spec("vectordb")

        self.assertIn("concrete filesystem path", router_prompt)
        self.assertIn("read_document", router_prompt)
        self.assertIn("memorydb", router_prompt)
        self.assertIn("vectordb", router_prompt)

        self.assertIn("concrete filesystem path", worker_prompt)
        self.assertIn("read_document", worker_prompt)
        self.assertIn("memorydb", worker_prompt)
        self.assertIn("vectordb", worker_prompt)

        self.assertIsNotNone(read_document_spec)
        self.assertIsNotNone(memorydb_spec)
        self.assertIsNotNone(vectordb_spec)
        self.assertIn("concrete file path", read_document_spec.description)
        self.assertIn("Do not use this to open a concrete file path", memorydb_spec.description)
        self.assertIn("Do not use this to open or load a concrete file path", vectordb_spec.description)

    def test_route_to_agent_builds_xworker_request_from_tool_name_and_explicit_tools(self) -> None:
        result_text, routing_request = agents_factory.execute_tool(
            "route_to_agent",
            {
                "target_agent": "_xworker",
                "tool_name": "read_document",
                "tools": ["read_document"],
                "message_text": "Please load /tmp/example.txt",
            },
            source_agent_label="_xplaner_xrouter",
        )

        self.assertEqual(result_text, "Routing to _xworker")
        self.assertIsNotNone(routing_request)
        routed_tool_names = [
            tool_def["function"]["name"]
            for tool_def in (routing_request.get("tools") or [])
            if isinstance(tool_def, dict) and isinstance(tool_def.get("function"), dict)
        ]

        self.assertEqual(routed_tool_names, ["read_document"])
        self.assertEqual(routing_request["handoff"]["metadata"]["tool_name"], "read_document")
        self.assertEqual(routing_request["handoff"]["metadata"]["job_name"], "generic_execution")
        self.assertEqual(routing_request["handoff"]["metadata"]["tools"], ["read_document"])
        self.assertEqual(routing_request["runtime"]["selection_mode"], "tool_name")
        self.assertEqual(routing_request["runtime"]["fallback_selection_mode"], "job_name")
        self.assertEqual(routing_request["runtime"]["tool_name"], "read_document")
        self.assertEqual(routing_request["runtime"]["job_name"], "generic_execution")
        self.assertEqual(routing_request["runtime"]["explicit_tools"], ["read_document"])
        self.assertEqual(routing_request["runtime"]["skill_profile"], "xworker_core")

    def test_read_document_tool_result_is_returned_and_logged_as_final_assistant_result(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            file_path = tmp.name
            tmp.write("Direkter Dokumentinhalt")

        try:
            tool_call = SimpleNamespace(
                id="call_read_document",
                function=SimpleNamespace(
                    name="read_document",
                    arguments=json.dumps({"file_path": file_path}, ensure_ascii=False),
                ),
            )

            result = agents_factory._handle_tool_calls(
                SimpleNamespace(content="", tool_calls=[tool_call]),
                agent_label="",
            )

            self.assertEqual(result, "Direkter Dokumentinhalt")

            assistant_entries = [
                entry
                for entry in chat_mod.ChatHistory._history_
                if isinstance(entry, dict) and entry.get("role") == "assistant"
            ]
            tool_entries = [
                entry
                for entry in chat_mod.ChatHistory._history_
                if isinstance(entry, dict) and entry.get("role") == "tool"
            ]

            self.assertTrue(assistant_entries)
            self.assertEqual(assistant_entries[-1].get("content"), "Direkter Dokumentinhalt")
            self.assertTrue(tool_entries)
            self.assertFalse(tool_entries[-1].get("tool_response_required", True))

            history = chat_mod.ChatHistory()
            history._thread_iD = tool_entries[-1].get("thread-id")
            inserted = history._insert(tool=True, f_depth=10)

            self.assertEqual(inserted, [{"role": "assistant", "content": "Direkter Dokumentinhalt"}])
        finally:
            os.unlink(file_path)

    def test_run_retrieval_with_events_triggers_optional_mongodb_sync(self) -> None:
        retrieval_result = [
            {
                "document_id": "doc_job_0001",
                "title": "Senior Python Engineer",
                "score": 0.93,
                "source": "https://example.org/jobs/0001",
            },
        ]

        with patch("alde.tools._emit_query_event") as emit_query_event:
            with patch("alde.tools._emit_outcome_event") as emit_outcome_event:
                with patch("alde.tools._run_vectordb_subprocess", return_value=retrieval_result):
                    with patch("alde.tools.sync_retrieval_run_to_mongodb_knowledge", return_value={"ok": True, "stored": True}) as mongo_sync:
                        result = tools_mod._run_retrieval_with_events("vectordb", "Python RAG", 3)

        self.assertEqual(result, retrieval_result)
        emit_query_event.assert_called_once()
        emit_outcome_event.assert_called_once()
        mongo_sync.assert_called_once()
        self.assertEqual(mongo_sync.call_args.kwargs["tool_name"], "vectordb")
        self.assertEqual(mongo_sync.call_args.kwargs["query_event"]["query_text"], "Python RAG")
        self.assertEqual(mongo_sync.call_args.kwargs["outcome_event"]["result_count"], 1)
        self.assertEqual(mongo_sync.call_args.kwargs["retrieval_result"][0]["document_id"], "doc_job_0001")

    def test_vector_search_logging_emits_raw_result_without_wrapper(self) -> None:
        result_object = [{"rank": 1, "source": "knowledge.md", "content": "alpha"}]

        with patch("builtins.print") as mocked_print:
            agents_factory.TOOL_EXECUTION_CALLBACK_SERVICE.log_object_result("memorydb", result_object)

        mocked_print.assert_called_once_with("TOOL RESULT: memorydb [payload omitted]")

    def test_followup_uses_raw_tool_results_when_history_messages_are_empty(self) -> None:
        captured_messages: dict[str, object] = {}

        class _DummyChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                captured_messages["messages"] = list(_messages)

            def _response(self):
                message = SimpleNamespace(content="processed retrieval", tool_calls=None)
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        history = agents_factory.get_history()
        history._history_ = []
        history._thread_iD = 777

        with patch.object(
            agents_factory.TOOL_CALL_FOLLOWUP_SERVICE,
            "build_object_request",
            return_value={"messages": [], "tools": [], "model": "gpt-4o-mini"},
        ), patch("alde.chat_completion.ChatComE", _DummyChatComE):
            result = agents_factory.TOOL_CALL_FOLLOWUP_SERVICE.execute_object_followup(
                history=history,
                routing_request=None,
                tool_results=['[{"rank": 1, "source": "knowledge.md", "content": "alpha"}]'],
                depth=0,
                ChatCom=None,
                agent_label="_xplaner_xrouter",
                workflow_session=None,
            )

        self.assertEqual(
            captured_messages["messages"],
            [{"role": "user", "content": '[{"rank": 1, "source": "knowledge.md", "content": "alpha"}]'}],
        )
        self.assertEqual(result, "processed retrieval")

    def test_store_profile_result_tool_supports_direct_profile_storage(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            profiles_db_path = tmp.name

        try:
            result = json.loads(
                tools_mod.store_profile_result_tool(
                    profile_result={
                        "agent": "profile_platform_ingest",
                        "correlation_id": "profile:job-board-7",
                        "parse": {"language": "de", "errors": [], "warnings": []},
                        "profile": {
                            "profile_id": "profile:job-board-7",
                            "personal_info": {"full_name": "Max Mustermann"},
                            "preferences": {"language": "de"},
                        },
                    },
                    db_path=profiles_db_path,
                    source_agent="profile_platform_ingest",
                )
            )

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("profile:job-board-7", db_path=profiles_db_path, obj_name="profiles")
            self.assertTrue(result["ok"])
            self.assertEqual(result["correlation_id"], "profile:job-board-7")
            self.assertEqual(stored["profile"]["profile_id"], "profile:job-board-7")
            self.assertEqual(stored["profile"]["personal_info"]["full_name"], "Max Mustermann")
        finally:
            os.unlink(profiles_db_path)

    def test_ingest_profile_tool_supports_request_style_profile_sources(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            profiles_db_path = tmp.name

        try:
            result = json.loads(
                tools_mod.ingest_profile_tool(
                    applicant_profile={
                        "source": "text",
                        "value": {
                            "profile_id": "profile:platform-11",
                            "personal_info": {"full_name": "Erika Muster"},
                            "preferences": {"language": "de"},
                        },
                    },
                    db_path=profiles_db_path,
                    source_agent="profile_platform_ingest",
                    source_payload={"platform": "example_profiles", "record_id": "platform-11"},
                )
            )

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("profile:platform-11", db_path=profiles_db_path, obj_name="profiles")
            self.assertTrue(result["ok"])
            self.assertEqual(result["correlation_id"], "profile:platform-11")
            self.assertEqual(stored["profile"]["personal_info"]["full_name"], "Erika Muster")
        finally:
            os.unlink(profiles_db_path)

    def test_ingest_job_posting_action_returns_store_result_without_model_call(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            request = {
                "action": "ingest_object",
                "correlation_id": "platform:ingest-99",
                "source_agent": "job_platform_ingest",
                "obj_db_path": job_postings_db_path,
                "job_posting": {
                    "job_title": "Senior Data Engineer",
                    "company_name": "Platform Co",
                    "external_id": "ingest-99",
                },
                "source_payload": {
                    "platform": "example_jobs",
                    "record_id": "ingest-99",
                },
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )
                response = json.loads(chat.get_response())

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("platform:ingest-99", db_path=job_postings_db_path, obj_name="job_postings")
            self.assertTrue(response["ok"])
            self.assertEqual(response["correlation_id"], "platform:ingest-99")
            self.assertEqual(stored["job_posting"]["job_title"], "Senior Data Engineer")
            self.assertEqual(stored["parse"]["is_job_posting"], True)
            get_client.assert_not_called()
        finally:
            os.unlink(job_postings_db_path)

    def test_ingest_job_posting_tool_includes_knowledge_sync_after_persist(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            with patch.object(
                tools_mod,
                "sync_parser_result_to_mongodb_knowledge",
                return_value={
                    "ok": True,
                    "stored": True,
                    "object_name": "job_posting",
                    "document_id": "doc:job_posting:platform:ingest-knowledge-1",
                    "entity_count": 5,
                    "relation_count": 4,
                },
            ) as sync_mock:
                result = json.loads(
                    tools_mod.ingest_job_posting_tool(
                        job_posting={
                            "job_title": "Platform Knowledge Engineer",
                            "company_name": "Platform Co",
                            "requirements": {
                                "technical_skills": ["Python", "MongoDB"],
                                "soft_skills": ["Kommunikation"],
                                "languages": ["Deutsch", "Englisch"],
                            },
                        },
                        correlation_id="platform:ingest-knowledge-1",
                        db_path=job_postings_db_path,
                        source_agent="job_platform_ingest",
                        source_payload={"platform": "example_jobs", "record_id": "ingest-knowledge-1"},
                    )
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["knowledge_sync"]["stored"])
            self.assertEqual(result["knowledge_sync"]["relation_count"], 4)
            self.assertEqual(sync_mock.call_args.kwargs["object_name"], "job_postings")
            self.assertEqual(sync_mock.call_args.kwargs["correlation_id"], "platform:ingest-knowledge-1")
        finally:
            os.unlink(job_postings_db_path)

    def test_store_profile_action_returns_store_result_without_model_call(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            profiles_db_path = tmp.name

        try:
            request = {
                "action": "ingest_object",
                "obj_db_path": profiles_db_path,
                "source_agent": "profile_platform_ingest",
                "applicant_profile": {
                    "source": "text",
                    "value": {
                        "profile_id": "profile:ingest-5",
                        "personal_info": {"full_name": "Jane Doe"},
                        "preferences": {"language": "en"},
                    },
                },
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )
                response = json.loads(chat.get_response())

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("profile:ingest-5", db_path=profiles_db_path, obj_name="profiles")
            self.assertTrue(response["ok"])
            self.assertEqual(response["correlation_id"], "profile:ingest-5")
            self.assertEqual(stored["profile"]["personal_info"]["full_name"], "Jane Doe")
            get_client.assert_not_called()
        finally:
            os.unlink(profiles_db_path)

    def test_ingest_profile_action_returns_store_result_without_model_call(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            profiles_db_path = tmp.name

        try:
            request = {
                "action": "ingest_object",
                "obj_db_path": profiles_db_path,
                "source_agent": "profile_platform_ingest",
                "profile": {
                    "profile_id": "profile:ingest-15",
                    "personal_info": {"full_name": "Alex Example"},
                    "preferences": {"language": "en"},
                },
                "source_payload": {
                    "platform": "example_profiles",
                    "record_id": "ingest-15",
                },
            }

            with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
                chat = chat_mod.ChatCom(
                    _model="gpt-4o-mini",
                    _input_text=json.dumps(request, ensure_ascii=False),
                    _name="test_workflow",
                )
                response = json.loads(chat.get_response())

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("profile:ingest-15", db_path=profiles_db_path, obj_name="profiles")
            self.assertTrue(response["ok"])
            self.assertEqual(response["correlation_id"], "profile:ingest-15")
            self.assertEqual(stored["profile"]["personal_info"]["full_name"], "Alex Example")
            get_client.assert_not_called()
        finally:
            os.unlink(profiles_db_path)

    def test_ingest_job_posting_action_rejects_invalid_schema_request(self) -> None:
        request = {
            "action": "ingest_object",
            "source_agent": "job_platform_ingest",
            "obj_db_path": "/tmp/unused-job-postings.json",
        }

        with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
            chat = chat_mod.ChatCom(
                _model="gpt-4o-mini",
                _input_text=json.dumps(request, ensure_ascii=False),
                _name="test_workflow",
            )
            response = json.loads(chat.get_response())

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "invalid_action_request")
        self.assertEqual(response["schema_name"], "platform_job_posting_ingest_request")
        get_client.assert_not_called()

    def test_execute_action_request_tool_ingests_job_posting_for_dispatcher(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            result_text, routing_request = agents_factory.execute_tool(
                "execute_action_request",
                {
                    "action": "ingest_object",
                    "payload": {
                        "correlation_id": "platform:dispatcher-21",
                        "obj_db_path": job_postings_db_path,
                        "obj_name": "job_postings",
                        "source_agent": "job_platform_ingest",
                        "job_posting": {
                            "job_title": "Automation Engineer",
                            "company_name": "Dispatcher Co",
                        },
                        "source_payload": {
                            "platform": "example_jobs",
                            "record_id": "dispatcher-21",
                        },
                    },
                },
                source_agent_label="_xworker",
            )

            result = json.loads(result_text)
            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("platform:dispatcher-21", db_path=job_postings_db_path, obj_name="job_postings")
            self.assertIsNone(routing_request)
            self.assertTrue(result["ok"])
            self.assertEqual(stored["job_posting"]["job_title"], "Automation Engineer")
            self.assertEqual(stored["parse"]["is_job_posting"], True)
        finally:
            os.unlink(job_postings_db_path)

    def test_primary_route_parser_result_is_persisted_to_job_postings_store(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        try:
            routing_request = {
                "agent_label": "_xworker",
                "handoff": {
                    "handoff_payload": {
                        "output": {
                            "type": "job_posting_pdf",
                            "file": {
                                "path": "/tmp/example-job.pdf",
                                "content_sha256": "sha-direct-store-1",
                            },
                            "requested_actions": ["parse", "store_object_result"],
                            "job_name": "job_posting_parser",
                        }
                    },
                    "metadata": {
                        "correlation_id": "sha-direct-store-1",
                        "obj_name": "job_postings",
                        "obj_db_path": job_postings_db_path,
                    },
                },
                "handoff_context": {
                    "contract": {
                        "schema": {
                            "result_postprocess": {
                                "tool": "store_object_result",
                                "source_agent": "target_agent",
                            }
                        }
                    }
                },
            }

            postprocess_result = agents_factory.ROUTING_RESULT_POSTPROCESS_SERVICE.apply_object_result(
                routing_request,
                result_text=json.dumps(
                    {
                        "agent": "xworker",
                        "job_name": "job_posting_parser",
                        "correlation_id": "sha-direct-store-1",
                        "parse": {"is_job_posting": True},
                        "job_posting": {
                            "job_title": "Runtime Persisted Engineer",
                            "company_name": "Route Storage Co",
                        },
                    },
                    ensure_ascii=False,
                ),
                succeeded=True,
            )

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document(
                "sha-direct-store-1",
                db_path=job_postings_db_path,
                obj_name="job_postings",
            )

            self.assertIsInstance(postprocess_result, dict)
            self.assertTrue(postprocess_result["ok"])
            self.assertEqual(postprocess_result["obj_name"], "job_postings")
            self.assertEqual(stored["job_posting"]["job_title"], "Runtime Persisted Engineer")
            self.assertEqual(stored["agent"], "_xworker")
        finally:
            os.unlink(job_postings_db_path)

    def test_deterministic_action_is_logged_as_real_assistant_result(self) -> None:
        request = {
            "action": "ingest_object",
            "payload": {
                "correlation_id": "platform:history-1",
                "obj_db_path": "/tmp/unused-job-postings.json",
                "source_agent": "job_platform_ingest",
                "job_posting": {
                    "job_title": "History Engineer",
                    "company_name": "History Co",
                },
            },
        }

        with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
            chat = chat_mod.ChatCom(
                _model="gpt-4o-mini",
                _input_text=json.dumps(request, ensure_ascii=False),
                _name="test_workflow",
            )
            response_text = chat.get_response()

        assistant_entries = [
            entry
            for entry in chat_mod.ChatHistory._history_
            if isinstance(entry, dict) and entry.get("role") == "assistant"
        ]

        self.assertTrue(assistant_entries)
        latest = assistant_entries[-1]
        self.assertEqual(latest.get("content"), response_text)
        self.assertEqual(latest.get("data", {}).get("deterministic_action", {}).get("action"), "ingest_object")
        self.assertEqual(latest.get("data", {}).get("deterministic_action", {}).get("correlation_id"), "platform:history-1")
        get_client.assert_not_called()

    def test_forced_route_is_logged_as_prepared_route_instead_of_tool_placeholder(self) -> None:
        with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
            chat_mod.ChatCom(
                _model="gpt-4o-mini",
                _input_text=json.dumps(SAMPLE_WORKFLOW_REQUEST, ensure_ascii=False),
                _name="test_workflow",
            )

        assistant_entries = [
            entry
            for entry in chat_mod.ChatHistory._history_
            if isinstance(entry, dict) and entry.get("role") == "assistant"
        ]

        self.assertTrue(assistant_entries)
        self.assertEqual(assistant_entries[-1].get("content"), "[forced route prepared]")
        get_client.assert_not_called()

    def test_upsert_dispatcher_job_record_tool_updates_both_stores(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as dispatcher_tmp, tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as jobs_tmp:
            dispatcher_db_path = dispatcher_tmp.name
            job_postings_db_path = jobs_tmp.name

        try:
            result = json.loads(
                tools_mod.upsert_dispatcher_job_record_tool(
                    job_posting_result={
                        "agent": "job_platform_ingest",
                        "correlation_id": "platform:atomic-1",
                        "parse": {"is_job_posting": True},
                        "job_posting": {
                            "job_title": "ERP Integration Engineer",
                            "company_name": "Atomic Co",
                        },
                        "db_updates": {"processing_state": "processed", "processed": True},
                    },
                    dispatcher_db_path=dispatcher_db_path,
                    job_postings_db_path=job_postings_db_path,
                    source_agent="job_platform_ingest",
                    source_payload={"platform": "example_jobs", "record_id": "atomic-1"},
                    dispatcher_updates={"thread_id": "thread-atomic"},
                )
            )

            stored_job = tools_mod.DOCUMENT_REPOSITORY.get_document("platform:atomic-1", db_path=job_postings_db_path, obj_name="job_postings")
            dispatcher_db = tools_mod.DOCUMENT_REPOSITORY.load_db(dispatcher_db_path, db_name="dispatcher_documents")
            dispatcher_record = dispatcher_db["documents"]["platform:atomic-1"]
            self.assertTrue(result["ok"])
            self.assertTrue(result["dispatcher_updated"])
            self.assertEqual(stored_job["job_posting"]["job_title"], "ERP Integration Engineer")
            self.assertEqual(dispatcher_record["processing_state"], "processed")
            self.assertEqual(dispatcher_record["thread_id"], "thread-atomic")
        finally:
            os.unlink(dispatcher_db_path)
            os.unlink(job_postings_db_path)

    def test_execute_action_request_tool_supports_atomic_dispatcher_job_upsert(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as dispatcher_tmp, tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as jobs_tmp:
            dispatcher_db_path = dispatcher_tmp.name
            job_postings_db_path = jobs_tmp.name

        try:
            result_text, routing_request = agents_factory.execute_tool(
                "execute_action_request",
                {
                    "action": "upsert_object_record",
                    "payload": {
                        "correlation_id": "platform:atomic-2",
                        "dispatcher_db_path": dispatcher_db_path,
                        "obj_db_path": job_postings_db_path,
                        "obj_name": "job_postings",
                        "source_agent": "job_platform_ingest",
                        "processing_state": "processed",
                        "job_posting_result": {
                            "agent": "job_platform_ingest",
                            "parse": {"is_job_posting": True},
                            "job_posting": {
                                "job_title": "Autonomous Workflow Engineer",
                                "company_name": "Atomic Dispatcher Co",
                            },
                        },
                    },
                },
                source_agent_label="_xworker",
            )

            result = json.loads(result_text)
            stored_job = tools_mod.DOCUMENT_REPOSITORY.get_document("platform:atomic-2", db_path=job_postings_db_path, obj_name="job_postings")
            dispatcher_db = tools_mod.DOCUMENT_REPOSITORY.load_db(dispatcher_db_path, db_name="dispatcher_documents")
            self.assertIsNone(routing_request)
            self.assertTrue(result["ok"])
            self.assertEqual(stored_job["job_posting"]["job_title"], "Autonomous Workflow Engineer")
            self.assertEqual(dispatcher_db["documents"]["platform:atomic-2"]["processing_state"], "processed")
        finally:
            os.unlink(dispatcher_db_path)
            os.unlink(job_postings_db_path)

    def test_action_request_service_dispatches_generic_object_action_via_config(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            custom_db_path = tmp.name

        try:
            request = {
                "action": "store_generic_object",
                "obj_name": "custom_records",
                "custom_records_db_path": custom_db_path,
                "source_agent": "generic_ingest",
                "object_payload": {
                    "id": "custom-42",
                    "name": "Config First",
                    "source": "platform.generic",
                },
            }
            schema_config = {
                "name": "generic_object_ingest_request",
                "actions": ["store_generic_object"],
                "request_resolution": {
                    "objects": [
                        {
                            "binding_name": "generic_object",
                            "request_field": "object_request",
                            "result_field": "object_result",
                            "default_obj_name": "generic_objects",
                            "obj_name_config_key": "generic_obj_name",
                            "db_path_field_key": "generic_db_path_field",
                            "default_source": "text",
                        }
                    ]
                },
                "action_execution": {
                    "handler_name": "ingest_object",
                    "binding_name": "generic_object",
                    "object_payload_field": "object_payload",
                    "request_payload_field": "object_request",
                    "result_payload_field": "object_result",
                    "correlation_id_fields": ["correlation_id"],
                    "source_agent_fields": ["source_agent"],
                    "default_request_source": "text",
                },
            }

            with patch("alde.tools.get_action_request_schema_config", return_value=schema_config), patch(
                "alde.tools.validate_action_request",
                return_value={
                    "valid": True,
                    "errors": [],
                    "warnings": [],
                    "schema_name": "generic_object_ingest_request",
                },
            ):
                response = json.loads(tools_mod.ACTION_REQUEST_SERVICE.execute_request(request))

            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("custom-42", db_path=custom_db_path, obj_name="custom_records")
            self.assertTrue(response["ok"])
            self.assertEqual(response["obj_name"], "custom_records")
            self.assertEqual(stored["custom_records"]["name"], "Config First")
            self.assertEqual(stored["agent"], "generic_ingest")
        finally:
            os.unlink(custom_db_path)

    def test_forced_route_executes_via_agents_factory_path(self) -> None:
        captured_execute_tool_calls: list[tuple[str, dict]] = []

        def _fake_execute_tool(name: str, args: dict, tool_call_id: str = None, source_agent_label: str = None):
            captured_execute_tool_calls.append((name, dict(args)))
            if name == "route_to_agent":
                return (
                    "Routing to _xworker",
                    {
                        "messages": [
                            {"role": "system", "content": "writer system"},
                            {"role": "system", "content": "Structured handoff context. {}"},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        **SAMPLE_WORKFLOW_REQUEST,
                                        "job_posting_result": {
                                            "agent": "job_posting_parser",
                                            "correlation_id": "sample-job-1",
                                            "job_posting": {
                                                "job_title": "Full Stack Software Engineer",
                                                "raw_text": "Full Stack Software Engineer role at Example Co",
                                            },
                                        },
                                        "profile_result": {
                                            "agent": "profile_parser",
                                            "correlation_id": "profile:test",
                                            "parse": {"language": "de", "errors": [], "warnings": []},
                                            "profile": SAMPLE_WORKFLOW_REQUEST["applicant_profile"]["value"],
                                        },
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                        "agent_label": "_xworker",
                        "tools": [],
                        "model": "gpt-4o",
                        "include_history": False,
                        "handoff": {
                            "protocol": "agent_handoff_v1",
                            "source_agent": "_xplaner_xrouter",
                            "target_agent": "_xworker",
                            "handoff_payload": {
                                "agent_label": "_xplaner_xrouter",
                                "handoff_to": "_xworker",
                                "output": {
                                    **SAMPLE_WORKFLOW_REQUEST,
                                    "job_posting_result": {
                                        "agent": "job_posting_parser",
                                        "correlation_id": "sample-job-1",
                                        "job_posting": {
                                            "job_title": "Full Stack Software Engineer",
                                            "raw_text": "Full Stack Software Engineer role at Example Co",
                                        },
                                    },
                                    "profile_result": {
                                        "agent": "profile_parser",
                                        "correlation_id": "profile:test",
                                        "parse": {"language": "de", "errors": [], "warnings": []},
                                        "profile": SAMPLE_WORKFLOW_REQUEST["applicant_profile"]["value"],
                                    },
                                },
                            },
                            "metadata": {},
                        },
                        "handoff_context": {
                            "contract": {
                                "schema": {
                                    "result_postprocess": {
                                        "tool": "persist_cover_letter_artifacts",
                                        "text_writer_tool": "write_document",
                                        "pdf_writer_tool": "md_to_pdf",
                                        "default_write_pdf": True,
                                    }
                                }
                            }
                        },
                        "runtime": {"instance_policy": "ephemeral", "role": "worker"},
                    },
                )
            raise AssertionError(f"Unexpected tool execution: {name}")

        chat = chat_mod.ChatCom(
            _model="gpt-4o-mini",
            _input_text=json.dumps(SAMPLE_WORKFLOW_REQUEST, ensure_ascii=False),
            _name="test_workflow",
        )

        with patch("alde.chat_completion.ChatComE", _DeterministicDispatcherChatComE), patch(
            "alde.agents_factory.execute_tool",
            side_effect=_fake_execute_tool,
        ), patch(
            "alde.agents_factory.write_document",
            return_value="Document saved to: /tmp/sample_cover_letter.md",
        ), patch(
            "alde.agents_factory.md_to_pdf",
            return_value={"ok": True, "pdf_path": "/tmp/sample_cover_letter.pdf"},
        ):
            response = chat.get_response()

        payload = json.loads(response)
        self.assertEqual(payload["cover_letter"]["full_text"], "Sehr geehrtes Team,\n\nMotivation und Erfahrung.")
        self.assertEqual(payload["quality"]["language"], "de")
        self.assertEqual(payload["document_text_path"], "/tmp/sample_cover_letter.md")
        self.assertEqual(payload["document_pdf_path"], "/tmp/sample_cover_letter.pdf")
        self.assertEqual(len(captured_execute_tool_calls), 1)
        self.assertEqual(captured_execute_tool_calls[0][0], "route_to_agent")
        routed = captured_execute_tool_calls[0][1]
        self.assertEqual(routed["target_agent"], "_xworker")
        self.assertEqual(routed["handoff_protocol"], "agent_handoff_v1")
        self.assertEqual(routed["handoff_schema"], "xplaner_to_xworker")
        self.assertEqual(routed["agent_response"]["handoff_to"], "_xworker")
        self.assertEqual(routed["agent_response"]["job_name"], "cover_letter_writer")
        self.assertEqual(routed["agent_response"]["output"]["profile_result"]["profile"]["profile_id"], "profile:test")

    def test_ready_forced_route_executes_via_structured_handoff_path(self) -> None:
        captured_execute_tool_calls: list[tuple[str, dict]] = []

        def _fake_execute_tool(name: str, args: dict, tool_call_id: str = None, source_agent_label: str = None):
            captured_execute_tool_calls.append((name, dict(args)))
            if name == "route_to_agent":
                return (
                    "Routing to _xworker",
                    {
                        "messages": [
                            {"role": "system", "content": "writer system"},
                            {"role": "system", "content": "Structured handoff context. {}"},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "action": "generate_cover_letter",
                                        "job_posting_result": {
                                            "agent": "job_posting_parser",
                                            "correlation_id": "sha-direct-1",
                                            "job_posting": {"job_title": "Support Engineer"},
                                        },
                                        "profile_result": {
                                            "agent": "profile_parser",
                                            "correlation_id": "profile:direct-1",
                                            "parse": {"language": "de", "errors": [], "warnings": []},
                                            "profile": {"profile_id": "profile:direct-1", "preferences": {"language": "de"}},
                                        },
                                        "options": {"language": "de", "tone": "modern", "max_words": 280},
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                        "agent_label": "_xworker",
                        "tools": [],
                        "model": "gpt-4o",
                        "include_history": False,
                        "handoff": {
                            "protocol": "agent_handoff_v1",
                            "source_agent": "_xplaner_xrouter",
                            "target_agent": "_xworker",
                            "handoff_payload": {
                                "agent_label": "_xplaner_xrouter",
                                "handoff_to": "_xworker",
                                "output": {
                                    "action": "generate_cover_letter",
                                    "job_posting_result": {
                                        "agent": "job_posting_parser",
                                        "correlation_id": "sha-direct-1",
                                        "file": {"path": "/tmp/source-posting.pdf"},
                                        "job_posting": {"job_title": "Support Engineer", "company_name": "Example Co"},
                                    },
                                    "profile_result": {
                                        "agent": "profile_parser",
                                        "correlation_id": "profile:direct-1",
                                        "profile": {"profile_id": "profile:direct-1", "preferences": {"language": "de"}},
                                    },
                                    "options": {"language": "de", "tone": "modern", "max_words": 280},
                                },
                            },
                            "metadata": {},
                        },
                        "handoff_context": {
                            "contract": {
                                "schema": {
                                    "result_postprocess": {
                                        "tool": "persist_cover_letter_artifacts",
                                        "text_writer_tool": "write_document",
                                        "pdf_writer_tool": "md_to_pdf",
                                        "default_write_pdf": True,
                                    }
                                }
                            }
                        },
                        "runtime": {"instance_policy": "ephemeral", "role": "worker"},
                    },
                )
            raise AssertionError(f"Unexpected tool execution: {name}")

        ready_request = {
            "action": "generate_cover_letter",
            "job_posting_result": {
                "agent": "job_posting_parser",
                "correlation_id": "sha-direct-1",
                "job_posting": {"job_title": "Support Engineer"},
            },
            "applicant_profile": {
                "source": "text",
                "value": {"profile_id": "profile:direct-1", "preferences": {"language": "de"}},
            },
            "options": {"language": "de", "tone": "modern", "max_words": 280},
        }

        chat = chat_mod.ChatCom(
            _model="gpt-4o-mini",
            _input_text=json.dumps(ready_request, ensure_ascii=False),
            _name="test_ready_structured_route",
        )

        with patch("alde.chat_completion.ChatComE", _DeterministicDispatcherChatComE), patch(
            "alde.agents_factory.execute_tool",
            side_effect=_fake_execute_tool,
        ), patch(
            "alde.agents_factory.write_document",
            return_value="Document saved to: /tmp/cover_letter_ready.md",
        ), patch(
            "alde.agents_factory.md_to_pdf",
            return_value={"ok": True, "pdf_path": "/tmp/cover_letter_ready.pdf"},
        ):
            response = chat.get_response()

        payload = json.loads(response)
        self.assertEqual(payload["cover_letter"]["full_text"], "Sehr geehrtes Team,\n\nMotivation und Erfahrung.")
        self.assertEqual(payload["document_text_path"], "/tmp/cover_letter_ready.md")
        self.assertEqual(payload["document_pdf_path"], "/tmp/cover_letter_ready.pdf")
        self.assertEqual(payload["document_path"], "/tmp/cover_letter_ready.pdf")
        self.assertEqual(len(captured_execute_tool_calls), 1)
        routed = captured_execute_tool_calls[0][1]
        self.assertEqual(routed["target_agent"], "_xworker")
        self.assertEqual(routed["handoff_protocol"], "agent_handoff_v1")
        self.assertEqual(routed["handoff_schema"], "xplaner_to_xworker")
        self.assertEqual(routed["agent_response"]["handoff_to"], "_xworker")
        self.assertEqual(routed["agent_response"]["job_name"], "cover_letter_writer")
        self.assertEqual(routed["agent_response"]["output"]["job_posting_result"]["correlation_id"], "sha-direct-1")

    def test_ready_forced_route_uses_explicit_job_posting_identity_for_artifact_doc_id(self) -> None:
        captured_write_calls: list[dict[str, object]] = []

        def _fake_write_document(*, content: str, path: str | None = None, doc_id: str | None = None, correlation_id: str | None = None, **_: object):
            captured_write_calls.append(
                {
                    "content": content,
                    "path": path,
                    "doc_id": doc_id,
                    "correlation_id": correlation_id,
                }
            )
            return "Document saved to: /tmp/explicit_cover_letter.md"

        chat = chat_mod.ChatCom(
            _model="gpt-4o-mini",
            _input_text=json.dumps(SAMPLE_WORKFLOW_REQUEST, ensure_ascii=False),
            _name="test_explicit_structured_route",
        )

        def _fake_execute_tool(name: str, args: dict, tool_call_id: str = None, source_agent_label: str = None):
            if name != "route_to_agent":
                raise AssertionError(f"Unexpected tool execution: {name}")
            return (
                "Routing to _xworker",
                {
                    "messages": [],
                    "agent_label": "_xworker",
                    "tools": [],
                    "model": "gpt-4o",
                    "include_history": False,
                    "handoff": {
                        "protocol": "agent_handoff_v1",
                        "source_agent": "_xplaner_xrouter",
                        "target_agent": "_xworker",
                        "handoff_payload": {
                            "agent_label": "_xplaner_xrouter",
                            "handoff_to": "_xworker",
                            "output": {
                                "action": "generate_cover_letter",
                                "job_posting_result": {
                                    "agent": "job_posting_parser",
                                    "correlation_id": "sha-explicit-1",
                                    "file": {"path": "/tmp/source-posting.pdf"},
                                    "raw_text_document": {
                                        "title": "Support Engineer",
                                        "raw_text": "Support Engineer at Example Co",
                                    },
                                    "entity_objects": [
                                        {"entity_key": "subject", "entity_type": "job_posting", "canonical_name": "Support Engineer", "metadata": {"role": "subject"}},
                                        {"entity_key": "organization:example_co", "entity_type": "organization", "canonical_name": "Example Co"},
                                    ],
                                    "relation_objects": [
                                        {"source_entity_key": "subject", "target_entity_key": "organization:example_co", "relation_type": "offered_by", "section_key": "header"}
                                    ],
                                },
                                "profile_result": {
                                    "agent": "profile_parser",
                                    "correlation_id": "profile:direct-1",
                                    "profile": {"profile_id": "profile:direct-1", "preferences": {"language": "de"}},
                                },
                                "options": {"language": "de", "tone": "modern", "max_words": 280},
                            },
                        },
                        "metadata": {},
                    },
                    "handoff_context": {
                        "contract": {
                            "schema": {
                                "result_postprocess": {
                                    "tool": "persist_cover_letter_artifacts",
                                    "text_writer_tool": "write_document",
                                    "pdf_writer_tool": "md_to_pdf",
                                    "default_write_pdf": True,
                                }
                            }
                        }
                    },
                    "runtime": {"instance_policy": "ephemeral", "role": "worker"},
                },
            )

        with patch("alde.chat_completion.ChatComE", _DeterministicDispatcherChatComE), patch(
            "alde.agents_factory.execute_tool",
            side_effect=_fake_execute_tool,
        ), patch(
            "alde.agents_factory.write_document",
            side_effect=_fake_write_document,
        ), patch(
            "alde.agents_factory.md_to_pdf",
            return_value={"ok": True, "pdf_path": "/tmp/explicit_cover_letter.pdf"},
        ):
            response = chat.get_response()

        payload = json.loads(response)
        self.assertEqual(payload["document_text_path"], "/tmp/explicit_cover_letter.md")
        self.assertEqual(payload["document_pdf_path"], "/tmp/explicit_cover_letter.pdf")
        self.assertEqual(captured_write_calls[0]["doc_id"], "Support Engineer_Example Co")

    def test_import_dispatch_pipeline_action_uses_forced_route(self) -> None:
        pipeline_request = {
            "action": "import_dispatch_pipeline",
            "correlation_id": "pipeline-import-001",
            "job_posting_result": {
                "agent": "job_posting_parser",
                "correlation_id": "pipeline-import-001",
                "job_posting": {
                    "job_title": "Pipeline Engineer",
                    "company_name": "Tree Data Co",
                },
            },
            "agents_db_tree_path": "ALDE/AppData/tree_data.json",
        }

        with patch.object(chat_mod.ChatCompletion, "_get_client") as get_client:
            chat = chat_mod.ChatCom(
                _model="gpt-4o-mini",
                _input_text=json.dumps(pipeline_request, ensure_ascii=False),
                _name="test_import_dispatch_pipeline_route",
            )

        self.assertEqual(chat._forced_route["target_agent"], "_xworker")
        self.assertEqual(chat._forced_route["job_name"], "document_dispatch_ingest_import_pipeline")
        self.assertIn("import_dispatch_pipeline", str(chat._forced_route.get("user_question") or ""))
        get_client.assert_not_called()

    def test_dispatch_parser_import_pipeline_persists_and_propagates_tree_data_path(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            job_postings_db_path = tmp.name

        tree_data_rel_path = "ALDE/AppData/tree_data.json"
        try:
            self.assertTrue(Path(PKG_ROOT / "AppData" / "tree_data.json").is_file())

            mongo_backend = _InMemoryMongoDocumentBackend()
            with patch.object(tools_mod.DOCUMENT_REPOSITORY, "_load_mongo_backend", return_value=mongo_backend), patch.object(
                tools_mod,
                "sync_parser_result_to_mongodb_knowledge",
                return_value={
                    "ok": True,
                    "stored": True,
                    "backend": "mongodb",
                    "tree_data_path": tree_data_rel_path,
                    "object_name": "job_postings",
                },
            ) as sync_mock:
                result = json.loads(
                    tools_mod.store_job_posting_result_tool(
                        job_posting_result={
                            "agent": "document_dispatch_ingest_import_pipeline",
                            "correlation_id": "pipeline-import-002",
                            "parse": {"is_job_posting": True},
                            "job_posting": {
                                "job_title": "Dispatcher Parser Import Engineer",
                                "company_name": "Pipeline Labs",
                            },
                        },
                        correlation_id="pipeline-import-002",
                        db_path=job_postings_db_path,
                        source_agent="document_dispatch_ingest_import_pipeline",
                        source_payload={
                            "action": "import_dispatch_pipeline",
                            "agents_db_tree_path": tree_data_rel_path,
                            "tree_data_path": tree_data_rel_path,
                        },
                    )
                )

            mongo_record = mongo_backend.load_record(
                storage_key=job_postings_db_path,
                record_id="pipeline-import-002",
                db_name="job_postings",
                obj_name="job_postings",
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["knowledge_sync"]["stored"])
            self.assertEqual(result["knowledge_sync"]["backend"], "mongodb")
            self.assertEqual(result["knowledge_sync"]["tree_data_path"], tree_data_rel_path)
            self.assertIsNotNone(mongo_record)
            self.assertEqual(mongo_record["job_posting"]["job_title"], "Dispatcher Parser Import Engineer")
            self.assertEqual(sync_mock.call_args.kwargs["object_name"], "job_postings")
            self.assertEqual(sync_mock.call_args.kwargs["correlation_id"], "pipeline-import-002")
            self.assertEqual(sync_mock.call_args.kwargs["handoff_payload"]["agents_db_tree_path"], tree_data_rel_path)
            self.assertEqual(sync_mock.call_args.kwargs["handoff_payload"]["tree_data_path"], tree_data_rel_path)
        finally:
            os.unlink(job_postings_db_path)


if __name__ == "__main__":
    unittest.main()
