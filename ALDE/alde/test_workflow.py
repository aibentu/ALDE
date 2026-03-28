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

import alde.agents_ccompletion as chat_mod
import alde.agents_factory as agents_factory
import alde.tools as tools_mod


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

        self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
        self.assertEqual(chat._forced_route["handoff_protocol"], "agent_handoff_v1")
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

        self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
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

        self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
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

            self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
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

            self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
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

            self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
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

            self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
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

            self.assertEqual(chat._forced_route["target_agent"], "_cover_letter_agent")
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
        self.assertEqual(forced_route["target_agent"], "_cover_letter_agent")
        self.assertEqual(forced_route["handoff_protocol"], "agent_handoff_v1")
        self.assertEqual(forced_route["agent_response"]["handoff_to"], "_cover_letter_agent")
        self.assertEqual(forced_route["agent_response"]["agent_label"], "_primary_assistant")
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
                source_agent_label="_data_dispatcher",
            )

            result = json.loads(result_text)
            stored = tools_mod.DOCUMENT_REPOSITORY.get_document("platform:dispatcher-21", db_path=job_postings_db_path, obj_name="job_postings")
            self.assertIsNone(routing_request)
            self.assertTrue(result["ok"])
            self.assertEqual(stored["job_posting"]["job_title"], "Automation Engineer")
            self.assertEqual(stored["parse"]["is_job_posting"], True)
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
                source_agent_label="_data_dispatcher",
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
                    "Routing to _cover_letter_agent",
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
                        "agent_label": "_cover_letter_agent",
                        "tools": [],
                        "model": "gpt-4o",
                        "include_history": False,
                        "handoff": {
                            "protocol": "agent_handoff_v1",
                            "source_agent": "_primary_assistant",
                            "target_agent": "_cover_letter_agent",
                            "handoff_payload": {
                                "agent_label": "_primary_assistant",
                                "handoff_to": "_cover_letter_agent",
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
        self.assertEqual(routed["target_agent"], "_cover_letter_agent")
        self.assertEqual(routed["handoff_protocol"], "agent_handoff_v1")
        self.assertEqual(routed["agent_response"]["handoff_to"], "_cover_letter_agent")
        self.assertEqual(routed["agent_response"]["output"]["profile_result"]["profile"]["profile_id"], "profile:test")

    def test_ready_forced_route_executes_via_structured_handoff_path(self) -> None:
        captured_execute_tool_calls: list[tuple[str, dict]] = []

        def _fake_execute_tool(name: str, args: dict, tool_call_id: str = None, source_agent_label: str = None):
            captured_execute_tool_calls.append((name, dict(args)))
            if name == "route_to_agent":
                return (
                    "Routing to _cover_letter_agent",
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
                        "agent_label": "_cover_letter_agent",
                        "tools": [],
                        "model": "gpt-4o",
                        "include_history": False,
                        "handoff": {
                            "protocol": "agent_handoff_v1",
                            "source_agent": "_primary_assistant",
                            "target_agent": "_cover_letter_agent",
                            "handoff_payload": {
                                "agent_label": "_primary_assistant",
                                "handoff_to": "_cover_letter_agent",
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
        self.assertEqual(routed["target_agent"], "_cover_letter_agent")
        self.assertEqual(routed["handoff_protocol"], "agent_handoff_v1")
        self.assertEqual(routed["agent_response"]["handoff_to"], "_cover_letter_agent")
        self.assertEqual(routed["agent_response"]["output"]["job_posting_result"]["correlation_id"], "sha-direct-1")


if __name__ == "__main__":
    unittest.main()
