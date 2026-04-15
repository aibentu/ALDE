from __future__ import annotations

import unittest

from ALDE_Projekt.ALDE.alde.agents_runtime_events import (
    create_agent_handoff_event,
    create_query_event,
    load_projected_runtime_events,
    validate_runtime_event,
)


class TestRuntimeEvents(unittest.TestCase):
    def test_create_query_event_returns_valid_event(self) -> None:
        event_object = create_query_event(
            query_text="python retrieval",
            tool_name="vectordb",
            session_id="session-1",
            agent_label="_xplaner_xrouter",
        )

        ok, reason = validate_runtime_event(event_object)

        self.assertTrue(ok, reason)
        self.assertEqual(event_object["event_type"], "query")
        self.assertEqual(event_object["payload"]["tool_name"], "vectordb")

    def test_handoff_event_requires_target_agent(self) -> None:
        with self.assertRaises(ValueError):
            create_agent_handoff_event(
                source_agent="_xplaner_xrouter",
                target_agent="",
                protocol="agent_handoff_v1",
            )

    def test_projection_uses_existing_history_schema(self) -> None:
        history_entries = [
            {
                "message-id": 1,
                "role": "assistant",
                "content": "retrieving context",
                "thread-name": "chat",
                "thread-id": "thread-1",
                "assistant-name": "_xplaner_xrouter",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "vectordb",
                            "arguments": '{"query": "agent routing"}',
                        },
                    }
                ],
                "data": {
                    "workflow": {
                        "phase": "tool_call_start",
                        "workflow_name": "dispatcher",
                        "agent_label": "_xplaner_xrouter",
                        "scope_key": "session-1",
                        "current_state": "retrieving",
                        "event": {
                            "kind": "tool",
                            "name": "vectordb",
                            "payload": {},
                        },
                    }
                },
            },
            {
                "message-id": 2,
                "role": "tool",
                "content": "[]",
                "thread-name": "chat",
                "thread-id": "thread-1",
                "assistant-name": "_xplaner_xrouter",
                "tool_call_id": "call-1",
                "name": "vectordb",
                "data": {
                    "workflow": {
                        "phase": "tool_result",
                        "workflow_name": "dispatcher",
                        "agent_label": "_xplaner_xrouter",
                        "scope_key": "session-1",
                        "current_state": "retrieving",
                        "event": {
                            "kind": "state",
                            "name": "handoff_ready",
                            "payload": {
                                "target_agent": "_xworker",
                                "protocol": "agent_handoff_v1",
                            },
                        },
                    }
                },
            },
        ]

        projected_events = load_projected_runtime_events(history_entries=history_entries)
        event_types = {event_object["event_type"] for event_object in projected_events}
        workflow_state_event = next(
            event_object
            for event_object in projected_events
            if event_object["event_type"] == "workflow_state"
            and event_object["payload"]["metadata"].get("event_family") == "handoff"
        )
        handoff_event = next(event_object for event_object in projected_events if event_object["event_type"] == "agent_handoff")

        self.assertIn("workflow_state", event_types)
        self.assertIn("tool_call", event_types)
        self.assertIn("agent_handoff", event_types)
        self.assertEqual(workflow_state_event["payload"]["metadata"]["event_family"], "handoff")
        self.assertEqual(handoff_event["payload"]["metadata"]["event_status"], "requested")


if __name__ == "__main__":
    unittest.main()