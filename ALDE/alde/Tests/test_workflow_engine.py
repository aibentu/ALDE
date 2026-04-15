from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import alde.agents_factory as agents_factory
import ALDE_Projekt.ALDE.alde.agents_configurator as agents_configurator
from ALDE_Projekt.ALDE.alde.agents_configurator import get_agent_config, get_agent_manifest, get_agent_workflow_config, validate_agent_manifest


class TestWorkflowEngine(unittest.TestCase):
    def setUp(self) -> None:
        agents_factory._WORKFLOW_SESSION_CACHE.clear()

    def test_xplaner_workflow_routes_and_completes(self) -> None:
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

    def test_xworker_leaf_workflow_completes_after_followup(self) -> None:
        session = agents_factory._create_workflow_session("_xworker")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "xworker_active")

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="followup_complete",
            payload={"result": "generated deterministic output"},
        )

        self.assertEqual(session["current_state"], "xworker_complete")
        self.assertTrue(session["terminal"])

    def test_xworker_failure_records_last_failure(self) -> None:
        session = agents_factory._create_workflow_session("_xworker")

        self.assertIsNotNone(session)

        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="tool_failed",
            payload={"tool_name": "execute_action_request", "result": "schema invalid"},
        )

        self.assertEqual(session["current_state"], "xworker_failed")
        self.assertTrue(session["terminal"])
        self.assertEqual(session["retry"]["attempt_count"], 1)
        self.assertEqual(
            session["retry"]["last_failure"],
            {"tool_name": "execute_action_request", "result": "schema invalid"},
        )

    def test_history_policy_normalizes_invalid_runtime_values(self) -> None:
        with patch(
            "alde.agents_factory._get_runtime_agent_config",
            return_value={
                "agent_label": "_xworker",
                "history_policy": {
                    "followup_history_depth": "not-a-number",
                    "include_routed_history": 1,
                    "routed_history_depth": -4,
                },
            },
        ):
            policy = agents_factory._agent_history_policy("_xworker")

        self.assertEqual(policy["followup_history_depth"], 15)
        self.assertTrue(policy["include_routed_history"])
        self.assertEqual(policy["routed_history_depth"], 0)

    def test_session_scoped_workflow_reuses_non_terminal_state(self) -> None:
        session = agents_factory._create_workflow_session("_xplaner_xrouter")

        self.assertIsNotNone(session)
        session = agents_factory._advance_workflow_session(
            session,
            event_kind="tool",
            event_name="route_to_agent",
            payload={"target_agent": "_xworker"},
        )

        reused_session = agents_factory._create_workflow_session("_xplaner_xrouter")

        self.assertIsNotNone(reused_session)
        self.assertEqual(reused_session["current_state"], "xworker_delegated")
        self.assertEqual(reused_session["runtime"]["instance_policy"], "session_scoped")
        self.assertTrue(str(reused_session.get("scope_key") or "").startswith("session:"))

    def test_ephemeral_workflow_starts_fresh_each_time(self) -> None:
        session = agents_factory._create_workflow_session("_xworker")

        self.assertIsNotNone(session)
        self.assertEqual(session["current_state"], "xworker_active")
        session = agents_factory._advance_workflow_session(
            session,
            event_kind="state",
            event_name="followup_complete",
            payload={"result": "parsed content"},
        )
        self.assertEqual(session["current_state"], "xworker_complete")

        fresh_session = agents_factory._create_workflow_session("_xworker")

        self.assertIsNotNone(fresh_session)
        self.assertEqual(fresh_session["current_state"], "xworker_active")
        self.assertEqual(fresh_session["runtime"]["instance_policy"], "ephemeral")
        self.assertIsNone(fresh_session.get("scope_key"))

    def test_unknown_agent_config_uses_default_projection(self) -> None:
        config = get_agent_config("_missing_agent")

        self.assertEqual(config["agent_label"], "_missing_agent")
        self.assertEqual(config["canonical_name"], "_missing_agent")
        self.assertEqual(config["instance_policy"], "ephemeral")
        self.assertFalse(config["routing_policy"]["can_route"])
        self.assertEqual(config["history_policy"]["followup_history_depth"], 6)

    def test_set_config_values_supports_nested_paths(self) -> None:
        config = agents_configurator.set_config_values(
            {"routing_policy": {}, "history_policy": {}},
            {
                "routing_policy.can_route": True,
                "history_policy.followup_history_depth": 12,
            },
        )

        self.assertTrue(config["routing_policy"]["can_route"])
        self.assertEqual(config["history_policy"]["followup_history_depth"], 12)

    def test_create_prompt_config_builds_missing_prompt_projection(self) -> None:
        config = agents_configurator.create_prompt_config(
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
        config = agents_configurator.create_agent_runtime_config(
            "_xworker",
            {
                "model": "gpt-5-mini",
                "workflow.definition": "custom_xworker_flow",
            },
        )

        self.assertEqual(config["canonical_name"], "xworker")
        self.assertEqual(config["model"], "gpt-5-mini")
        self.assertEqual(config["workflow"]["definition"], "custom_xworker_flow")

    def test_create_tool_config_normalizes_alias_and_applies_updates(self) -> None:
        config = agents_configurator.create_tool_config(
            "dispatch_docs",
            {
                "description": "Dispatcher alias config",
            },
        )

        self.assertEqual(config["name"], "dispatch_documents")
        self.assertEqual(config["description"], "Dispatcher alias config")

    def test_create_workflow_config_builds_named_missing_workflow(self) -> None:
        config = agents_configurator.create_workflow_config(
            "custom_flow",
            {
                "entry_state": "start",
                "states.start.actor.kind": "agent",
                "states.start.actor.name": "_xworker",
                "states.done.terminal": True,
            },
        )

        self.assertEqual(config["name"], "custom_flow")
        self.assertEqual(config["entry_state"], "start")
        self.assertEqual(config["states"]["start"]["actor"]["name"], "_xworker")
        self.assertTrue(config["states"]["done"]["terminal"])

    def test_create_handoff_schema_config_builds_default_schema(self) -> None:
        config = agents_configurator.create_handoff_schema_config(
            "custom_schema",
            {
                "workflow_name": "custom_flow",
                "instructions": ["Use structured payload"],
            },
        )

        self.assertEqual(config["name"], "custom_schema")
        self.assertEqual(config["handoff_id"], "custom_schema")
        self.assertEqual(config["protocol"], "message_text")
        self.assertEqual(config["workflow_name"], "custom_flow")
        self.assertEqual(config["instructions"], ["Use structured payload"])

    def test_create_agent_system_basic_config_builds_planner_builder_bundle(self) -> None:
        config_bundle = agents_configurator.create_agent_system_basic_config(
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
            config_bundle["forced_route_configs"]["_xplaner_xrouter"][0]["trigger"]["type"],
            "text_prefix",
        )
        self.assertTrue(config_bundle["validation"]["valid"])
        assistant_workflow = config_bundle["assistant_integration"]["workflow_config"]
        self.assertIn("planner_delegated", assistant_workflow["states"])
        self.assertIn("xworker_delegated", assistant_workflow["states"])

    def test_create_agent_system_basic_config_rejects_missing_required_planning_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid agent system action request"):
            agents_configurator.create_agent_system_basic_config(
                "qa_agency",
                {
                    "agent_specs": [{"name": "planner"}],
                    "workflow_specs": [{"name": "qa_flow"}],
                    "integration_targets": {"assistant_agent_name": "_xplaner_xrouter"},
                },
            )

    def test_tool_projection_resolves_alias_to_canonical_config(self) -> None:
        config = agents_configurator.TOOL_CONFIG_SERVICE.load_object_projection("dispatch_docs").to_config_dict()

        self.assertEqual(config["name"], "dispatch_documents")

    def test_agent_workflow_projection_returns_named_workflow_config(self) -> None:
        config = agents_configurator.WORKFLOW_CONFIG_SERVICE.load_agent_object_projection("_xplaner_xrouter").to_config_dict()

        self.assertEqual(config["name"], "xplaner_xrouter_router")
        self.assertEqual(config["entry_state"], "xplaner_ready")

    def test_manifest_validation_rejects_unknown_instance_policy(self) -> None:
        report = validate_agent_manifest(
            "_xworker",
            {
                "agent_label": "_xworker",
                "canonical_name": "xworker",
                "role": "xworker",
                "skill_profile": "xworker_core",
                "prompt_config_name": "xworker",
                "prompt_fragments": ["source_grounding", "deterministic_execution"],
                "model": "gpt-4o-mini",
                "system": "xworker system",
                "tools": ["read_document"],
                "tool_groups": [],
                "direct_tools": ["read_document"],
                "defaults": {},
                "workflow": {"definition": "xworker_leaf"},
                "workflow_name": "xworker_leaf",
                "instance_policy": "permanent_forever",
                "routing_policy": {"mode": "xworker", "can_route": False},
                "history_policy": {
                    "followup_history_depth": 8,
                    "include_routed_history": False,
                    "routed_history_depth": 0,
                },
            },
        )

        self.assertFalse(report["valid"])
        self.assertTrue(any("instance_policy 'permanent_forever'" in error for error in report["errors"]))

    def test_current_xplaner_manifest_remains_valid(self) -> None:
        manifest = get_agent_manifest("_xplaner_xrouter")

        report = validate_agent_manifest("_xplaner_xrouter", manifest)

        self.assertTrue(report["valid"])
        self.assertEqual(manifest.get("workflow_name"), "xplaner_xrouter_router")
        self.assertIn("route_to_agent", manifest.get("direct_tools") or [])

    def test_xworker_leaf_workflow_is_registered(self) -> None:
        self.assertEqual(get_agent_workflow_config("_xworker").get("name"), "xworker_leaf")

    def test_compound_guard_supports_nested_all_any(self) -> None:
        conditions = {
            "all": [
                {"target_agent": {"in": ["_xworker"]}},
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
                {"target_agent": "_xworker", "metadata": {"status": "ok"}},
                conditions,
            )
        )
        self.assertFalse(
            agents_factory._workflow_conditions_match(
                {"target_agent": "_xplaner_xrouter", "metadata": {"status": "ok"}},
                conditions,
            )
        )


if __name__ == "__main__":
    unittest.main()