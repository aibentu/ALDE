from __future__ import annotations

import sys
import unittest
from pathlib import Path


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import alde.agents_factory as agents_factory
import alde.chat_completion as chat_mod
from alde.agents_config import get_agent_workflow_config, get_batch_workflow_config, validate_all_workflows, validate_batch_workflow_config, validate_workflow_config


class TestWorkflowVisibility(unittest.TestCase):
    def setUp(self) -> None:
        chat_mod.ChatHistory._history_ = []

    def test_validate_all_workflows_reports_current_config_as_valid(self) -> None:
        report = validate_all_workflows()

        self.assertTrue(report["valid"])
        self.assertGreater(report["workflow_count"], 0)
        self.assertGreater(report["batch_workflow_count"], 0)
        self.assertEqual(report["invalid_count"], 0)
        self.assertEqual(report["invalid_batch_workflow_count"], 0)
        self.assertEqual(report["mapping_errors"], [])

    def test_batch_cover_letter_workflow_is_declared_and_valid(self) -> None:
        workflow = get_batch_workflow_config("cover_letter_batch_generation")
        report = validate_batch_workflow_config("cover_letter_batch_generation", workflow)

        self.assertTrue(report["valid"])
        self.assertEqual(workflow["dispatcher"]["tool_name"], "dispatch_documents")
        self.assertEqual(workflow["document_output"]["text_writer_tool"], "write_document")
        self.assertEqual(workflow["document_output"]["pdf_writer"], "internal_text_pdf")
        stage_names = [stage["name"] for stage in workflow["stages"]]
        self.assertEqual(stage_names, ["job_posting_parse", "cover_letter_generate"])
        self.assertEqual(workflow["stages"][0]["prompt"], {"agent_type": "parser", "task_name": "job_posting"})
        self.assertEqual(workflow["stages"][1]["prompt"], {"agent_type": "writer", "task_name": "cover_letter"})

    def test_validate_workflow_config_detects_invalid_references(self) -> None:
        report = validate_workflow_config(
            "broken_workflow",
            {
                "entry_state": "missing_state",
                "states": {
                    "start": {"actor": {"kind": "agent", "name": "_missing_agent"}},
                    "end": {"terminal": True},
                },
                "transitions": [
                    {
                        "from": "start",
                        "to": "end",
                        "on": {"kind": "tool", "name": "missing_tool"},
                    }
                ],
                "retry_policy": {"max_attempts": -1, "backoff_seconds": [0, -2]},
            },
        )

        self.assertFalse(report["valid"])
        self.assertTrue(any("entry_state 'missing_state'" in error for error in report["errors"]))
        self.assertTrue(any("unknown agent '_missing_agent'" in error for error in report["errors"]))
        self.assertTrue(any("unknown tool event 'missing_tool'" in error for error in report["errors"]))
        self.assertTrue(any("max_attempts" in error for error in report["errors"]))

    def test_validate_workflow_config_warns_when_backoff_exceeds_retry_attempts(self) -> None:
        report = validate_workflow_config(
            "warning_workflow",
            {
                "entry_state": "start",
                "states": {
                    "start": {"actor": {"kind": "state", "name": "start"}},
                    "end": {"terminal": True},
                },
                "transitions": [
                    {
                        "from": "start",
                        "to": "end",
                        "on": {"kind": "state", "name": "complete"},
                    }
                ],
                "retry_policy": {"max_attempts": 1, "backoff_seconds": [1, 2]},
            },
        )

        self.assertTrue(report["valid"])
        self.assertTrue(any("more entries than max_attempts" in warning for warning in report["warnings"]))

    def test_validate_batch_workflow_config_requires_dispatcher_record_updates(self) -> None:
        workflow = get_batch_workflow_config("cover_letter_batch_generation")
        workflow["dispatcher_record"] = {}

        report = validate_batch_workflow_config("cover_letter_batch_generation", workflow)

        self.assertFalse(report["valid"])
        self.assertTrue(any("dispatcher_record.success_updates" in error for error in report["errors"]))
        self.assertTrue(any("dispatcher_record.failure_updates" in error for error in report["errors"]))

    def test_workflow_status_helpers_expose_latest_visible_snapshot(self) -> None:
        history = agents_factory.get_history()
        history._thread_iD = 99
        history._history_ = [
            {
                "message-id": 1,
                "role": "assistant",
                "assistant-name": "_xworker",
                "thread-id": 99,
                "thread-name": "test-thread",
                "time": "2025-03-01T10:00:00Z",
                "data": {
                    "workflow": {
                        "workflow_name": "xworker_leaf",
                        "agent_label": "_xworker",
                        "current_state": "xworker_active",
                        "phase": "tool_call_start",
                    }
                },
            },
            {
                "message-id": 2,
                "role": "assistant",
                "assistant-name": "_xworker",
                "thread-id": 99,
                "thread-name": "test-thread",
                "time": "2025-03-01T10:00:01Z",
                "data": {
                    "workflow": {
                        "workflow_name": "xworker_leaf",
                        "agent_label": "_xworker",
                        "current_state": "xworker_complete",
                        "phase": "tool_result",
                    }
                },
            },
        ]

        items = agents_factory.get_workflow_history_entries(agent_label="_xworker", thread_id=99, limit=10)
        latest = agents_factory.get_latest_workflow_status(agent_label="_xworker", thread_id=99)

        self.assertIsNotNone(latest)
        self.assertEqual(latest["message_id"], 2)
        self.assertEqual(latest["workflow"]["current_state"], "xworker_complete")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["message_id"], 2)
        self.assertEqual(items[1]["message_id"], 1)

    def test_xworker_workflow_visibility_uses_leaf_states(self) -> None:
        workflow = get_agent_workflow_config("_xworker")

        self.assertEqual(workflow.get("name"), "xworker_leaf")
        states = workflow.get("states") or {}
        transitions = workflow.get("transitions") or []

        self.assertEqual(states["xworker_active"]["actor"]["name"], "_xworker")
        self.assertEqual(states["xworker_complete"]["actor"]["name"], "workflow_complete")
        self.assertTrue(
            any(
                transition.get("from") == "xworker_active"
                and (transition.get("on") or {}).get("name") == ["followup_complete", "tool_complete"]
                and transition.get("to") == "xworker_complete"
                for transition in transitions
            )
        )

    def test_workflow_status_helpers_preserve_snapshot_metadata(self) -> None:
        history = agents_factory.get_history()
        history._thread_iD = 100
        history._history_ = [
            {
                "message-id": 11,
                "role": "tool",
                "assistant-name": "_xworker",
                "thread-id": 100,
                "thread-name": "snapshot-thread",
                "time": "2025-03-01T10:00:02Z",
                "data": {
                    "workflow": {
                        "workflow_name": "xworker_leaf",
                        "agent_label": "_xworker",
                        "current_state": "xworker_active",
                        "phase": "tool_result",
                        "snapshot": {
                            "phase": "tool_result",
                            "workflow_name": "xworker_leaf",
                            "agent_label": "_xworker",
                            "current_state": "xworker_active",
                            "terminal": False,
                            "actor": {"kind": "tool", "name": "execute_action_request"},
                            "event": {
                                "kind": "tool",
                                "name": "execute_action_request",
                                "tool_name": "execute_action_request",
                                "action": "ingest_object",
                                "target_agent": None,
                                "correlation_id": "platform:42",
                            },
                        },
                    }
                },
            }
        ]

        latest = agents_factory.get_latest_workflow_status(agent_label="_xworker", thread_id=100)

        self.assertIsNotNone(latest)
        snapshot = latest["workflow"]["snapshot"]
        self.assertEqual(snapshot["actor"]["name"], "execute_action_request")
        self.assertEqual(snapshot["event"]["action"], "ingest_object")
        self.assertEqual(snapshot["event"]["correlation_id"], "platform:42")

    def test_workflow_history_helpers_ignore_non_workflow_entries(self) -> None:
        history = agents_factory.get_history()
        history._thread_iD = 101
        history._history_ = [
            "not-a-dict",
            {
                "message-id": 1,
                "thread-id": 101,
                "data": {},
            },
            {
                "message-id": 2,
                "thread-id": 999,
                "data": {
                    "workflow": {
                        "workflow_name": "xworker_leaf",
                        "agent_label": "_xworker",
                        "current_state": "xworker_active",
                    }
                },
            },
            {
                "message-id": 3,
                "role": "assistant",
                "assistant-name": "_xworker",
                "thread-id": 101,
                "thread-name": "query-thread",
                "time": "2025-03-01T10:00:03Z",
                "data": {
                    "workflow": {
                        "workflow_name": "xworker_leaf",
                        "agent_label": "_xworker",
                        "current_state": "xworker_complete",
                    }
                },
            },
        ]

        items = agents_factory.get_workflow_history_entries(agent_label="_xworker", thread_id=101, limit=5)
        latest = agents_factory.get_latest_workflow_status(agent_label="_xworker", thread_id=101)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["message_id"], 3)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["workflow"]["current_state"], "xworker_complete")

    def test_workflow_history_data_projects_explicit_event_payload(self) -> None:
        session = agents_factory._create_workflow_session("_xworker")

        self.assertIsNotNone(session)

        workflow_data = agents_factory._workflow_history_data(
            session,
            phase="tool_result",
            event_kind="tool",
            event_name="execute_action_request",
            payload={"action": "ingest_object"},
        )

        self.assertIsNotNone(workflow_data)
        event = workflow_data["workflow"]["event"]
        self.assertEqual(event["kind"], "tool")
        self.assertEqual(event["name"], "execute_action_request")
        self.assertEqual(event["payload"], {"action": "ingest_object"})

    def test_workflow_history_data_promotes_tool_actor_on_tool_failed_state(self) -> None:
        session = agents_factory._create_workflow_session("_xworker")

        self.assertIsNotNone(session)

        workflow_data = agents_factory._workflow_history_data(
            session,
            phase="tool_result",
            event_kind="state",
            event_name="tool_failed",
            payload={"tool_name": "dispatch_documents", "correlation_id": "corr-1"},
        )

        self.assertIsNotNone(workflow_data)
        snapshot = workflow_data["workflow"]["snapshot"]
        self.assertEqual(snapshot["actor"]["kind"], "tool")
        self.assertEqual(snapshot["actor"]["name"], "dispatch_documents")
        self.assertEqual(snapshot["event"]["tool_name"], "dispatch_documents")
        self.assertEqual(snapshot["event"]["correlation_id"], "corr-1")


if __name__ == "__main__":
    unittest.main()