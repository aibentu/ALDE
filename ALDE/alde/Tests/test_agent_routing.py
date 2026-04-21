from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import alde.agents_factory as agents_factory
import alde.chat_completion as chat_mod
from alde import agents_configurator
from alde.agents_configurator import get_agent_workflow_config


def _tool_call(name: str, arguments: str, call_id: str = "call_1") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _FakeChatComE:
    last_messages = None
    last_tools = None
    last_model = None

    def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
        type(self).last_model = _model
        type(self).last_messages = list(_messages)
        type(self).last_tools = list(tools)

    def _response(self):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="xworker ok", tool_calls=None))])


class _FakeClient:
    class _Chat:
        class _Completions:
            @staticmethod
            def create(model=None, messages=None, tools=None, tool_choice=None):
                msg = SimpleNamespace(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "route_to_agent",
                            '{"target_agent":"_xworker","job_name":"document_dispatch","user_question":"please dispatch this request"}',
                        )
                    ],
                )
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)], id="resp_1")

        completions = _Completions()

    chat = _Chat()


class TestAgentRouting(unittest.TestCase):
    def setUp(self) -> None:
        chat_mod.ChatHistory._history_ = []
        agents_factory._WORKFLOW_SESSION_CACHE.clear()
        _FakeChatComE.last_messages = None
        _FakeChatComE.last_tools = None
        _FakeChatComE.last_model = None

    def test_routed_followup_uses_clean_handoff_messages(self) -> None:
        history = agents_factory.get_history()
        history._history_ = [
            {"role": "user", "content": "scan /tmp/jobs", "thread-id": history._thread_iD},
            {
                "role": "assistant",
                "content": "",
                "thread-id": history._thread_iD,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "route_to_agent", "arguments": '{"target_agent":"_xworker"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "content": "Routing to _xworker",
                "thread-id": history._thread_iD,
                "tool_call_id": "call_1",
                "name": "route_to_agent",
            },
        ]

        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[_tool_call("route_to_agent", '{"target_agent":"_xworker","user_question":"scan /tmp/jobs","job_name":"document_dispatch"}')],
        )

        with patch("alde.chat_completion.ChatComE", _FakeChatComE):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_xplaner_xrouter")

        self.assertEqual(result, "xworker ok")
        self.assertIsNotNone(_FakeChatComE.last_messages)
        self.assertEqual(_FakeChatComE.last_messages[0]["role"], "system")
        self.assertEqual(_FakeChatComE.last_messages[-1]["role"], "user")
        self.assertIn('"handoff_to": "_xworker"', _FakeChatComE.last_messages[-1]["content"])

    def test_primary_chatcom_routes_with_xplaner_label(self) -> None:
        captured: dict[str, object] = {}

        def _fake_handle_tool_calls(agent_msg, depth=0, ChatCom=None, agent_label=""):
            captured["agent_label"] = agent_label
            return "ok"

        with patch.object(chat_mod.ChatCompletion, "_get_client", return_value=_FakeClient()), patch(
            "alde.agents_factory._handle_tool_calls", side_effect=_fake_handle_tool_calls
        ):
            chat = chat_mod.ChatCom(_model="gpt-4o-mini", _input_text="please dispatch this request")
            result = chat.get_response()

        self.assertEqual(result, "ok")
        self.assertEqual(captured.get("agent_label"), "_xplaner_xrouter")
        self.assertEqual(chat._instance_policy, "session_scoped")
        self.assertEqual(chat._agent_runtime.get("role"), "xplaner_xrouter")

    def test_latest_user_message_returns_last_non_empty_user_entry(self) -> None:
        history = agents_factory.get_history()
        history._history_ = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "   "},
            {"role": "user", "content": "final question"},
        ]

        result = agents_factory._latest_user_message("fallback")

        self.assertEqual(result, "final question")

    def test_routed_agent_keeps_xworker_label_for_nested_tool_followup(self) -> None:
        captured_calls: list[dict[str, object]] = []

        class _SequencedChatComE:
            responses = [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="",
                                tool_calls=[
                                    _tool_call(
                                        "vdb_worker",
                                        '{"operation":"create","store":{"name":"VSM_5_Data"}}',
                                        call_id="call_2",
                                    )
                                ],
                            )
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="vector db built",
                                tool_calls=None,
                            )
                        )
                    ]
                ),
            ]

            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                captured_calls.append(
                    {
                        "model": _model,
                        "messages": list(_messages),
                        "tools": list(tools),
                        "tool_choice": tool_choice,
                    }
                )

            def _response(self):
                return type(self).responses.pop(0)

        history = agents_factory.get_history()
        history._history_ = [{"role": "user", "content": "build vectordb", "thread-id": history._thread_iD}]
        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "route_to_agent",
                    '{"target_agent":"_xworker","job_name":"document_dispatch","user_question":"build vectordb"}',
                    call_id="call_1",
                )
            ],
        )

        expected_worker_tools = agents_factory.get_agent_runtime_tools("_xworker")

        with patch("alde.chat_completion.ChatComE", _SequencedChatComE), patch(
            "alde.agents_factory.execute_tool",
            side_effect=[
                (
                    "Routing to _xworker",
                    {
                        "messages": [
                            {"role": "system", "content": "xworker system"},
                            {"role": "user", "content": "build vectordb"},
                        ],
                        "agent_label": "_xworker",
                        "tools": expected_worker_tools,
                        "model": agents_factory.AGENTS_REGISTRY["_xworker"]["model"],
                        "include_history": False,
                    },
                ),
                (
                    '{"operation":"create","store":{"name":"VSM_5_Data"}}',
                    None,
                ),
            ],
        ):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_xplaner_xrouter")

        self.assertEqual(result, '{"operation":"create","store":{"name":"VSM_5_Data"}}')
        self.assertEqual(len(captured_calls), 1)
        self.assertEqual(captured_calls[0]["tools"], expected_worker_tools)
        self.assertEqual(captured_calls[0]["model"], agents_factory.AGENTS_REGISTRY["_xworker"]["model"])
        self.assertEqual(chat_mod.ChatHistory._history_[-1]["assistant-name"], "_xworker")

    def test_followup_request_uses_routing_request_configuration(self) -> None:
        history = SimpleNamespace(
            _insert=lambda tool, f_depth: [{"role": "assistant", "content": f"history:{f_depth}"}],
        )

        request = agents_factory.TOOL_CALL_FOLLOWUP_SERVICE.build_object_request(
            history=history,
            routing_request={
                "messages": {"role": "user", "content": "dispatch this"},
                "include_history": True,
                "history_depth": "7",
                "tools": [{"function": {"name": "vdb_worker"}}],
                "model": "gpt-test",
                "agent_label": "_xworker",
            },
            agent_label="_xplaner_xrouter",
        )

        self.assertEqual(
            request["messages"],
            [
                {"role": "user", "content": "dispatch this"},
                {"role": "assistant", "content": "history:7"},
            ],
        )
        self.assertEqual(request["model"], "gpt-test")
        self.assertEqual(request["tools"], [{"function": {"name": "vdb_worker"}}])

    def test_non_routed_followup_logs_assistant_response_phase(self) -> None:
        class _TextOnlyChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                self._model = _model

            def _response(self):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="final tool summary", tool_calls=None))]
                )

        history = agents_factory.get_history()
        history._history_ = [{"role": "user", "content": "run write_document", "thread-id": history._thread_iD}]
        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[_tool_call("write_document", '{"content":"hello","path":"/tmp","titel":"x"}')],
        )

        with patch("alde.chat_completion.ChatComE", _TextOnlyChatComE), patch(
            "alde.agents_factory.execute_tool",
            return_value=("saved document", None),
        ):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_xworker")

        self.assertEqual(result, "saved document")
        workflow_entries = [
            entry for entry in chat_mod.ChatHistory._history_
            if isinstance(entry, dict)
            and isinstance(entry.get("data"), dict)
            and isinstance((entry.get("data") or {}).get("workflow"), dict)
            and entry.get("role") == "assistant"
        ]
        self.assertTrue(workflow_entries)
        self.assertEqual(workflow_entries[-1]["content"], "saved document")
        self.assertEqual(workflow_entries[-1]["data"]["workflow"].get("phase"), "assistant_response")

    def test_only_xplaner_retains_router_workflow(self) -> None:
        self.assertEqual(get_agent_workflow_config("_xplaner_xrouter").get("name"), "xplaner_xrouter_router")
        self.assertEqual(get_agent_workflow_config("_xworker").get("name"), "xworker_leaf")

    def test_xplaner_workflow_supports_branch_merge_conditions(self) -> None:
        session = agents_factory._create_workflow_session("_xplaner_xrouter")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "xplaner_ready")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="tool",
            event_name="route_to_agent",
            payload={"target_agent": "_xworker"},
        )
        self.assertEqual(session["current_state"], "xworker_delegated")
        self.assertFalse(session["terminal"])

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="routed_agent_complete",
            payload={"target_agent": "_xworker"},
        )
        self.assertEqual(session["current_state"], "workflow_complete")
        self.assertTrue(session["terminal"])

    def test_worker_runtime_tools_exclude_route_to_agent(self) -> None:
        worker_tools = agents_factory.get_agent_runtime_tools("_xworker")
        tool_names = {tool["function"]["name"] for tool in worker_tools}

        self.assertNotIn("route_to_agent", tool_names)
        self.assertFalse(agents_factory._agent_can_route("_xworker"))

    def test_planner_runtime_tools_include_route_to_agent(self) -> None:
        planner_tools = agents_factory.get_agent_runtime_tools("_xplaner_xrouter")
        tool_names = {tool["function"]["name"] for tool in planner_tools}

        self.assertIn("route_to_agent", tool_names)
        self.assertTrue(agents_factory._agent_can_route("_xplaner_xrouter"))

    def test_create_agents_command_resolves_to_xplaner_planning_job(self) -> None:
        route = agents_configurator.resolve_forced_route(
            "_xplaner_xrouter",
            "/create agents build a qa system with planner and worker",
            set(agents_factory.AGENTS_REGISTRY.keys()),
        )

        self.assertIsNotNone(route)
        self.assertEqual(route["target_agent"], "_xplaner_xrouter")
        self.assertEqual(route["job_name"], "agent_system_planning")
        self.assertEqual(route["user_question"], "build a qa system with planner and worker")

    def test_available_job_names_include_runtime_default_jobs(self) -> None:
        job_names = agents_configurator.get_available_job_names()

        self.assertIn("interactive_planning", job_names)
        self.assertIn("generic_execution", job_names)

    def test_job_config_drives_default_object_projection(self) -> None:
        job_config = agents_configurator.get_job_config("cover_letter_writer")

        self.assertEqual(job_config.get("default_object_name"), "cover_letters")

    def test_worker_route_to_agent_is_denied(self) -> None:
        result, route = agents_factory.execute_route_to_agent(
            {"target_agent": "_xplaner_xrouter", "user_question": "continue this thread"},
            source_agent_label="_xworker",
        )

        self.assertIn("Routing denied", result)
        self.assertIsNone(route)

    def test_worker_internal_auto_handoff_self_route_is_allowed(self) -> None:
        result, route = agents_factory.execute_tool(
            "route_to_agent",
            {
                "target_agent": "_xworker",
                "job_name": "job_posting_parser",
                "handoff_protocol": "agent_handoff_v1",
                "allow_internal_handoff": True,
                "handoff_payload": {
                    "agent_label": "_xworker",
                    "handoff_to": "_xworker",
                    "output": {
                        "type": "file",
                        "correlation_id": "sha-123",
                        "link": {"thread_id": "thread-1", "message_id": "msg-1"},
                        "file": {
                            "path": "/tmp/job_offer.pdf",
                            "content_sha256": "sha-123",
                        },
                        "db": {"processing_state": "queued"},
                        "requested_actions": [
                            "parse",
                            "extract_text",
                            "store_object_result",
                            "mark_processed_on_success",
                        ],
                    },
                },
                "handoff_metadata": {
                    "correlation_id": "sha-123",
                    "dispatcher_message_id": "dispatcher-msg-1",
                    "dispatcher_db_path": "/tmp/dispatcher_doc_db.json",
                    "obj_name": "job_postings",
                    "obj_db_path": "/tmp/job_postings_db.json",
                },
            },
            source_agent_label="_xworker",
        )

        self.assertEqual(result, "Routing to _xworker")
        self.assertIsInstance(route, dict)
        self.assertEqual(route.get("agent_label"), "_xworker")

    def test_worker_internal_handoff_flag_does_not_allow_cross_agent_route(self) -> None:
        result, route = agents_factory.execute_tool(
            "route_to_agent",
            {
                "target_agent": "_xplaner_xrouter",
                "allow_internal_handoff": True,
                "user_question": "continue this thread",
            },
            source_agent_label="_xworker",
        )

        self.assertIn("Tool 'route_to_agent' is not allowed for agent _xworker", result)
        self.assertIsNone(route)

    def test_route_contract_prefers_two_agent_schema(self) -> None:
        contract = agents_configurator.get_handoff_route_contract(
            "_xplaner_xrouter",
            "_xworker",
        )

        self.assertEqual(contract["protocol"], "agent_handoff_v1")
        self.assertEqual(contract["handoff_schema"], "xplaner_to_xworker")
        self.assertEqual(contract["handoff_id"], "structured")
        self.assertEqual(contract["workflow_name"], "xworker_leaf")

    def test_route_to_agent_normalizes_structured_agent_handoff(self) -> None:
        result, route = agents_factory.execute_route_to_agent(
            {
                "target_agent": "_xworker",
                "handoff_protocol": "agent_handoff_v1",
                "agent_response": {
                    "agent_label": "_xplaner_xrouter",
                    "output": {"status": "ready", "value": 42},
                    "handoff_to": "_xworker",
                    "job_name": "cover_letter_writer",
                },
                "handoff_metadata": {"correlation_id": "corr-1"},
            },
            source_agent_label="_xplaner_xrouter",
        )

        self.assertEqual(result, "Routing to _xworker")
        self.assertIsNotNone(route)
        self.assertEqual(route["agent_label"], "_xworker")
        self.assertEqual(len(route["messages"]), 3)
        self.assertEqual(route["messages"][1]["role"], "system")
        self.assertIn("Structured handoff context", route["messages"][1]["content"])
        handoff_context = json.loads(route["messages"][1]["content"].split("\n", 1)[1])
        self.assertEqual(handoff_context["protocol"], "agent_handoff_v1")
        self.assertEqual(handoff_context["target_agent"], "_xworker")
        self.assertEqual(handoff_context["metadata"]["correlation_id"], "corr-1")
        self.assertEqual(route["handoff_context"]["contract"]["handoff_schema"], "xplaner_to_xworker")
        self.assertEqual(route["handoff_context"]["contract"]["handoff_id"], "cover_letter_writer")
        self.assertEqual(route["handoff_context"]["contract"]["job_name"], "cover_letter_writer")

    def test_route_to_agent_rejects_missing_job_name_for_xworker(self) -> None:
        result, route = agents_factory.execute_route_to_agent(
            {
                "target_agent": "_xworker",
                "user_question": "continue this thread",
            },
            source_agent_label="_xplaner_xrouter",
        )

        self.assertEqual(result, "Invalid route_to_agent payload for _xworker: missing required job_name")
        self.assertIsNone(route)

    def test_dispatch_documents_returns_tool_result_without_followup_when_no_handoff_exists(self) -> None:
        history = agents_factory.get_history()
        history._thread_iD = 655
        history._history_ = [{"role": "user", "content": "scan this folder", "thread-id": history._thread_iD}]

        dispatch_result = {
            "agent": "xworker",
            "job_name": "document_dispatch",
            "scan_dir": "/tmp/jobs",
            "processed": 0,
            "handoff_messages": [],
        }
        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "dispatch_documents",
                    json.dumps(
                        {
                            "scan_dir": "/tmp/jobs",
                            "db_path": "/tmp/dispatcher.json",
                        },
                        ensure_ascii=False,
                    ),
                    call_id="call_dispatcher_terminal",
                )
            ],
        )

        with patch("alde.chat_completion.ChatComE") as chat_cls, patch(
            "alde.agents_factory.execute_tool",
            return_value=(dispatch_result, None),
        ):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_xworker")

        self.assertEqual(result, json.dumps(dispatch_result, ensure_ascii=False))
        chat_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()