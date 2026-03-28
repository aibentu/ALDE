from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import alde.agents_factory as agents_factory
import alde.chat_completion as chat_mod
import alde.tools as tools_mod
from alde import agents_config
from alde.agents_config import _SYSTEM_PROMPT, get_agent_workflow_config, normalize_agent_name


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
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="dispatcher ok", tool_calls=None))])


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
                            '{"target_agent":"_data_dispatcher","user_question":"scan /tmp/jobs"}',
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
                        "function": {"name": "route_to_agent", "arguments": '{"target_agent":"_data_dispatcher"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "content": "Routing to _data_dispatcher",
                "thread-id": history._thread_iD,
                "tool_call_id": "call_1",
                "name": "route_to_agent",
            },
        ]

        agent_msg = SimpleNamespace(content="", tool_calls=[_tool_call("route_to_agent", '{"target_agent":"_data_dispatcher","user_question":"scan /tmp/jobs"}')])

        with patch("alde.chat_completion.ChatComE", _FakeChatComE):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_primary_assistant")

        self.assertEqual(result, "dispatcher ok")
        self.assertIsNotNone(_FakeChatComE.last_messages)
        self.assertEqual(len(_FakeChatComE.last_messages), 2)
        self.assertEqual(_FakeChatComE.last_messages[0]["role"], "system")
        self.assertEqual(_FakeChatComE.last_messages[1], {"role": "user", "content": "scan /tmp/jobs"})

    def test_primary_chatcom_routes_with_primary_label(self) -> None:
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
        self.assertEqual(captured.get("agent_label"), "_primary_assistant")
        self.assertEqual(chat._instance_policy, "session_scoped")
        self.assertEqual(chat._agent_runtime.get("role"), "planner_router")

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

    def test_routed_agent_keeps_its_label_for_nested_tool_followup(self) -> None:
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
                                        '{"operation":"create","store":"VSM_5_Data"}',
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
                    '{"target_agent":"_data_dispatcher","user_question":"build vectordb"}',
                    call_id="call_1",
                )
            ],
        )

        expected_dispatcher_tools = agents_factory.get_agent_runtime_tools("_data_dispatcher")

        with patch("alde.chat_completion.ChatComE", _SequencedChatComE), patch(
            "alde.agents_factory.execute_tool",
            side_effect=[
                (
                    "Routing to _data_dispatcher",
                    {
                        "messages": [
                            {"role": "system", "content": "dispatcher system"},
                            {"role": "user", "content": "build vectordb"},
                        ],
                        "agent_label": "_data_dispatcher",
                        "tools": expected_dispatcher_tools,
                        "model": agents_factory.AGENTS_REGISTRY["_data_dispatcher"]["model"],
                        "include_history": False,
                    },
                ),
                (
                    '{"operation":"create","store":{"name":"VSM_5_Data"}}',
                    None,
                ),
            ],
        ):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_primary_assistant")

        self.assertEqual(result, "vector db built")
        self.assertEqual(len(captured_calls), 2)
        self.assertEqual(captured_calls[0]["tools"], expected_dispatcher_tools)
        self.assertEqual(captured_calls[1]["tools"], expected_dispatcher_tools)
        self.assertEqual(captured_calls[1]["model"], agents_factory.AGENTS_REGISTRY["_data_dispatcher"]["model"])
        self.assertEqual(chat_mod.ChatHistory._history_[-1]["assistant-name"], "_data_dispatcher")

        workflow_entries = [entry for entry in chat_mod.ChatHistory._history_ if isinstance(entry, dict) and isinstance(entry.get("data"), dict) and isinstance(entry.get("data", {}).get("workflow"), dict)]
        self.assertTrue(workflow_entries)
        self.assertTrue(any(entry["data"]["workflow"].get("phase") == "tool_result" for entry in workflow_entries))
        self.assertTrue(any(entry["data"]["workflow"].get("workflow_name") == "data_dispatcher_chain" for entry in workflow_entries))
        self.assertTrue(any(entry["data"]["workflow"].get("runtime", {}).get("instance_policy") == "workflow_scoped" for entry in workflow_entries))

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
                "tools": [{"function": {"name": "route_to_agent"}}],
                "model": "gpt-test",
                "agent_label": "_data_dispatcher",
            },
            agent_label="_primary_assistant",
        )

        self.assertEqual(
            request["messages"],
            [
                {"role": "user", "content": "dispatch this"},
                {"role": "assistant", "content": "history:7"},
            ],
        )
        self.assertEqual(request["model"], "gpt-test")
        self.assertEqual(request["tools"], [{"function": {"name": "route_to_agent"}}])

    def test_history_mirrors_workflow_status_for_failure(self) -> None:
        class _FailingChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                self._model = _model

            def _response(self):
                raise RuntimeError("backend unavailable")

        history = agents_factory.get_history()
        history._history_ = [{"role": "user", "content": "scan /tmp/jobs", "thread-id": history._thread_iD}]
        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[_tool_call("route_to_agent", '{"target_agent":"_data_dispatcher","user_question":"scan /tmp/jobs"}')],
        )

        with patch("alde.chat_completion.ChatComE", _FailingChatComE):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_primary_assistant")

        self.assertIn("Follow-up model call failed", result)
        mirrored = [
            entry for entry in chat_mod.ChatHistory._history_
            if isinstance(entry, dict)
            and isinstance(entry.get("data"), dict)
            and isinstance(entry.get("data", {}).get("workflow"), dict)
        ]
        self.assertTrue(mirrored)
        failure_entries = [entry for entry in mirrored if entry["data"]["workflow"].get("phase") == "model_failure"]
        self.assertTrue(failure_entries)
        failure_workflow = failure_entries[-1]["data"]["workflow"]
        self.assertEqual(failure_workflow.get("current_state"), "assistant_retry_pending")
        self.assertEqual(failure_workflow.get("retry", {}).get("attempt_count"), 1)
        self.assertEqual(failure_workflow.get("event", {}).get("name"), "model_failed")

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
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_writer_agent")

        self.assertEqual(result, "final tool summary")
        workflow_entries = [
            entry for entry in chat_mod.ChatHistory._history_
            if isinstance(entry, dict)
            and isinstance(entry.get("data"), dict)
            and isinstance((entry.get("data") or {}).get("workflow"), dict)
            and entry.get("role") == "assistant"
        ]
        self.assertTrue(workflow_entries)
        latest_workflow = workflow_entries[-1]["data"]["workflow"]
        self.assertEqual(latest_workflow.get("phase"), "assistant_response")
        self.assertEqual(latest_workflow.get("event", {}).get("name"), "followup_complete")

    def test_only_primary_assistant_retains_router_workflow(self) -> None:
        self.assertEqual(get_agent_workflow_config("_primary_assistant").get("name"), "primary_assistant_router")
        self.assertEqual(get_agent_workflow_config("_parser_agent").get("name"), "parser_agent_leaf")
        self.assertEqual(get_agent_workflow_config("_writer_agent").get("name"), "writer_agent_leaf")

    def test_primary_workflow_supports_branch_merge_conditions(self) -> None:
        session = agents_factory._create_workflow_session("_primary_assistant")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "assistant_ready")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="tool",
            event_name="route_to_agent",
            payload={"target_agent": "_writer_agent"},
        )
        self.assertEqual(session["current_state"], "writer_delegated")
        self.assertFalse(session["terminal"])

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="routed_agent_complete",
            payload={"target_agent": "_writer_agent"},
        )
        self.assertEqual(session["current_state"], "workflow_complete")
        self.assertTrue(session["terminal"])

    def test_nested_routing_emits_parent_completion_event(self) -> None:
        captured_events: list[tuple[str, str, dict[str, object] | None]] = []
        real_advance = agents_factory._advance_workflow_session

        def _tracking_advance(workflow_session, *, event_kind, event_name, payload=None):
            captured_events.append((event_kind, event_name, payload))
            return real_advance(
                workflow_session,
                event_kind=event_kind,
                event_name=event_name,
                payload=payload,
            )

        class _RoutedWriterChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                self._model = _model

            def _response(self):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="writer ok", tool_calls=None))]
                )

        history = agents_factory.get_history()
        history._history_ = [{"role": "user", "content": "write a cover letter", "thread-id": history._thread_iD}]
        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "route_to_agent",
                    '{"target_agent":"_writer_agent","user_question":"write a cover letter"}',
                    call_id="call_1",
                )
            ],
        )
        writer_tools = agents_factory.get_agent_runtime_tools("_writer_agent")

        with patch("alde.chat_completion.ChatComE", _RoutedWriterChatComE), patch(
            "alde.agents_factory.execute_tool",
            return_value=(
                "Routing to _writer_agent",
                {
                    "messages": [
                        {"role": "system", "content": "writer system"},
                        {"role": "user", "content": "write a cover letter"},
                    ],
                    "agent_label": "_writer_agent",
                    "tools": writer_tools,
                    "model": agents_factory.AGENTS_REGISTRY["_writer_agent"]["model"],
                    "include_history": False,
                },
            ),
        ), patch("alde.agents_factory._advance_workflow_session", side_effect=_tracking_advance):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_primary_assistant")

        self.assertEqual(result, "writer ok")
        self.assertTrue(
            any(
                event_kind == "state"
                and event_name == "routed_agent_complete"
                and isinstance(payload, dict)
                and payload.get("target_agent") == "_writer_agent"
                for event_kind, event_name, payload in captured_events
            )
        )

    def test_vdb_worker_forwards_doc_types(self) -> None:
        with patch.object(tools_mod, "_run_vdb_admin_subprocess", return_value={"ok": True}) as run_admin:
            result = tools_mod.vdb_worker(
                operation="build",
                store="VSM_5_Data",
                root_dir="/tmp/project",
                doc_types=[".txt", ".md"],
                chunk_strategy="character",
                chunk_size=600,
                overlap=120,
            )

        self.assertEqual(result, {"ok": True})
        run_admin.assert_called_once_with(
            operation="build",
            store="VSM_5_Data",
            root_dir="/tmp/project",
            doc_types=[".txt", ".md"],
            chunk_strategy="character",
            chunk_size=600,
            overlap=120,
            force=False,
            remove_store_dir=False,
        )

    def test_worker_runtime_tools_exclude_route_to_agent(self) -> None:
        worker_tools = agents_factory.get_agent_runtime_tools("_writer_agent")
        tool_names = {tool["function"]["name"] for tool in worker_tools}

        self.assertNotIn("route_to_agent", tool_names)
        self.assertFalse(agents_factory._agent_can_route("_writer_agent"))

    def test_dispatcher_runtime_tools_include_route_to_agent(self) -> None:
        dispatcher_tools = agents_factory.get_agent_runtime_tools("_data_dispatcher")
        tool_names = {tool["function"]["name"] for tool in dispatcher_tools}

        self.assertIn("route_to_agent", tool_names)
        self.assertTrue(agents_factory._agent_can_route("_data_dispatcher"))

    def test_agent_system_worker_runtime_tools_include_builder_tool(self) -> None:
        worker_tools = agents_factory.get_agent_runtime_tools("_agent_system_worker")
        tool_names = {tool["function"]["name"] for tool in worker_tools}

        self.assertIn("build_agent_system_configs", tool_names)
        self.assertNotIn("route_to_agent", tool_names)
        self.assertFalse(agents_factory._agent_can_route("_agent_system_worker"))

    def test_create_agents_command_resolves_to_agent_system_planner(self) -> None:
        route = agents_config.resolve_forced_route(
            "_primary_assistant",
            "/create agents build a qa system with planner and worker",
            set(agents_factory.AGENTS_REGISTRY.keys()),
        )

        self.assertIsNotNone(route)
        self.assertEqual(route["target_agent"], "_agent_system_planner")
        self.assertEqual(route["user_question"], "build a qa system with planner and worker")

    def test_worker_route_to_agent_is_denied(self) -> None:
        result, route = agents_factory.execute_route_to_agent(
            {"target_agent": "_data_dispatcher", "user_question": "scan /tmp/jobs"},
            source_agent_label="_writer_agent",
        )

        self.assertIn("Routing denied", result)
        self.assertIsNone(route)

    def test_session_scoped_target_exposes_routed_history_policy(self) -> None:
        result, route = agents_factory.execute_route_to_agent(
            {"target_agent": "_primary_assistant", "user_question": "continue this thread"},
            source_agent_label="_primary_assistant",
        )

        self.assertEqual(result, "Routing to _primary_assistant")
        self.assertIsNotNone(route)
        self.assertTrue(route["include_history"])
        self.assertEqual(route["history_depth"], 12)
        self.assertEqual(route["runtime"]["history_policy"]["routed_history_depth"], 12)

    def test_dispatch_documents_auto_routes_handoff_messages(self) -> None:
        captured_calls: list[dict[str, object]] = []
        real_execute_tool = agents_factory.execute_tool

        class _SequencedChatComE:
            responses = [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="parser ok",
                                tool_calls=None,
                            )
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="dispatcher summary",
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
                    }
                )

            def _response(self):
                return type(self).responses.pop(0)

        def _fake_execute_tool(name, args, tool_call_id=None, *, source_agent_label=None):
            if name == "dispatch_documents":
                return (
                    {
                        "agent": "data_dispatcher",
                        "handoff_messages": [
                            {
                                "target_agent": "_job_posting_parser",
                                "handoff_protocol": "agent_handoff_v1",
                                "message_text": json.dumps(
                                    {
                                        "protocol": "agent_handoff_v1",
                                        "source_agent": "_data_dispatcher",
                                        "target_agent": "_job_posting_parser",
                                    },
                                    ensure_ascii=False,
                                ),
                                "handoff_payload": {
                                    "agent_label": "_data_dispatcher",
                                    "handoff_to": "_job_posting_parser",
                                    "output": {
                                        "type": "job_posting_pdf",
                                        "correlation_id": "sha-1",
                                        "link": {"thread_id": "thread-1", "message_id": "PENDING"},
                                        "file": {"path": "/tmp/posting.pdf", "content_sha256": "sha-1"},
                                        "db": {"processing_state": "queued"},
                                        "requested_actions": ["parse"],
                                    },
                                },
                                "handoff_metadata": {
                                    "correlation_id": "sha-1",
                                    "dispatcher_message_id": "disp-1",
                                    "dispatcher_db_path": "/tmp/dispatcher.json",
                                    "obj_name": "job_postings",
                                    "obj_db_path": "/tmp/job_postings.json",
                                },
                            }
                        ],
                    },
                    None,
                )
            return real_execute_tool(
                name,
                args,
                tool_call_id,
                source_agent_label=source_agent_label,
            )

        history = agents_factory.get_history()
        history._history_ = [{"role": "user", "content": "scan jobs", "thread-id": history._thread_iD}]
        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "dispatch_documents",
                    '{"scan_dir":"/tmp/jobs","db_path":"/tmp/db.json","thread_id":"thread-1","dispatcher_message_id":"disp-1"}',
                    call_id="call_dispatch",
                )
            ],
        )

        with patch("alde.chat_completion.ChatComE", _SequencedChatComE), patch(
            "alde.agents_factory.execute_tool",
            side_effect=_fake_execute_tool,
        ):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_data_dispatcher")

        self.assertEqual(result, "dispatcher summary")
        self.assertEqual(len(captured_calls), 2)
        self.assertEqual(captured_calls[0]["model"], agents_factory.AGENTS_REGISTRY["_job_posting_parser"]["model"])
        self.assertEqual(captured_calls[1]["model"], agents_factory.AGENTS_REGISTRY["_data_dispatcher"]["model"])
        self.assertEqual(captured_calls[0]["messages"][1]["role"], "system")
        self.assertIn("Structured handoff context", captured_calls[0]["messages"][1]["content"])
        self.assertIn('"correlation_id": "sha-1"', captured_calls[0]["messages"][2]["content"])
        self.assertIn('"obj_db_path": "/tmp/job_postings.json"', captured_calls[0]["messages"][1]["content"])
        tool_entries = [entry for entry in chat_mod.ChatHistory._history_ if entry.get("role") == "tool"]
        self.assertTrue(any("handoff_results" in str(entry.get("content") or "") for entry in tool_entries))

    def test_route_to_agent_normalizes_structured_agent_handoff(self) -> None:
        result, route = agents_factory.execute_route_to_agent(
            {
                "handoff_protocol": "agent_handoff_v1",
                "agent_response": {
                    "agent_label": "_primary_assistant",
                    "output": {"status": "ready", "value": 42},
                    "handoff_to": "_writer_agent",
                },
                "handoff_metadata": {"correlation_id": "corr-1"},
            },
            source_agent_label="_primary_assistant",
        )

        self.assertEqual(result, "Routing to _writer_agent")
        self.assertIsNotNone(route)
        self.assertEqual(route["agent_label"], "_writer_agent")
        self.assertEqual(len(route["messages"]), 3)
        self.assertEqual(route["messages"][1]["role"], "system")
        self.assertIn("Structured handoff context", route["messages"][1]["content"])
        handoff_context = json.loads(route["messages"][1]["content"].split("\n", 1)[1])
        self.assertEqual(handoff_context["protocol"], "agent_handoff_v1")
        self.assertEqual(handoff_context["target_agent"], "_writer_agent")
        self.assertEqual(handoff_context["selected_input"], {"status": "ready", "value": 42})
        self.assertEqual(handoff_context["metadata"]["correlation_id"], "corr-1")
        self.assertEqual(json.loads(route["messages"][2]["content"]), {"status": "ready", "value": 42})
        self.assertEqual(route["handoff"]["handoff_payload"]["handoff_to"], "_writer_agent")
        self.assertEqual(route["handoff_context"]["contract"]["handoff_schema"], "primary_to_writer_brief")

    def test_routing_handoff_view_extracts_metadata_and_paths(self) -> None:
        routing_request = {
            "agent_label": "_job_posting_parser",
            "handoff": {
                "source_agent": "_data_dispatcher",
                "target_agent": "_job_posting_parser",
                "handoff_payload": {
                    "correlation_id": "corr-2",
                    "output": {"correlation_id": "corr-2-out"},
                },
                "metadata": {
                    "correlation_id": "corr-2-meta",
                    "dispatcher_db_path": "/tmp/dispatcher.json",
                    "obj_name": "job_postings",
                    "obj_db_path": "/tmp/job_postings.json",
                },
            },
            "handoff_context": {
                "source_agent": "_data_dispatcher",
                "contract": {
                    "schema": {
                        "result_postprocess": {"tool": "upsert_object_record"}
                    }
                },
            },
        }

        self.assertEqual(
            agents_factory.ROUTING_HANDOFF_VIEW_SERVICE.load_result_postprocess(routing_request),
            {"tool": "upsert_object_record"},
        )
        self.assertEqual(
            agents_factory.ROUTING_HANDOFF_VIEW_SERVICE.load_target_agent(routing_request),
            "_job_posting_parser",
        )
        self.assertEqual(
            agents_factory.ROUTING_HANDOFF_VIEW_SERVICE.load_source_agent(routing_request),
            "_data_dispatcher",
        )
        self.assertEqual(
            agents_factory.ROUTING_HANDOFF_VIEW_SERVICE.load_correlation_id(routing_request),
            "corr-2-meta",
        )
        self.assertEqual(
            agents_factory.ROUTING_HANDOFF_VIEW_SERVICE.load_dispatcher_paths(routing_request),
            ("/tmp/dispatcher.json", "/tmp/job_postings.json"),
        )

    def test_routing_result_object_prefers_metadata_correlation_and_source_agent(self) -> None:
        routing_request = {
            "agent_label": "_job_posting_parser",
            "handoff": {
                "source_agent": "_data_dispatcher",
                "target_agent": "_job_posting_parser",
                "handoff_payload": {
                    "correlation_id": "corr-payload",
                    "output": {"correlation_id": "corr-output"},
                },
                "metadata": {
                    "correlation_id": "corr-meta",
                    "dispatcher_db_path": "/tmp/dispatcher.json",
                    "obj_name": "job_postings",
                    "obj_db_path": "/tmp/job_postings.json",
                },
            },
            "handoff_context": {
                "source_agent": "_data_dispatcher",
                "contract": {
                    "schema": {
                        "result_postprocess": {
                            "tool": "upsert_object_record",
                            "source_agent": "source_agent",
                        }
                    }
                },
            },
        }

        result_object = agents_factory.ROUTING_RESULT_POSTPROCESS_SERVICE.load_object_result(
            routing_request,
            result_text='{"db_updates":{"processing_state":"processed","processed":true}}',
            succeeded=True,
        )

        self.assertTrue(result_object.load_valid_request())
        self.assertEqual(result_object.object_name, "upsert_object_record")
        self.assertEqual(result_object.obj_name, "job_postings")
        self.assertEqual(result_object.correlation_id, "corr-meta")
        self.assertEqual(result_object.load_source_agent(), "_data_dispatcher")
        self.assertEqual(result_object.dispatcher_db_path, "/tmp/dispatcher.json")
        self.assertEqual(result_object.obj_db_path, "/tmp/job_postings.json")

    def test_persist_document_artifacts_uses_output_override_and_job_posting_doc_id(self) -> None:
        parsed_result = {
            "document": {
                "full_text": "Generated cover letter",
                "header": {"subject": "Cover Letter"},
            }
        }
        handoff_payload = {
            "output": {
                "options": {"output_dir": "/tmp/custom_letters", "write_pdf": False},
                "job_posting_result": {
                    "job_posting": {
                        "job_title": "Python Engineer",
                        "company_name": "Example Co",
                    }
                },
                "profile_result": {
                    "profile": {
                        "personal_info": {"full_name": "Taylor Example"},
                    }
                },
            }
        }

        with patch("alde.agents_factory.os.makedirs") as makedirs, patch(
            "alde.agents_factory.write_document",
            return_value={"path": "/tmp/custom_letters/Python Engineer_Example Co.md"},
        ) as write_document, patch("alde.agents_factory.md_to_pdf") as md_to_pdf:
            result = agents_factory.ROUTING_RESULT_POSTPROCESS_SERVICE.persist_object_artifacts(
                result_postprocess={"tool": "persist_document_artifacts", "default_write_pdf": True},
                parsed_result=parsed_result,
                handoff_payload=handoff_payload,
                metadata={"correlation_id": "corr-42"},
                fallback_result_text="raw-result",
            )

        self.assertIsNotNone(result)
        makedirs.assert_called_once_with("/tmp/custom_letters", exist_ok=True)
        self.assertEqual(write_document.call_args.kwargs["path"], "/tmp/custom_letters")
        self.assertEqual(write_document.call_args.kwargs["doc_id"], "Python Engineer_Example Co")
        md_to_pdf.assert_not_called()
        self.assertEqual(result["result"]["document_text_path"], "/tmp/custom_letters/Python Engineer_Example Co.md")
        self.assertEqual(result["result"]["document_path"], "/tmp/custom_letters/Python Engineer_Example Co.md")

    def test_route_to_agent_rejects_target_outside_handoff_policy(self) -> None:
        result, route = agents_factory.execute_route_to_agent(
            {"target_agent": "_profile_parser", "message_text": "write this"},
            source_agent_label="_primary_assistant",
        )

        self.assertIn("handoff_policy.allowed_targets", result)
        self.assertIsNone(route)

    def test_validate_handoff_for_target_rejects_missing_dispatcher_fields(self) -> None:
        handoff = agents_config.build_agent_handoff(
            source_agent_label="_data_dispatcher",
            target_agent="_job_posting_parser",
            protocol="agent_handoff_v1",
            agent_response={
                "agent_label": "_data_dispatcher",
                "output": {
                    "type": "job_posting_pdf",
                    "file": {"path": "/tmp/posting.pdf"},
                },
                "handoff_to": "_job_posting_parser",
            },
            handoff_metadata={"correlation_id": "corr-7", "dispatcher_db_path": "/tmp/dispatcher.json", "obj_name": "job_postings", "obj_db_path": "/tmp/job_postings.json"},
        )

        report = agents_config.validate_handoff_for_target(
            "_job_posting_parser",
            handoff,
            source_agent_label="_data_dispatcher",
        )

        self.assertFalse(report["valid"])
        self.assertTrue(any("output.correlation_id" in err for err in report["errors"]))
        self.assertTrue(any("dispatcher_message_id" in err for err in report["errors"]))

    def test_dispatcher_routed_parser_success_updates_dispatcher_db(self) -> None:
        parser_result = json.dumps(
            {
                "db_updates": {
                    "correlation_id": "sha-2",
                    "processing_state": "processed",
                    "processed": True,
                    "failed_reason": None,
                }
            },
            ensure_ascii=False,
        )

        class _ParserChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                self._messages = _messages

            def _response(self):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=parser_result, tool_calls=None))]
                )

        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "route_to_agent",
                    json.dumps(
                        {
                            "target_agent": "_job_posting_parser",
                            "handoff_protocol": "agent_handoff_v1",
                            "handoff_payload": {
                                "agent_label": "_data_dispatcher",
                                "handoff_to": "_job_posting_parser",
                                "output": {
                                    "type": "job_posting_pdf",
                                    "correlation_id": "sha-2",
                                    "link": {"thread_id": "thread-2", "message_id": "PENDING"},
                                    "file": {"path": "/tmp/posting.pdf", "content_sha256": "sha-2"},
                                    "db": {"processing_state": "queued"},
                                    "requested_actions": ["parse"],
                                },
                            },
                            "handoff_metadata": {
                                "correlation_id": "sha-2",
                                "dispatcher_message_id": "disp-2",
                                "dispatcher_db_path": "/tmp/dispatcher.json",
                                "obj_name": "job_postings",
                                "obj_db_path": "/tmp/job_postings.json",
                            },
                        },
                        ensure_ascii=False,
                    ),
                    call_id="call_parser_success",
                )
            ],
        )

        with patch("alde.chat_completion.ChatComE", _ParserChatComE), patch(
            "alde.agents_factory.upsert_object_record_tool",
            return_value={"ok": True},
        ) as upsert_record:
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_data_dispatcher")

        self.assertEqual(result, parser_result)
        upsert_record.assert_called_once()
        self.assertEqual(upsert_record.call_args.kwargs["correlation_id"], "sha-2")
        self.assertEqual(upsert_record.call_args.kwargs["dispatcher_db_path"], "/tmp/dispatcher.json")
        self.assertEqual(upsert_record.call_args.kwargs["obj_db_path"], "/tmp/job_postings.json")
        self.assertEqual(upsert_record.call_args.kwargs["obj_name"], "job_postings")
        self.assertEqual(upsert_record.call_args.kwargs["processing_state"], "processed")
        self.assertTrue(upsert_record.call_args.kwargs["processed"])
        self.assertEqual(upsert_record.call_args.kwargs["source_agent"], "_job_posting_parser")
        self.assertEqual(
            upsert_record.call_args.kwargs["object_result"]["db_updates"]["processing_state"],
            "processed",
        )

    def test_dispatcher_routed_parser_success_persists_job_posting_store(self) -> None:
        parser_result = json.dumps(
            {
                "correlation_id": "sha-2b",
                "parse": {"is_job_posting": True, "language": "de", "errors": [], "warnings": []},
                "job_posting": {"job_title": "Python Engineer", "company_name": "Example Co"},
                "db_updates": {"correlation_id": "sha-2b", "processing_state": "processed", "processed": True},
            },
            ensure_ascii=False,
        )

        class _ParserChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                self._messages = _messages

            def _response(self):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=parser_result, tool_calls=None))]
                )

        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "route_to_agent",
                    json.dumps(
                        {
                            "target_agent": "_job_posting_parser",
                            "handoff_protocol": "agent_handoff_v1",
                            "handoff_payload": {
                                "agent_label": "_data_dispatcher",
                                "handoff_to": "_job_posting_parser",
                                "output": {
                                    "type": "job_posting_pdf",
                                    "correlation_id": "sha-2b",
                                    "link": {"thread_id": "thread-2", "message_id": "PENDING"},
                                    "file": {"path": "/tmp/posting.pdf", "content_sha256": "sha-2b"},
                                    "db": {"processing_state": "queued"},
                                    "requested_actions": ["parse", "store_object_result"],
                                },
                            },
                            "handoff_metadata": {
                                "correlation_id": "sha-2b",
                                "dispatcher_message_id": "disp-2b",
                                "dispatcher_db_path": "/tmp/dispatcher.json",
                                "obj_name": "job_postings",
                                "obj_db_path": "/tmp/job_postings.json",
                            },
                        },
                        ensure_ascii=False,
                    ),
                    call_id="call_parser_success_store",
                )
            ],
        )

        with patch("alde.chat_completion.ChatComE", _ParserChatComE), patch(
            "alde.agents_factory.upsert_object_record_tool",
            return_value={"ok": True, "obj_db_path": "/tmp/job_postings.json"},
        ) as upsert_record:
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_data_dispatcher")

        self.assertEqual(result, parser_result)
        upsert_record.assert_called_once()
        self.assertEqual(upsert_record.call_args.kwargs["correlation_id"], "sha-2b")
        self.assertEqual(upsert_record.call_args.kwargs["dispatcher_db_path"], "/tmp/dispatcher.json")
        self.assertEqual(upsert_record.call_args.kwargs["obj_db_path"], "/tmp/job_postings.json")
        self.assertEqual(upsert_record.call_args.kwargs["obj_name"], "job_postings")
        self.assertEqual(upsert_record.call_args.kwargs["object_result"]["job_posting"]["job_title"], "Python Engineer")
        self.assertEqual(upsert_record.call_args.kwargs["processing_state"], "processed")
        self.assertTrue(upsert_record.call_args.kwargs["processed"])

    def test_dispatcher_routed_parser_failure_updates_dispatcher_db(self) -> None:
        failure_text = "failed: parser backend unavailable"

        class _FailingParserChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                self._messages = _messages

            def _response(self):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=failure_text, tool_calls=None))]
                )

        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "route_to_agent",
                    json.dumps(
                        {
                            "target_agent": "_job_posting_parser",
                            "handoff_protocol": "agent_handoff_v1",
                            "handoff_payload": {
                                "agent_label": "_data_dispatcher",
                                "handoff_to": "_job_posting_parser",
                                "output": {
                                    "type": "job_posting_pdf",
                                    "correlation_id": "sha-3",
                                    "link": {"thread_id": "thread-3", "message_id": "PENDING"},
                                    "file": {"path": "/tmp/posting.pdf", "content_sha256": "sha-3"},
                                    "db": {"processing_state": "queued"},
                                    "requested_actions": ["parse"],
                                },
                            },
                            "handoff_metadata": {
                                "correlation_id": "sha-3",
                                "dispatcher_message_id": "disp-3",
                                "dispatcher_db_path": "/tmp/dispatcher.json",
                                "obj_name": "job_postings",
                                "obj_db_path": "/tmp/job_postings.json",
                            },
                        },
                        ensure_ascii=False,
                    ),
                    call_id="call_parser_failure",
                )
            ],
        )

        with patch("alde.chat_completion.ChatComE", _FailingParserChatComE), patch(
            "alde.agents_factory.upsert_object_record_tool",
            return_value={"ok": True},
        ) as upsert_record:
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_data_dispatcher")

        self.assertEqual(result, failure_text)
        upsert_record.assert_called_once()
        self.assertEqual(upsert_record.call_args.kwargs["correlation_id"], "sha-3")
        self.assertEqual(upsert_record.call_args.kwargs["dispatcher_db_path"], "/tmp/dispatcher.json")
        self.assertEqual(upsert_record.call_args.kwargs["obj_db_path"], "/tmp/job_postings.json")
        self.assertEqual(upsert_record.call_args.kwargs["obj_name"], "job_postings")
        self.assertEqual(upsert_record.call_args.kwargs["processing_state"], "failed")
        self.assertFalse(upsert_record.call_args.kwargs["processed"])
        self.assertIn("parser backend unavailable", upsert_record.call_args.kwargs["failed_reason"])
        self.assertEqual(upsert_record.call_args.kwargs["object_result"]["error"], failure_text)

    def test_dispatcher_action_history_exposes_snapshot_metadata(self) -> None:
        history = agents_factory.get_history()
        history._thread_iD = 321
        history._history_ = [{"role": "user", "content": "ingest this posting", "thread-id": history._thread_iD}]

        class _ActionFollowupChatComE:
            def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
                self._messages = _messages

            def _response(self):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="action acknowledged", tool_calls=None))]
                )

        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "execute_action_request",
                    json.dumps(
                        {
                            "action": "ingest_object",
                            "payload": {
                                "correlation_id": "platform:42",
                                "job_posting": {"job_title": "Platform Engineer"},
                            },
                        },
                        ensure_ascii=False,
                    ),
                    call_id="call_dispatcher_action",
                )
            ],
        )

        with patch("alde.chat_completion.ChatComE", _ActionFollowupChatComE), patch(
            "alde.agents_factory.execute_tool",
            return_value=('{"ok": true, "stored": true}', None),
        ):
            agents_factory._handle_tool_calls(agent_msg, agent_label="_data_dispatcher")

        workflow_entries = [
            entry
            for entry in chat_mod.ChatHistory._history_
            if isinstance(entry, dict)
            and isinstance(entry.get("data"), dict)
            and isinstance((entry.get("data") or {}).get("workflow"), dict)
        ]
        tool_result_entry = next(
            entry
            for entry in workflow_entries
            if ((entry.get("data") or {}).get("workflow") or {}).get("phase") == "tool_result"
            and entry.get("assistant-name") == "_data_dispatcher"
        )

        snapshot = tool_result_entry["data"]["workflow"]["snapshot"]
        self.assertEqual(snapshot["current_state"], "workflow_complete")
        self.assertEqual(snapshot["actor"]["name"], "execute_action_request")
        self.assertEqual(snapshot["event"]["tool_name"], "execute_action_request")
        self.assertEqual(snapshot["event"]["action"], "ingest_object")
        self.assertEqual(snapshot["event"]["correlation_id"], "platform:42")

    def test_dispatcher_execute_action_request_returns_tool_result_without_followup_model_call(self) -> None:
        history = agents_factory.get_history()
        history._thread_iD = 654
        history._history_ = [{"role": "user", "content": "ingest this posting", "thread-id": history._thread_iD}]

        agent_msg = SimpleNamespace(
            content="",
            tool_calls=[
                _tool_call(
                    "execute_action_request",
                    json.dumps(
                        {
                            "action": "ingest_object",
                            "payload": {
                                "correlation_id": "platform:654",
                                "job_posting": {"job_title": "Controls Engineer"},
                            },
                        },
                        ensure_ascii=False,
                    ),
                    call_id="call_dispatcher_action_terminal",
                )
            ],
        )

        with patch("alde.chat_completion.ChatComE") as chat_cls, patch(
            "alde.agents_factory.execute_tool",
            return_value=('{"ok": true, "stored": true}', None),
        ):
            result = agents_factory._handle_tool_calls(agent_msg, agent_label="_data_dispatcher")

        self.assertEqual(result, '{"ok": true, "stored": true}')
        chat_cls.assert_not_called()
        workflow_entries = [
            entry
            for entry in chat_mod.ChatHistory._history_
            if isinstance(entry, dict)
            and isinstance(entry.get("data"), dict)
            and isinstance((entry.get("data") or {}).get("workflow"), dict)
            and entry.get("assistant-name") == "_data_dispatcher"
        ]
        self.assertTrue(workflow_entries)
        latest_workflow = workflow_entries[-1]["data"]["workflow"]
        self.assertEqual(latest_workflow["current_state"], "workflow_complete")

    def test_route_contract_prefers_pair_schema(self) -> None:
        contract = agents_config.get_handoff_route_contract(
            "_primary_assistant",
            "_parser_agent",
        )

        self.assertEqual(contract["protocol"], "agent_handoff_v1")
        self.assertEqual(contract["handoff_schema"], "primary_to_parser_brief")
        self.assertEqual(contract["workflow_name"], "parser_agent_leaf")

    def test_agent_system_route_contracts_use_planner_and_builder_schemas(self) -> None:
        planner_contract = agents_config.get_handoff_route_contract(
            "_primary_assistant",
            "_agent_system_planner",
        )
        builder_contract = agents_config.get_handoff_route_contract(
            "_agent_system_planner",
            "_agent_system_worker",
        )

        self.assertEqual(planner_contract["handoff_schema"], "primary_to_agent_system_planner")
        self.assertEqual(planner_contract["workflow_name"], "agent_system_planner_router")
        self.assertEqual(builder_contract["handoff_schema"], "agent_system_planner_to_builder")
        self.assertEqual(builder_contract["workflow_name"], "agent_system_builder_leaf")

    def test_build_agent_system_configs_tool_returns_bundle(self) -> None:
        result = tools_mod.build_agent_system_configs_tool(
            system_name="qa_agency",
            action_request={"route_prefix": "/create agents"},
        )
        payload = json.loads(result)

        self.assertEqual(payload["system_name"], "qa_agency")
        self.assertIn("_qa_agency_planner", payload["agent_runtime_configs"])
        self.assertIn("_qa_agency_worker", payload["agent_runtime_configs"])
        self.assertIn("persisted_module", payload)
        self.assertIn("PERSISTED_CONFIG_UPDATES", payload["persisted_module"]["content"])

    def test_build_agent_system_configs_tool_writes_persisted_module_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            persist_path = Path(tmp_dir) / "qa_agency_persisted_config.py"
            result = tools_mod.build_agent_system_configs_tool(
                system_name="qa_agency",
                action_request={"route_prefix": "/create agents"},
                persist_path=str(persist_path),
                write_file=True,
            )

            payload = json.loads(result)
            self.assertTrue(persist_path.exists())
            self.assertTrue(payload["persisted_module"]["written"])
            self.assertEqual(payload["persisted_module"]["written_path"], str(persist_path))
            self.assertIn("SYSTEM_PROMPT_UPDATES", persist_path.read_text(encoding="utf-8"))

    def test_validate_agent_manifest_rejects_unknown_handoff_protocol(self) -> None:
        manifest = agents_config.get_agent_manifest("_primary_assistant")
        manifest["handoff_policy"] = {
            **dict(manifest.get("handoff_policy") or {}),
            "default_protocol": "missing_protocol",
        }

        report = agents_config.validate_agent_manifest("_primary_assistant", manifest)

        self.assertFalse(report["valid"])
        self.assertTrue(any("handoff_policy.default_protocol" in err for err in report["errors"]))

    def test_runtime_aliases_remain_supported_while_uppercase_legacy_aliases_are_pruned(self) -> None:
        self.assertEqual(normalize_agent_name("_profile_parser"), "profile_parser")
        self.assertEqual(normalize_agent_name("_job_posting_parser"), "job_posting_parser")
        self.assertIn("_profile_parser", _SYSTEM_PROMPT)
        self.assertIn("_job_posting_parser", _SYSTEM_PROMPT)
        self.assertNotIn("_PROFILE_PARSER", _SYSTEM_PROMPT)
        self.assertNotIn("_JOB_POSTING_PARSER", _SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()