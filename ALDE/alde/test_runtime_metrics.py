from __future__ import annotations

import tempfile
import unittest

from ALDE_Projekt.ALDE.alde.agents_policy_store import append_event
from ALDE_Projekt.ALDE.alde.agents_event_store import append_runtime_event
from ALDE_Projekt.ALDE.alde.agents_runtime_events import create_outcome_event, create_query_event, create_tool_call_event
from ALDE_Projekt.ALDE.alde.agents_runtime_metrics import load_runtime_metrics


class TestRuntimeMetrics(unittest.TestCase):
    def test_metrics_snapshot_aggregates_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            query_event = create_query_event(
                query_text="agent routing",
                tool_name="vectordb",
                session_id="session-metrics",
            )
            append_runtime_event(query_event, base_dir=temp_dir)

            tool_call_event = create_tool_call_event(
                tool_name="vectordb",
                phase="completed",
                session_id="session-metrics",
                metadata={"latency_ms": 25},
            )
            tool_call_event["payload"]["latency_ms"] = 25
            append_runtime_event(tool_call_event, base_dir=temp_dir)

            outcome_event = create_outcome_event(
                query_event_id=query_event["event_id"],
                tool_name="vectordb",
                success=True,
                session_id="session-metrics",
                metadata={"reward": 1.0},
            )
            outcome_event["payload"]["latency_ms"] = 30
            outcome_event["payload"]["reward"] = 1.0
            append_runtime_event(outcome_event, base_dir=temp_dir)

            snapshot = load_runtime_metrics(base_dir=temp_dir, session_id="session-metrics")

            self.assertEqual(snapshot["event_count"], 3)
            self.assertEqual(snapshot["session_count"], 1)
            self.assertEqual(snapshot["success_count"], 1)
            self.assertEqual(snapshot["failure_count"], 0)
            self.assertGreater(snapshot["average_latency_ms"], 0)
            self.assertEqual(snapshot["average_reward"], 1.0)
            self.assertEqual(snapshot["event_family_counts"]["tool"], 1)
            self.assertEqual(snapshot["event_status_counts"]["completed"], 2)

    def test_metrics_snapshot_uses_learning_events_and_history_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            append_event(
                "query",
                {
                    "event_id": "query-1",
                    "session_id": "session-history",
                    "agent": "_xplaner_xrouter",
                    "tool": "vectordb",
                    "query_text": "agent routing",
                    "timestamp": "2026-01-01T10:00:00Z",
                    "k": 5,
                },
                base_dir=temp_dir,
            )
            append_event(
                "outcome",
                {
                    "event_id": "outcome-1",
                    "query_event_id": "query-1",
                    "session_id": "session-history",
                    "agent": "_xplaner_xrouter",
                    "tool": "vectordb",
                    "timestamp": "2026-01-01T10:00:01Z",
                    "success": True,
                    "latency_ms": 18,
                    "reward": 0.8,
                    "result_count": 2,
                },
                base_dir=temp_dir,
            )

            history_entries = [
                {
                    "message-id": 11,
                    "role": "assistant",
                    "content": "running retrieval",
                    "thread-name": "chat",
                    "thread-id": "thread-history",
                    "assistant-name": "_xplaner_xrouter",
                    "tool_calls": [
                        {
                            "id": "call-history-1",
                            "type": "function",
                            "function": {"name": "vectordb", "arguments": "{}"},
                        }
                    ],
                    "data": {
                        "workflow": {
                            "phase": "tool_call_start",
                            "workflow_name": "dispatcher",
                            "agent_label": "_xplaner_xrouter",
                            "scope_key": "session-history",
                            "current_state": "retrieving",
                            "event": {
                                "kind": "tool",
                                "name": "vectordb",
                                "payload": {"target_agent": "_xworker"},
                            },
                        }
                    },
                }
            ]

            snapshot = load_runtime_metrics(
                base_dir=temp_dir,
                session_id="session-history",
                history_entries=history_entries,
            )

            self.assertEqual(snapshot["success_count"], 1)
            self.assertEqual(snapshot["failure_count"], 0)
            self.assertIn("query", snapshot["event_type_counts"])
            self.assertIn("outcome", snapshot["event_type_counts"])
            self.assertIn("tool_call", snapshot["event_type_counts"])
            self.assertIn("workflow_state", snapshot["event_type_counts"])
            self.assertIn("agent_handoff", snapshot["event_type_counts"])
            self.assertIn("handoff", snapshot["event_family_counts"])
            self.assertIn("requested", snapshot["event_status_counts"])

    def test_outcome_projection_inherits_query_session_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            append_event(
                "query",
                {
                    "event_id": "query-session-link",
                    "session_id": "session-linked",
                    "agent": "_xplaner_xrouter",
                    "tool": "memorydb",
                    "query_text": "context lookup",
                    "timestamp": "2026-01-01T12:00:00Z",
                    "k": 3,
                },
                base_dir=temp_dir,
            )
            append_event(
                "outcome",
                {
                    "event_id": "outcome-session-link",
                    "query_event_id": "query-session-link",
                    "tool": "memorydb",
                    "timestamp": "2026-01-01T12:00:01Z",
                    "success": True,
                    "latency_ms": 12,
                    "reward": 0.5,
                    "result_count": 1,
                },
                base_dir=temp_dir,
            )

            snapshot = load_runtime_metrics(base_dir=temp_dir, session_id="session-linked")

            self.assertEqual(snapshot["event_count"], 2)
            self.assertEqual(snapshot["success_count"], 1)


if __name__ == "__main__":
    unittest.main()