from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import alde.agents_factory as agents_factory
import alde.agents_config as agents_config
from alde.agents_config import get_agent_config, get_agent_manifest, get_agent_workflow_config, validate_agent_manifest


class TestWorkflowEngine(unittest.TestCase):
    def setUp(self) -> None:
        agents_factory._WORKFLOW_SESSION_CACHE.clear()

    def test_dispatcher_workflow_has_retry_and_failure_states(self) -> None:
        session = agents_factory._create_workflow_session("_data_dispatcher")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "dispatcher_ready")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="tool_failed",
            payload={"tool_name": "dispatch_documents", "result": "failed to dispatch"},
        )
        self.assertEqual(session["current_state"], "dispatcher_retry_pending")
        self.assertFalse(session["terminal"])
        self.assertEqual(session["retry"]["attempt_count"], 1)
        self.assertEqual(session["retry"]["next_delay_seconds"], 1)
        self.assertFalse(session["retry"]["exhausted"])

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="retry_requested",
            payload={},
        )
        self.assertEqual(session["current_state"], "dispatcher_ready")
        self.assertEqual(session["retry"]["attempt_count"], 1)
        self.assertEqual(session["retry"]["remaining_attempts"], 2)

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="tool_failed",
            payload={"tool_name": "dispatch_documents", "result": "failed again"},
        )
        self.assertEqual(session["retry"]["attempt_count"], 2)
        self.assertEqual(session["retry"]["next_delay_seconds"], 2)

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="retry_exhausted",
            payload={},
        )
        self.assertEqual(session["current_state"], "dispatcher_failed")
        self.assertTrue(session["terminal"])

    def test_dispatcher_workflow_completes_after_execute_action_request(self) -> None:
        session = agents_factory._create_workflow_session("_data_dispatcher")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "dispatcher_ready")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="tool",
            event_name="execute_action_request",
            payload={"action": "ingest_job_posting"},
        )
        self.assertEqual(session["current_state"], "action_executed")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="followup_complete",
            payload={"result": '{"ok": true, "stored": true}'},
        )
        self.assertEqual(session["current_state"], "workflow_complete")
        self.assertTrue(session["terminal"])

    def test_tool_transition_records_last_event_and_transition(self) -> None:
        session = agents_factory._create_workflow_session("_data_dispatcher")

        self.assertIsNotNone(session)

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="tool",
            event_name="execute_action_request",
            payload={"action": "ingest_job_posting"},
        )

        self.assertEqual(session["current_state"], "action_executed")
        self.assertEqual(session["last_event"]["name"], "execute_action_request")
        self.assertEqual(session["last_transition"]["to"], "action_executed")

    def test_dispatcher_workflow_completes_after_atomic_upsert(self) -> None:
        session = agents_factory._create_workflow_session("_data_dispatcher")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "dispatcher_ready")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="tool",
            event_name="upsert_dispatcher_job_record",
            payload={"correlation_id": "sha-atomic-1"},
        )
        self.assertEqual(session["current_state"], "job_record_upserted")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="tool_complete",
            payload={"result": '{"ok": true, "dispatcher_updated": true}'},
        )
        self.assertEqual(session["current_state"], "workflow_complete")
        self.assertTrue(session["terminal"])

    def test_dispatcher_workflow_retries_after_action_tool_failure(self) -> None:
        session = agents_factory._create_workflow_session("_data_dispatcher")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "dispatcher_ready")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="tool_failed",
            payload={"tool_name": "execute_action_request", "result": "schema invalid"},
        )
        self.assertEqual(session["current_state"], "dispatcher_retry_pending")
        self.assertEqual(session["retry"]["attempt_count"], 1)

    def test_retry_requested_preserves_last_failure_payload(self) -> None:
        session = agents_factory._create_workflow_session("_data_dispatcher")
        workflow_config = get_agent_workflow_config("_data_dispatcher")

        self.assertIsNotNone(session)
        self.assertIsNotNone(workflow_config)

        failure_retry = agents_factory._update_workflow_retry_status(
            session,
            workflow_config,
            event_name="tool_failed",
            payload={"tool_name": "dispatch_documents", "result": "failed to dispatch"},
            next_state="dispatcher_retry_pending",
        )
        session["retry"] = failure_retry

        retry_requested = agents_factory._update_workflow_retry_status(
            session,
            workflow_config,
            event_name="retry_requested",
            payload={},
            next_state="dispatcher_ready",
        )

        self.assertEqual(retry_requested["attempt_count"], 1)
        self.assertEqual(retry_requested["last_failure"], {"tool_name": "dispatch_documents", "result": "failed to dispatch"})
        self.assertEqual(retry_requested["history"][-1]["event"], "retry_requested")

    def test_history_policy_normalizes_invalid_runtime_values(self) -> None:
        with patch(
            "alde.agents_factory._get_runtime_agent_config",
            return_value={
                "agent_label": "_writer_agent",
                "history_policy": {
                    "followup_history_depth": "not-a-number",
                    "include_routed_history": 1,
                    "routed_history_depth": -4,
                },
            },
        ):
            policy = agents_factory._agent_history_policy("_writer_agent")

        self.assertEqual(policy["followup_history_depth"], 15)
        self.assertTrue(policy["include_routed_history"])
        self.assertEqual(policy["routed_history_depth"], 0)

    def test_session_scoped_workflow_reuses_non_terminal_state(self) -> None:
        session = agents_factory._create_workflow_session("_primary_assistant")

        self.assertIsNotNone(session)
        session = agents_factory._advance_workflow_session(
            session,
            event_kind="tool",
            event_name="route_to_agent",
            payload={"target_agent": "_writer_agent"},
        )

        reused_session = agents_factory._create_workflow_session("_primary_assistant")

        self.assertIsNotNone(reused_session)
        self.assertEqual(reused_session["current_state"], "writer_delegated")
        self.assertEqual(reused_session["runtime"]["instance_policy"], "session_scoped")
        self.assertTrue(str(reused_session.get("scope_key") or "").startswith("session:"))

    def test_ephemeral_workflow_starts_fresh_each_time(self) -> None:
        session = agents_factory._create_workflow_session("_parser_agent")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "parser_active")
        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="followup_complete",
            payload={"result": "parsed generic content"},
        )
        self.assertEqual(session["current_state"], "parser_complete")

        fresh_session = agents_factory._create_workflow_session("_parser_agent")

        self.assertIsNotNone(fresh_session)
        self.assertEqual(fresh_session["current_state"], "parser_active")
        self.assertEqual(fresh_session["runtime"]["instance_policy"], "ephemeral")
        self.assertIsNone(fresh_session.get("scope_key"))
        self.assertFalse(session["retry"]["exhausted"])

    def test_generic_writer_leaf_workflow_completes_without_routing(self) -> None:
        session = agents_factory._create_workflow_session("_writer_agent")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "writer_active")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="followup_complete",
            payload={"result": "generated generic text"},
        )

        self.assertEqual(session["current_state"], "writer_complete")
        self.assertTrue(session["terminal"])

    def test_service_scoped_workflow_reuses_non_terminal_state_across_threads(self) -> None:
        runtime_metadata = agents_factory._agent_runtime_metadata("_data_dispatcher")
        runtime_metadata["instance_policy"] = "service_scoped"

        with patch.object(agents_factory.WORKFLOW_CONTEXT_SERVICE, "load_runtime_metadata", return_value=runtime_metadata):
            session = agents_factory._create_workflow_session("_data_dispatcher", thread_id=101)

            self.assertIsNotNone(session)
            self.assertEqual(session["runtime"]["instance_policy"], "service_scoped")
            self.assertTrue(str(session.get("scope_key") or "").startswith("service:data_dispatcher_chain:"))

            session = agents_factory._advance_workflow_session(
                session,
                event_kind="state",
                event_name="tool_failed",
                payload={"tool_name": "dispatch_documents", "result": "failed to dispatch"},
            )
            self.assertEqual(session["current_state"], "dispatcher_retry_pending")

            reused_session = agents_factory._create_workflow_session("_data_dispatcher", thread_id=202)

        self.assertIsNotNone(reused_session)
        self.assertEqual(reused_session["current_state"], "dispatcher_retry_pending")
        self.assertEqual(reused_session["scope_key"], session["scope_key"])
        self.assertEqual(reused_session["runtime"]["instance_policy"], "service_scoped")

    def test_current_thread_id_reads_from_workflow_context_history(self) -> None:
        fake_history = SimpleNamespace(_thread_iD=321)

        with patch.object(agents_factory.WORKFLOW_CONTEXT_SERVICE, "load_history", return_value=fake_history):
            thread_id = agents_factory._current_thread_id()

        self.assertEqual(thread_id, 321)

    def test_unknown_agent_config_uses_default_projection(self) -> None:
        config = get_agent_config("_missing_agent")

        self.assertEqual(config["agent_label"], "_missing_agent")
        self.assertEqual(config["canonical_name"], "_missing_agent")
        self.assertEqual(config["instance_policy"], "ephemeral")
        self.assertFalse(config["routing_policy"]["can_route"])
        self.assertEqual(config["history_policy"]["followup_history_depth"], 6)

    def test_set_config_values_supports_nested_paths(self) -> None:
        config = agents_config.set_config_values(
            {"routing_policy": {}, "history_policy": {}},
            {
                "routing_policy.can_route": True,
                "history_policy.followup_history_depth": 12,
            },
        )

        self.assertTrue(config["routing_policy"]["can_route"])
        self.assertEqual(config["history_policy"]["followup_history_depth"], 12)

    def test_create_prompt_config_builds_missing_prompt_projection(self) -> None:
        config = agents_config.create_prompt_config(
            "custom_agent",
            {
                "prompt": "Custom prompt",
                "task.mode": "custom",
                "output_schema.agent": "custom_agent",
            },
        )

        self.assertEqual(config["prompt"], "Custom prompt")
        self.assertEqual(config["task"]["mode"], "custom")
        self.assertEqual(config["output_schema"]["agent"], "custom_agent")

    def test_create_agent_runtime_config_uses_existing_projection_as_base(self) -> None:
        config = agents_config.create_agent_runtime_config(
            "_writer_agent",
            {
                "model": "gpt-5-mini",
                "workflow.definition": "custom_writer_flow",
            },
        )

        self.assertEqual(config["canonical_name"], "writer_agent")
        self.assertEqual(config["model"], "gpt-5-mini")
        self.assertEqual(config["workflow"]["definition"], "custom_writer_flow")

    def test_create_tool_config_normalizes_alias_and_applies_updates(self) -> None:
        config = agents_config.create_tool_config(
            "dispatch_docs",
            {
                "description": "Dispatcher alias config",
            },
        )

        self.assertEqual(config["name"], "dispatch_documents")
        self.assertEqual(config["description"], "Dispatcher alias config")

    def test_create_workflow_config_builds_named_missing_workflow(self) -> None:
        config = agents_config.create_workflow_config(
            "custom_flow",
            {
                "entry_state": "start",
                "states.start.actor.kind": "agent",
                "states.start.actor.name": "_writer_agent",
                "states.done.terminal": True,
            },
        )

        self.assertEqual(config["name"], "custom_flow")
        self.assertEqual(config["entry_state"], "start")
        self.assertEqual(config["states"]["start"]["actor"]["name"], "_writer_agent")
        self.assertTrue(config["states"]["done"]["terminal"])

    def test_create_handoff_schema_config_builds_default_schema(self) -> None:
        config = agents_config.create_handoff_schema_config(
            "custom_schema",
            {
                "workflow_name": "custom_flow",
                "instructions": ["Use structured payload"],
            },
        )

        self.assertEqual(config["name"], "custom_schema")
        self.assertEqual(config["protocol"], "message_text")
        self.assertEqual(config["workflow_name"], "custom_flow")
        self.assertEqual(config["instructions"], ["Use structured payload"])

    def test_create_agent_system_basic_config_builds_planner_builder_bundle(self) -> None:
        config_bundle = agents_config.create_agent_system_basic_config(
            "qa_agency",
            {
                "route_prefix": "/create agents",
            },
        )

        self.assertEqual(config_bundle["system_name"], "qa_agency")
        self.assertIn("_qa_agency_planner", config_bundle["agent_runtime_configs"])
        self.assertIn("_qa_agency_worker", config_bundle["agent_runtime_configs"])
        self.assertIn("qa_agency_planner_router", config_bundle["workflow_configs"])
        self.assertIn("qa_agency_builder_leaf", config_bundle["workflow_configs"])
        self.assertEqual(
            config_bundle["forced_route_configs"]["_primary_assistant"][0]["trigger"]["type"],
            "text_prefix",
        )
        self.assertTrue(config_bundle["validation"]["valid"])
        self.assertIn("persisted_module", config_bundle)
        self.assertIn("SYSTEM_PROMPT_UPDATES", config_bundle["persisted_module"]["content"])
        assistant_workflow = config_bundle["assistant_integration"]["workflow_config"]
        self.assertIn("planner_delegated", assistant_workflow["states"])
        self.assertTrue(
            any(
                transition.get("to") == "planner_delegated"
                for transition in (assistant_workflow.get("transitions") or [])
            )
        )

    def test_create_agent_system_basic_config_rejects_missing_required_planning_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid agent system action request"):
            agents_config.create_agent_system_basic_config(
                "qa_agency",
                {
                    "agent_specs": [{"name": "planner"}],
                    "workflow_specs": [{"name": "qa_flow"}],
                    "integration_targets": {"assistant_agent_name": "_primary_assistant"},
                },
            )

    def test_tool_projection_resolves_alias_to_canonical_config(self) -> None:
        config = agents_config.TOOL_CONFIG_SERVICE.load_object_projection("dispatch_docs").to_config_dict()

        self.assertEqual(config["name"], "dispatch_documents")

    def test_agent_workflow_projection_returns_named_workflow_config(self) -> None:
        config = agents_config.WORKFLOW_CONFIG_SERVICE.load_agent_object_projection("_data_dispatcher").to_config_dict()

        self.assertEqual(config["name"], "data_dispatcher_chain")
        self.assertEqual(config["entry_state"], "dispatcher_ready")

    def test_manifest_validation_rejects_unknown_instance_policy(self) -> None:
        report = validate_agent_manifest(
            "_data_dispatcher",
            {
                "agent_label": "_data_dispatcher",
                "canonical_name": "data_dispatcher",
                "role": "workflow_service",
                "skill_profile": "workflow_dispatch",
                "prompt_config_name": "data_dispatcher",
                "prompt_fragments": ["source_grounding", "deterministic_workflow"],
                "model": "gpt-4o-mini",
                "system": "dispatcher system",
                "tools": ["dispatch_documents"],
                "tool_groups": [],
                "direct_tools": ["dispatch_documents"],
                "defaults": {},
                "workflow": {"definition": "data_dispatcher_chain"},
                "workflow_name": "data_dispatcher_chain",
                "instance_policy": "permanent_forever",
                "routing_policy": {"mode": "workflow_service", "can_route": False},
                "history_policy": {
                    "followup_history_depth": 8,
                    "include_routed_history": False,
                    "routed_history_depth": 0,
                },
            },
        )

        self.assertFalse(report["valid"])
        self.assertTrue(any("instance_policy 'permanent_forever'" in error for error in report["errors"]))

    def test_current_dispatcher_manifest_remains_valid_with_workflow_service_tools(self) -> None:
        manifest = get_agent_manifest("_data_dispatcher")

        report = validate_agent_manifest("_data_dispatcher", manifest)

        self.assertTrue(report["valid"])
        self.assertEqual(manifest.get("workflow_name"), "data_dispatcher_chain")
        self.assertIn("@dispatcher", manifest.get("tools") or [])
        self.assertIn("route_to_agent", manifest.get("direct_tools") or [])

    def test_agent_system_manifests_are_valid(self) -> None:
        planner_report = validate_agent_manifest("_agent_system_planner")
        worker_report = validate_agent_manifest("_agent_system_worker")

        self.assertTrue(planner_report["valid"])
        self.assertTrue(worker_report["valid"])

    def test_specialist_leaf_workflows_are_registered(self) -> None:
        self.assertEqual(get_agent_workflow_config("_profile_parser").get("name"), "profile_parser_leaf")
        self.assertEqual(get_agent_workflow_config("_job_posting_parser").get("name"), "job_posting_parser_leaf")
        self.assertEqual(get_agent_workflow_config("_cover_letter_agent").get("name"), "cover_letter_writer_leaf")

    def test_leaf_workflow_accepts_followup_complete(self) -> None:
        session = agents_factory._create_workflow_session("_job_posting_parser")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "job_posting_parser_active")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="followup_complete",
            payload={"result": "parsed posting"},
        )

        self.assertEqual(session["current_state"], "job_posting_parser_complete")
        self.assertTrue(session["terminal"])

    def test_compound_guard_supports_any_and_contains(self) -> None:
        session = agents_factory._create_workflow_session("_cover_letter_agent")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "cover_letter_writer_active")

        self.assertFalse(
            agents_factory._workflow_conditions_match(
                {"result": ""},
                {"all": [{"result": {"exists": True}}, {"result": {"contains": "Motivation"}}]},
            )
        )
        self.assertTrue(
            agents_factory._workflow_conditions_match(
                {"result": "Motivation und Erfahrung"},
                {"all": [{"result": {"exists": True}}, {"result": {"contains": "Motivation"}}]},
            )
        )

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="routed_agent_complete",
            payload={"result": "Motivation und Erfahrung"},
        )

        self.assertEqual(session["current_state"], "cover_letter_writer_complete")
        self.assertTrue(session["terminal"])

    def test_compound_guard_supports_nested_all_any(self) -> None:
        conditions = {
            "all": [
                {"target_agent": {"in": ["_profile_parser", "_job_posting_parser"]}},
                {
                    "any": [
                        {"result": {"contains": "parsed"}},
                        {"metadata.status": {"eq": "ok"}},
                    ]
                },
            ]
        }

        self.assertTrue(
            agents_factory._workflow_conditions_match(
                {"target_agent": "_profile_parser", "metadata": {"status": "ok"}},
                conditions,
            )
        )
        self.assertFalse(
            agents_factory._workflow_conditions_match(
                {"target_agent": "_cover_letter_agent", "metadata": {"status": "ok"}},
                conditions,
            )
        )


if __name__ == "__main__":
    unittest.main()