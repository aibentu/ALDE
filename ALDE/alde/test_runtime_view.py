from __future__ import annotations

import json
import tempfile
import unittest

from alde.policy_store import append_event
from alde.runtime_view import export_runtime_view, load_runtime_view


class TestRuntimeView(unittest.TestCase):
    def test_runtime_view_exports_session_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            append_event(
                "query",
                {
                    "event_id": "query-1",
                    "session_id": "session-view",
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
                    "session_id": "session-view",
                    "agent": "_xplaner_xrouter",
                    "tool": "vectordb",
                    "timestamp": "2026-01-01T10:00:01Z",
                    "success": True,
                    "latency_ms": 18,
                    "reward": 0.5,
                    "result_count": 2,
                },
                base_dir=temp_dir,
            )

            history_entries = [
                {
                    "message-id": 1,
                    "role": "assistant",
                    "content": "running retrieval",
                    "thread-name": "chat",
                    "thread-id": "thread-view",
                    "assistant-name": "_xplaner_xrouter",
                    "tool_calls": [
                        {
                            "id": "call-view-1",
                            "type": "function",
                            "function": {"name": "vectordb", "arguments": "{}"},
                        }
                    ],
                    "data": {
                        "workflow": {
                            "phase": "tool_call_start",
                            "workflow_name": "dispatcher",
                            "agent_label": "_xplaner_xrouter",
                            "scope_key": "session-view",
                            "current_state": "retrieving",
                            "event": {"kind": "tool", "name": "vectordb", "payload": {}},
                        }
                    },
                },
                {
                    "message-id": 2,
                    "role": "tool",
                    "content": "[]",
                    "thread-name": "chat",
                    "thread-id": "thread-view",
                    "assistant-name": "_xplaner_xrouter",
                    "tool_call_id": "call-view-1",
                    "name": "vectordb",
                    "data": {
                        "workflow": {
                            "phase": "tool_result",
                            "workflow_name": "dispatcher",
                            "agent_label": "_xplaner_xrouter",
                            "scope_key": "session-view",
                            "current_state": "planner_retry_pending",
                            "retry": {
                                "attempt_count": 1,
                                "remaining_attempts": 1,
                                "next_delay_seconds": 5,
                                "exhausted": False,
                            },
                            "event": {
                                "kind": "state",
                                "name": "retry_requested",
                                "payload": {
                                    "target_agent": "_xworker",
                                    "protocol": "agent_handoff_v1",
                                    "correlation_id": "corr-1",
                                },
                            },
                        }
                    },
                },
            ]

            runtime_view = load_runtime_view(
                base_dir=temp_dir,
                session_id="session-view",
                history_entries=history_entries,
            )

            self.assertEqual(runtime_view["session_count"], 1)
            self.assertEqual(runtime_view["sessions"][0]["session_id"], "session-view")
            self.assertEqual(runtime_view["sessions"][0]["metrics"]["event_count"], runtime_view["sessions"][0]["event_count"])
            self.assertEqual(runtime_view["sessions"][0]["retry"]["requested_count"], 1)
            self.assertEqual(runtime_view["sessions"][0]["handoffs"]["count"], 1)
            self.assertEqual(runtime_view["sessions"][0]["latest_workflow_state"]["status"], "scheduled")

            exported_path = export_runtime_view(
                base_dir=temp_dir,
                session_id="session-view",
                history_entries=history_entries,
            )
            with open(exported_path, "r", encoding="utf-8") as exported_file:
                exported_view = json.load(exported_file)

            self.assertEqual(exported_view["session_count"], 1)
            self.assertEqual(exported_view["sessions"][0]["handoffs"]["count"], 1)


if __name__ == "__main__":
    unittest.main()