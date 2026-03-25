from __future__ import annotations

from copy import deepcopy
import json
from pprint import pformat
from alde.agents_persisted_config import (
    ACTION_REQUEST_SCHEMA_CONFIGS,
    AGENT_MANIFEST_OVERRIDES,
    AGENT_ROLE_CONFIGS,
    AGENT_RUNTIME_CONFIG,
    AGENT_SKILL_PROFILES,
    ALLOWED_INSTANCE_POLICIES,
    BATCH_WORKFLOW_CONFIGS,
    FORCED_ROUTE_CONFIGS,
    HANDOFF_PROTOCOL_CONFIGS,
    HANDOFF_SCHEMA_CONFIGS,
    PROMPT_FRAGMENT_CONFIGS,
    SYSTEM_PROMPT,
    TOOL_CONFIGS,
    TOOL_GROUP_CONFIGS,
    TOOL_NAME_ALIASES,
    WORKFLOW_CONFIGS,
    _CANONICAL_AGENT_LABEL_MAP,
    _LEGACY_AGENT_NAME_MAP,
    _SPECIALIZED_AGENT_MAP,
)
from typing import Any


PromptConfig = dict[str, Any]


def _json_block(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _python_literal_block(value: Any) -> str:
    return pformat(value, sort_dicts=False, width=100)


def _compose_prompt(config: PromptConfig) -> str:
    sections: list[str] = []

    prompt = str(config.get("prompt") or "").strip()
    if prompt:
        sections.append(prompt)

    task = config.get("task") or {}
    if task:
        sections.append("## Task\n" + _json_block(task))

    output_schema = config.get("output_schema") or {}
    if output_schema:
        sections.append("## Output Schema\n" + _json_block(output_schema))

    return "\n\n".join(section for section in sections if section).strip()


class ConfigMutationService:
    def set_object_value(
        self,
        config: dict[str, Any] | None,
        key_path: str,
        value: Any,
    ) -> dict[str, Any]:
        updated_config = deepcopy(config or {})
        segments = [segment.strip() for segment in str(key_path or "").split(".") if segment.strip()]
        if not segments:
            return updated_config

        current = updated_config
        for segment in segments[:-1]:
            existing_value = current.get(segment)
            if not isinstance(existing_value, dict):
                existing_value = {}
                current[segment] = existing_value
            current = existing_value
        current[segments[-1]] = deepcopy(value)
        return updated_config

    def set_object_values(
        self,
        config: dict[str, Any] | None,
        config_updates: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated_config = deepcopy(config or {})
        for key_path, value in (config_updates or {}).items():
            normalized_key = str(key_path or "").strip()
            if not normalized_key:
                continue
            if "." in normalized_key:
                updated_config = self.set_object_value(updated_config, normalized_key, value)
                continue
            updated_config[normalized_key] = deepcopy(value)
        return updated_config


CONFIG_MUTATION_SERVICE = ConfigMutationService()


def set_config_value(config: dict[str, Any] | None, key_path: str, value: Any) -> dict[str, Any]:
    return CONFIG_MUTATION_SERVICE.set_object_value(config, key_path, value)


def set_config_values(config: dict[str, Any] | None, config_updates: dict[str, Any] | None) -> dict[str, Any]:
    return CONFIG_MUTATION_SERVICE.set_object_values(config, config_updates)


def _normalize_config_object_token(value: str, *, fallback: str = "object") -> str:
    import re

    normalized_value = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
    return normalized_value or fallback


def _workflow_definition_for_agent(agent_label: str) -> str:
    runtime_config = AGENT_RUNTIME_CONFIG.get(agent_label) or {}
    workflow = runtime_config.get("workflow") or {}
    workflow_name = str(runtime_config.get("workflow_name") or workflow.get("definition") or "")
    return workflow_name


def _build_agent_manifest(agent_label: str) -> dict[str, Any]:
    runtime_config = AGENT_RUNTIME_CONFIG.get(agent_label) or {}
    override = AGENT_MANIFEST_OVERRIDES.get(agent_label) or {}
    canonical_name = str(runtime_config.get("canonical_name") or normalize_agent_name(agent_label))
    skill_profile_name = str(override.get("skill_profile") or "")
    skill_profile = AGENT_SKILL_PROFILES.get(skill_profile_name) or {}
    role_name = str(override.get("role") or skill_profile.get("role") or "worker")
    role_config = AGENT_ROLE_CONFIGS.get(role_name) or AGENT_ROLE_CONFIGS["worker"]
    workflow_name = _workflow_definition_for_agent(agent_label)
    tools = list(runtime_config.get("tools") or [])

    routing_policy = dict(override.get("routing_policy") or {})
    routing_policy.setdefault("mode", role_name)
    routing_policy.setdefault("can_route", bool(role_config.get("can_route")))

    history_policy = dict(role_config.get("default_history_policy") or {})
    history_policy.update(dict(override.get("history_policy") or {}))

    handoff_policy = dict(role_config.get("default_handoff_policy") or {})
    handoff_override = dict(override.get("handoff_policy") or {})
    handoff_policy.update(
        {
            key: value
            for key, value in handoff_override.items()
            if key not in {"accepted_protocols", "emitted_protocols", "allowed_targets", "allowed_sources", "target_policies", "source_policies"}
        }
    )
    for key in ("accepted_protocols", "emitted_protocols", "allowed_targets", "allowed_sources"):
        if key in handoff_override:
            raw_values = handoff_override.get(key) or []
            handoff_policy[key] = [str(value) for value in raw_values if str(value).strip()]
    for key in ("target_policies", "source_policies"):
        merged_policy_map = dict(handoff_policy.get(key) or {})
        raw_policy_map = handoff_override.get(key) or {}
        if isinstance(raw_policy_map, dict):
            for policy_agent, policy_config in raw_policy_map.items():
                normalized_policy_agent = normalize_agent_label(str(policy_agent or ""))
                if not normalized_policy_agent:
                    continue
                merged_policy_map[normalized_policy_agent] = dict(policy_config or {})
        handoff_policy[key] = merged_policy_map
    handoff_policy.setdefault("default_protocol", "message_text")
    handoff_policy.setdefault("accepted_protocols", ["message_text", "agent_handoff_v1"])
    handoff_policy.setdefault("emitted_protocols", list(handoff_policy.get("accepted_protocols") or []))
    handoff_policy.setdefault("allowed_targets", [])
    handoff_policy.setdefault("allowed_sources", [])
    handoff_policy.setdefault("target_policies", {})
    handoff_policy.setdefault("source_policies", {})

    instance_policy = str(
        override.get("instance_policy")
        or role_config.get("default_instance_policy")
        or "ephemeral"
    )

    return {
        "agent_label": agent_label,
        "canonical_name": canonical_name,
        "role": role_name,
        "role_config": deepcopy(role_config),
        "skill_profile": skill_profile_name,
        "skill_profile_config": deepcopy(skill_profile),
        "prompt_config_name": canonical_name,
        "prompt_fragments": list(skill_profile.get("prompt_fragments") or []),
        "model": runtime_config.get("model") or "",
        "system": get_system_prompt(agent_label),
        "tools": tools,
        "tool_groups": [tool_name for tool_name in tools if isinstance(tool_name, str) and tool_name.startswith("@")],
        "direct_tools": [
            TOOL_NAME_ALIASES.get(tool_name, tool_name)
            for tool_name in tools
            if isinstance(tool_name, str) and not tool_name.startswith("@")
        ],
        "defaults": dict(runtime_config.get("defaults") or {}),
        "workflow": dict(runtime_config.get("workflow") or {}),
        "workflow_name": workflow_name,
        "instance_policy": instance_policy,
        "routing_policy": routing_policy,
        "handoff_policy": handoff_policy,
        "history_policy": history_policy,
    }


AGENT_MANIFESTS: dict[str, dict[str, Any]] = {}


class AgentConfigObject:
    def __init__(self, object_name: str, manifest: dict[str, Any] | None, agent_config_service: "AgentConfigService") -> None:
        self.object_name = object_name
        self.manifest = dict(manifest or {})
        self.agent_config_service = agent_config_service

    def load_object_label(self) -> str:
        return self.agent_config_service.normalize_object_label(self.object_name)

    def load_canonical_name(self) -> str:
        return self.agent_config_service.normalize_object_name(self.object_name)

    def build_missing_config(self) -> dict[str, Any]:
        object_label = self.load_object_label()
        return {
            "agent_label": object_label,
            "canonical_name": self.load_canonical_name(),
            "role": "worker",
            "model": "",
            "system": self.agent_config_service.load_system_object(self.object_name),
            "tools": [],
            "defaults": {},
            "workflow": {},
            "workflow_name": "",
            "instance_policy": "ephemeral",
            "routing_policy": {"mode": "worker", "can_route": False},
            "handoff_policy": {
                "default_protocol": "message_text",
                "accepted_protocols": ["message_text", "agent_handoff_v1"],
                "emitted_protocols": ["message_text", "agent_handoff_v1"],
                "allowed_targets": [],
            },
            "history_policy": {"followup_history_depth": 6, "include_routed_history": False, "routed_history_depth": 0},
        }

    def to_config_dict(self) -> dict[str, Any]:
        if not self.manifest:
            return self.build_missing_config()

        return {
            "agent_label": self.manifest["agent_label"],
            "canonical_name": self.manifest["canonical_name"],
            "role": self.manifest["role"],
            "skill_profile": self.manifest["skill_profile"],
            "model": self.manifest["model"],
            "system": self.manifest["system"],
            "tools": list(self.manifest.get("tools") or []),
            "defaults": dict(self.manifest.get("defaults") or {}),
            "workflow": dict(self.manifest.get("workflow") or {}),
            "workflow_name": self.manifest.get("workflow_name") or "",
            "instance_policy": self.manifest.get("instance_policy") or "ephemeral",
            "routing_policy": dict(self.manifest.get("routing_policy") or {}),
            "handoff_policy": dict(self.manifest.get("handoff_policy") or {}),
            "history_policy": dict(self.manifest.get("history_policy") or {}),
        }

    def to_registry_dict(self) -> dict[str, Any]:
        config = self.to_config_dict()
        return {
            "model": config["model"],
            "system": config["system"],
            "tools": list(config.get("tools") or []),
            "role": config.get("role") or "worker",
            "workflow_name": config.get("workflow_name") or "",
            "instance_policy": config.get("instance_policy") or "ephemeral",
            "handoff_policy": dict(config.get("handoff_policy") or {}),
        }


class AgentConfigService:
    def normalize_object_name(self, object_name: str) -> str:
        return _LEGACY_AGENT_NAME_MAP.get(object_name, object_name)

    def normalize_object_label(self, object_name: str) -> str:
        if object_name in AGENT_RUNTIME_CONFIG:
            return object_name

        canonical_name = self.normalize_object_name(object_name)
        return _CANONICAL_AGENT_LABEL_MAP.get(canonical_name, object_name)

    def load_prompt_object(self, object_name: str) -> dict[str, Any]:
        canonical_name = self.normalize_object_name(object_name)
        return SYSTEM_PROMPT.get(canonical_name, {"prompt": "", "task": {}, "output_schema": {}})

    def build_missing_prompt_object(self) -> dict[str, Any]:
        return {"prompt": "", "task": {}, "output_schema": {}}

    def create_prompt_object(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt_config = self.load_prompt_object(object_name) or self.build_missing_prompt_object()
        return set_config_values(prompt_config, config_updates)

    def load_system_object(self, object_name: str) -> str:
        return _compose_prompt(self.load_prompt_object(object_name))

    def load_object_projection(self, object_name: str) -> AgentConfigObject:
        object_label = self.normalize_object_label(object_name)
        return AgentConfigObject(object_name, AGENT_MANIFESTS.get(object_label), self)

    def _build_missing_object_config(self, object_name: str) -> dict[str, Any]:
        return self.load_object_projection(object_name).build_missing_config()

    def load_object_config(self, object_name: str) -> dict[str, Any]:
        return self.load_object_projection(object_name).to_config_dict()

    def list_registry_objects(self) -> dict[str, dict[str, Any]]:
        return {
            object_label: self.load_object_projection(object_label).to_registry_dict()
            for object_label in AGENT_MANIFESTS
        }

    def list_available_object_names(self) -> list[str]:
        return list(AGENT_MANIFESTS.keys())

    def load_object_manifest(self, object_name: str) -> dict[str, Any]:
        object_label = self.normalize_object_label(object_name)
        return deepcopy(AGENT_MANIFESTS.get(object_label, {}))

    def list_object_manifests(self) -> dict[str, dict[str, Any]]:
        return deepcopy(AGENT_MANIFESTS)

    def build_missing_runtime_object(self, object_name: str) -> dict[str, Any]:
        return {
            "canonical_name": self.normalize_object_name(object_name),
            "model": "",
            "tools": [],
            "defaults": {},
            "workflow": {},
        }

    def create_runtime_object(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        object_label = self.normalize_object_label(object_name)
        runtime_config = deepcopy(AGENT_RUNTIME_CONFIG.get(object_label) or self.build_missing_runtime_object(object_name))
        return set_config_values(runtime_config, config_updates)

    def build_missing_manifest_override_object(self) -> dict[str, Any]:
        return {
            "role": "worker",
            "skill_profile": "",
            "routing_policy": {},
            "handoff_policy": {},
            "history_policy": {},
        }

    def create_manifest_override_object(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        object_label = self.normalize_object_label(object_name)
        manifest_override = deepcopy(AGENT_MANIFEST_OVERRIDES.get(object_label) or self.build_missing_manifest_override_object())
        return set_config_values(manifest_override, config_updates)

    def create_object_config(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        object_config = self.load_object_config(object_name) or self._build_missing_object_config(object_name)
        return set_config_values(object_config, config_updates)


AGENT_CONFIG_SERVICE = AgentConfigService()


def normalize_agent_name(agent_name: str) -> str:
    return AGENT_CONFIG_SERVICE.normalize_object_name(agent_name)


def normalize_agent_label(agent_name: str) -> str:
    return AGENT_CONFIG_SERVICE.normalize_object_label(agent_name)


def get_prompt_config(agent_name: str) -> dict[str, Any]:
    return AGENT_CONFIG_SERVICE.load_prompt_object(agent_name)


def create_prompt_config(agent_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return AGENT_CONFIG_SERVICE.create_prompt_object(agent_name, config_updates)


def get_system_prompt(agent_name: str) -> str:
    return AGENT_CONFIG_SERVICE.load_system_object(agent_name)


def _materialize_agent_manifests() -> dict[str, dict[str, Any]]:
    return {
        agent_label: _build_agent_manifest(agent_label)
        for agent_label in AGENT_RUNTIME_CONFIG
    }


AGENT_MANIFESTS = _materialize_agent_manifests()


AGENT_WORKFLOW_MAP = {
    agent_label: workflow_name
    for agent_label in AGENT_MANIFESTS
    for workflow_name in [str((AGENT_MANIFESTS.get(agent_label) or {}).get("workflow_name") or "")]
    if workflow_name
}


def get_agent_config(agent_name: str) -> dict[str, Any]:
    return AGENT_CONFIG_SERVICE.load_object_config(agent_name)


def create_agent_runtime_config(agent_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return AGENT_CONFIG_SERVICE.create_runtime_object(agent_name, config_updates)


def create_agent_manifest_override_config(agent_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return AGENT_CONFIG_SERVICE.create_manifest_override_object(agent_name, config_updates)


def create_agent_config(agent_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return AGENT_CONFIG_SERVICE.create_object_config(agent_name, config_updates)


def get_agents_registry_data() -> dict[str, dict[str, Any]]:
    return AGENT_CONFIG_SERVICE.list_registry_objects()


def get_available_agent_labels() -> list[str]:
    return AGENT_CONFIG_SERVICE.list_available_object_names()


def get_agent_manifest(agent_name: str) -> dict[str, Any]:
    return AGENT_CONFIG_SERVICE.load_object_manifest(agent_name)


def get_agent_manifests() -> dict[str, dict[str, Any]]:
    return AGENT_CONFIG_SERVICE.list_object_manifests()


def _config_payload_value(payload: dict[str, Any], key: str) -> Any:
    current: Any = payload
    for segment in str(key).split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _config_condition_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if "all" in expected:
            return all(_config_condition_matches(actual, item) for item in (expected.get("all") or []))
        if "any" in expected:
            return any(_config_condition_matches(actual, item) for item in (expected.get("any") or []))
        if "not" in expected:
            return not _config_condition_matches(actual, expected.get("not"))
        if "eq" in expected:
            return actual == expected.get("eq")
        if "in" in expected:
            return actual in (expected.get("in") or [])
        if "exists" in expected:
            return (actual is not None) == bool(expected.get("exists"))
        if "truthy" in expected:
            return bool(actual) == bool(expected.get("truthy"))
    return actual == expected


def _config_conditions_match(payload: dict[str, Any], conditions: Any) -> bool:
    if not conditions:
        return True
    if isinstance(conditions, dict):
        if "all" in conditions:
            return all(_config_conditions_match(payload, item) for item in (conditions.get("all") or []))
        if "any" in conditions:
            return any(_config_conditions_match(payload, item) for item in (conditions.get("any") or []))
        if "not" in conditions:
            return not _config_conditions_match(payload, conditions.get("not"))
        for key, expected in conditions.items():
            if not _config_condition_matches(_config_payload_value(payload, str(key)), expected):
                return False
        return True
    return bool(conditions)


def _resolve_route_template_value(value: Any, *, original_text: str, original_payload: Any, trigger_remainder: str = "") -> Any:
    if isinstance(value, str):
        if value == "__original_input__":
            return original_text
        if value == "__original_payload__":
            return deepcopy(original_payload)
        if value == "__trigger_remainder__":
            return trigger_remainder
        if value == "__cover_letter_writer_payload__":
            if not isinstance(original_payload, dict):
                return deepcopy(original_payload)
            narrowed_payload: dict[str, Any] = {}
            for key in ("action", "job_posting_result", "profile_result", "options", "correlation_id"):
                if key in original_payload:
                    narrowed_payload[key] = deepcopy(original_payload.get(key))
            return narrowed_payload
        return value
    if isinstance(value, list):
        return [
            _resolve_route_template_value(item, original_text=original_text, original_payload=original_payload, trigger_remainder=trigger_remainder)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(key): _resolve_route_template_value(item, original_text=original_text, original_payload=original_payload, trigger_remainder=trigger_remainder)
            for key, item in value.items()
        }
    return value


def resolve_forced_route(agent_name: str, input_text: Any, available_agents: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any] | None:
    agent_label = normalize_agent_label(agent_name)
    route_configs = FORCED_ROUTE_CONFIGS.get(agent_label) or []
    available = {str(agent) for agent in available_agents}
    text = input_text if isinstance(input_text, str) else json.dumps(input_text, ensure_ascii=False)

    for route_config in route_configs:
        trigger = route_config.get("trigger") or {}
        trigger_type = str(trigger.get("type") or "")

        if trigger_type == "at_prefix":
            import re

            match = re.match(r"^\s*@\s*([A-Za-z0-9_\-]+)\b[\s:,-]*", text or "")
            if not match:
                continue
            agent_token = (match.group(1) or "").strip()
            remainder = (text[match.end():] or "").lstrip()
            candidates = [agent_token if agent_token.startswith("_") else f"_{agent_token}", agent_token]
            for candidate in candidates:
                if candidate in available:
                    return {
                        "target_agent": candidate,
                        "user_question": remainder or "",
                    }
            continue

        if trigger_type == "text_prefix":
            prefix = str(trigger.get("prefix") or "")
            if not prefix:
                continue
            match_text = text or ""
            compare_text = match_text.casefold() if bool(trigger.get("ignore_case", True)) else match_text
            compare_prefix = prefix.casefold() if bool(trigger.get("ignore_case", True)) else prefix
            if not compare_text.startswith(compare_prefix):
                continue
            remainder = (match_text[len(prefix):] or "").lstrip()
            route = dict(route_config.get("route") or {})
            target_agent = normalize_agent_label(str(route.get("target_agent") or ""))
            if target_agent not in available:
                continue
            resolved_route = _resolve_route_template_value(
                route,
                original_text=text,
                original_payload=input_text,
                trigger_remainder=remainder,
            )
            if not isinstance(resolved_route, dict):
                continue
            resolved_route["target_agent"] = target_agent
            if not any(
                resolved_route.get(key) not in (None, "", [], {})
                for key in ("user_question", "message_text", "agent_response", "handoff_payload")
            ):
                resolved_route["user_question"] = remainder or text
            return resolved_route

        if trigger_type == "json_payload":
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if not _config_conditions_match(payload, trigger.get("conditions") or {}):
                continue
            route = dict(route_config.get("route") or {})
            target_agent = str(route.get("target_agent") or "")
            if target_agent not in available:
                continue
            resolved_route = _resolve_route_template_value(route, original_text=text, original_payload=payload)
            if not isinstance(resolved_route, dict):
                continue
            resolved_route["target_agent"] = target_agent
            if (
                "user_question" not in resolved_route
                and "message_text" not in resolved_route
                and "agent_response" not in resolved_route
                and "handoff_payload" not in resolved_route
            ):
                resolved_route["user_question"] = text
            return resolved_route

    return None


class ActionRequestSchemaService:
    def list_object_configs(self) -> dict[str, dict[str, Any]]:
        return deepcopy(ACTION_REQUEST_SCHEMA_CONFIGS)

    def load_object_config(self, object_name: str) -> dict[str, Any]:
        normalized_action = str(object_name or "").strip().lower()
        for schema_name, config in ACTION_REQUEST_SCHEMA_CONFIGS.items():
            actions = {str(value or "").strip().lower() for value in (config.get("actions") or [])}
            if normalized_action in actions:
                schema = deepcopy(config)
                schema.setdefault("name", schema_name)
                return schema
        return {}

    def build_missing_object_config(self, object_name: str) -> dict[str, Any]:
        return {
            "name": str(object_name or "").strip(),
            "description": "",
            "actions": [],
            "required_paths": [],
            "recommended_paths": [],
            "conditions": {},
            "request_resolution": {},
        }

    def create_object_config(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        action_config = self.load_object_config(object_name) or self.build_missing_object_config(object_name)
        return set_config_values(action_config, config_updates)


ACTION_REQUEST_SCHEMA_SERVICE = ActionRequestSchemaService()


def get_action_request_schema_configs() -> dict[str, dict[str, Any]]:
    return ACTION_REQUEST_SCHEMA_SERVICE.list_object_configs()


def get_action_request_schema_config(action_name: str) -> dict[str, Any]:
    return ACTION_REQUEST_SCHEMA_SERVICE.load_object_config(action_name)


def create_action_request_schema_config(action_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return ACTION_REQUEST_SCHEMA_SERVICE.create_object_config(action_name, config_updates)


def validate_action_request(action_name: str, payload: Any) -> dict[str, Any]:
    schema = get_action_request_schema_config(action_name)
    normalized_action = str(action_name or "").strip().lower()
    errors: list[str] = []
    warnings: list[str] = []

    if not schema:
        return {
            "action": normalized_action,
            "schema_name": "",
            "valid": True,
            "errors": [],
            "warnings": [],
        }

    if not isinstance(payload, dict):
        return {
            "action": normalized_action,
            "schema_name": str(schema.get("name") or ""),
            "valid": False,
            "errors": ["deterministic action payload must be a JSON object"],
            "warnings": [],
        }

    for key_path in schema.get("required_paths") or []:
        if _config_payload_value(payload, str(key_path)) in (None, "", []):
            errors.append(f"missing required field '{key_path}'")

    conditions = schema.get("conditions") or {}
    if conditions and not _config_conditions_match(payload, conditions):
        errors.append("payload does not satisfy action request schema conditions")

    for key_path in schema.get("recommended_paths") or []:
        if _config_payload_value(payload, str(key_path)) in (None, "", []):
            warnings.append(f"recommended field '{key_path}' is missing")

    return {
        "action": normalized_action,
        "schema_name": str(schema.get("name") or ""),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


class ToolConfigObject:
    def __init__(self, object_name: str, tool_config_service: "ToolConfigService") -> None:
        self.object_name = object_name
        self.tool_config_service = tool_config_service

    def load_normalized_name(self) -> str:
        return self.tool_config_service.normalize_object_name(self.object_name)

    def to_config_dict(self) -> dict[str, Any]:
        normalized_name = self.load_normalized_name()
        for object_config in TOOL_CONFIGS:
            if object_config.get("name") == normalized_name:
                return deepcopy(object_config)
        return {}

    def build_missing_config(self) -> dict[str, Any]:
        return {
            "name": self.load_normalized_name(),
            "description": "",
            "parameters": [],
        }

    def create_config_dict(self, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        object_config = self.to_config_dict() or self.build_missing_config()
        return set_config_values(object_config, config_updates)


class ToolConfigService:
    def normalize_object_name(self, object_name: str) -> str:
        return TOOL_NAME_ALIASES.get(object_name, object_name)

    def load_object_projection(self, object_name: str) -> ToolConfigObject:
        return ToolConfigObject(object_name, self)

    def list_available_object_names(self) -> list[str]:
        return [str(tool_config.get("name") or "") for tool_config in TOOL_CONFIGS if str(tool_config.get("name") or "")]

    def list_object_configs(self) -> list[dict[str, Any]]:
        return deepcopy(TOOL_CONFIGS)

    def load_object_config(self, object_name: str) -> dict[str, Any]:
        return self.load_object_projection(object_name).to_config_dict()

    def create_object_config(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.load_object_projection(object_name).create_config_dict(config_updates)

    def list_object_group_configs(self) -> dict[str, list[str]]:
        return deepcopy(TOOL_GROUP_CONFIGS)

    def load_object_group_config(self, object_name: str) -> list[str]:
        return list(TOOL_GROUP_CONFIGS.get(object_name, []))


TOOL_CONFIG_SERVICE = ToolConfigService()


def normalize_tool_name(tool_name: str) -> str:
    return TOOL_CONFIG_SERVICE.normalize_object_name(tool_name)


def get_available_tool_names() -> list[str]:
    return TOOL_CONFIG_SERVICE.list_available_object_names()


def get_tool_configs() -> list[dict[str, Any]]:
    return TOOL_CONFIG_SERVICE.list_object_configs()


def get_tool_config(tool_name: str) -> dict[str, Any]:
    return TOOL_CONFIG_SERVICE.load_object_config(tool_name)


def create_tool_config(tool_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return TOOL_CONFIG_SERVICE.create_object_config(tool_name, config_updates)


def get_tool_group_configs() -> dict[str, list[str]]:
    return TOOL_CONFIG_SERVICE.list_object_group_configs()


def get_tool_group_config(group_name: str) -> list[str]:
    return TOOL_CONFIG_SERVICE.load_object_group_config(group_name)


class WorkflowConfigObject:
    def __init__(self, workflow_name: str, workflow_config: dict[str, Any] | None) -> None:
        self.workflow_name = workflow_name
        self.workflow_config = dict(workflow_config or {})

    def to_config_dict(self) -> dict[str, Any]:
        return deepcopy(self.workflow_config)

    def to_named_config_dict(self) -> dict[str, Any]:
        workflow_config = self.to_config_dict()
        if workflow_config:
            workflow_config.setdefault("name", self.workflow_name)
        return workflow_config

    def build_missing_config(self) -> dict[str, Any]:
        return {
            "name": self.workflow_name,
            "description": "",
            "entry_state": "",
            "states": {},
            "transitions": [],
            "retry_policy": {},
        }

    def create_config_dict(self, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_config = self.to_named_config_dict() or self.build_missing_config()
        return set_config_values(workflow_config, config_updates)


class AgentWorkflowConfigObject:
    def __init__(self, agent_name: str, workflow_config_service: "WorkflowConfigService") -> None:
        self.agent_name = agent_name
        self.workflow_config_service = workflow_config_service

    def load_agent_label(self) -> str:
        return normalize_agent_label(self.agent_name)

    def load_workflow_name(self) -> str:
        agent_label = self.load_agent_label()
        manifest = AGENT_MANIFESTS.get(agent_label) or {}
        workflow_name = str(manifest.get("workflow_name") or AGENT_WORKFLOW_MAP.get(agent_label) or "")
        if workflow_name:
            return workflow_name

        agent_runtime = AGENT_RUNTIME_CONFIG.get(agent_label) or {}
        workflow_name = str(agent_runtime.get("workflow_name") or "")
        if workflow_name:
            return workflow_name
        return str(((agent_runtime.get("workflow") or {}).get("definition")) or "")

    def to_config_dict(self) -> dict[str, Any]:
        workflow_name = self.load_workflow_name()
        if not workflow_name:
            return {}
        return self.workflow_config_service.load_object_projection(workflow_name).to_named_config_dict()


class WorkflowConfigService:
    def load_object_projection(self, object_name: str) -> WorkflowConfigObject:
        return WorkflowConfigObject(object_name, WORKFLOW_CONFIGS.get(object_name, {}))

    def list_object_configs(self) -> dict[str, dict[str, Any]]:
        return deepcopy(WORKFLOW_CONFIGS)

    def load_object_config(self, object_name: str) -> dict[str, Any]:
        return self.load_object_projection(object_name).to_config_dict()

    def create_object_config(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.load_object_projection(object_name).create_config_dict(config_updates)

    def load_batch_object_projection(self, object_name: str) -> WorkflowConfigObject:
        return WorkflowConfigObject(object_name, BATCH_WORKFLOW_CONFIGS.get(object_name, {}))

    def list_batch_object_configs(self) -> dict[str, dict[str, Any]]:
        return deepcopy(BATCH_WORKFLOW_CONFIGS)

    def load_batch_object_config(self, object_name: str) -> dict[str, Any]:
        return self.load_batch_object_projection(object_name).to_config_dict()

    def build_missing_batch_object_config(self, object_name: str) -> dict[str, Any]:
        return {
            "name": object_name,
            "description": "",
            "dispatcher": {},
            "filters": {},
            "profile_result": {},
            "job_payload": {},
            "stages": [],
            "document_output": {},
            "dispatcher_record": {
                "success_updates": {},
                "failure_updates": {},
            },
        }

    def create_batch_object_config(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_config = self.load_batch_object_projection(object_name).to_named_config_dict() or self.build_missing_batch_object_config(object_name)
        return set_config_values(workflow_config, config_updates)

    def load_agent_object_projection(self, agent_name: str) -> AgentWorkflowConfigObject:
        return AgentWorkflowConfigObject(agent_name, self)

    def load_agent_object_config(self, agent_name: str) -> dict[str, Any]:
        return self.load_agent_object_projection(agent_name).to_config_dict()


WORKFLOW_CONFIG_SERVICE = WorkflowConfigService()


def get_workflow_configs() -> dict[str, dict[str, Any]]:
    return WORKFLOW_CONFIG_SERVICE.list_object_configs()


def get_workflow_config(workflow_name: str) -> dict[str, Any]:
    return WORKFLOW_CONFIG_SERVICE.load_object_config(workflow_name)


def create_workflow_config(workflow_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return WORKFLOW_CONFIG_SERVICE.create_object_config(workflow_name, config_updates)


def get_batch_workflow_configs() -> dict[str, dict[str, Any]]:
    return WORKFLOW_CONFIG_SERVICE.list_batch_object_configs()


def get_batch_workflow_config(workflow_name: str) -> dict[str, Any]:
    return WORKFLOW_CONFIG_SERVICE.load_batch_object_config(workflow_name)


def create_batch_workflow_config(workflow_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return WORKFLOW_CONFIG_SERVICE.create_batch_object_config(workflow_name, config_updates)


class HandoffConfigService:
    def list_protocol_objects(self) -> dict[str, dict[str, Any]]:
        return deepcopy(HANDOFF_PROTOCOL_CONFIGS)

    def load_protocol_object(self, object_name: str) -> dict[str, Any]:
        return deepcopy(HANDOFF_PROTOCOL_CONFIGS.get(str(object_name or ""), {}))

    def list_schema_objects(self) -> dict[str, dict[str, Any]]:
        return deepcopy(HANDOFF_SCHEMA_CONFIGS)

    def load_schema_object(self, object_name: str) -> dict[str, Any]:
        return deepcopy(HANDOFF_SCHEMA_CONFIGS.get(str(object_name or ""), {}))

    def load_agent_policy_object(self, object_name: str) -> dict[str, Any]:
        object_label = AGENT_CONFIG_SERVICE.normalize_object_label(object_name)
        manifest = AGENT_MANIFESTS.get(object_label) or {}
        return deepcopy(manifest.get("handoff_policy") or {})

    def build_missing_protocol_object(self, object_name: str) -> dict[str, Any]:
        return {
            "name": str(object_name or "").strip(),
            "description": "",
            "transport": "user_message",
            "mode": "text",
        }

    def create_protocol_object(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        protocol_config = self.load_protocol_object(object_name) or self.build_missing_protocol_object(object_name)
        return set_config_values(protocol_config, config_updates)

    def build_missing_schema_object(self, object_name: str) -> dict[str, Any]:
        return {
            "name": str(object_name or "").strip(),
            "protocol": "message_text",
            "description": "",
            "instructions": [],
        }

    def create_schema_object(self, object_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
        schema_config = self.load_schema_object(object_name) or self.build_missing_schema_object(object_name)
        return set_config_values(schema_config, config_updates)


HANDOFF_CONFIG_SERVICE = HandoffConfigService()


def get_handoff_protocol_configs() -> dict[str, dict[str, Any]]:
    return HANDOFF_CONFIG_SERVICE.list_protocol_objects()


def get_handoff_protocol_config(protocol_name: str) -> dict[str, Any]:
    return HANDOFF_CONFIG_SERVICE.load_protocol_object(protocol_name)


def create_handoff_protocol_config(protocol_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return HANDOFF_CONFIG_SERVICE.create_protocol_object(protocol_name, config_updates)


def get_handoff_schema_configs() -> dict[str, dict[str, Any]]:
    return HANDOFF_CONFIG_SERVICE.list_schema_objects()


def get_handoff_schema_config(schema_name: str) -> dict[str, Any]:
    return HANDOFF_CONFIG_SERVICE.load_schema_object(schema_name)


def create_handoff_schema_config(schema_name: str, config_updates: dict[str, Any] | None = None) -> dict[str, Any]:
    return HANDOFF_CONFIG_SERVICE.create_schema_object(schema_name, config_updates)


def get_agent_handoff_policy(agent_name: str) -> dict[str, Any]:
    return HANDOFF_CONFIG_SERVICE.load_agent_policy_object(agent_name)


class HandoffRouteService:
    def normalize_object_name(self, object_name: str | None) -> str:
        target = str(object_name or "").strip()
        if not target:
            return ""
        return normalize_agent_label(target)

    def extract_object_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("message_text", "user_question", "msg", "generated", "output", "content", "text"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    def load_route_contract(
        self,
        source_object_name: str | None,
        target_object_name: str | None,
        *,
        protocol: str | None = None,
    ) -> dict[str, Any]:
        source_label = self.normalize_object_name(source_object_name)
        target_label = self.normalize_object_name(target_object_name)
        source_policy = get_agent_handoff_policy(source_label) if source_label else {}
        target_policy = get_agent_handoff_policy(target_label) if target_label else {}
        source_target_policy = dict((source_policy.get("target_policies") or {}).get(target_label, {}) or {}) if target_label else {}
        target_source_policy = dict((target_policy.get("source_policies") or {}).get(source_label, {}) or {}) if source_label else {}

        selected_protocol = str(
            protocol
            or source_target_policy.get("default_protocol")
            or target_source_policy.get("default_protocol")
            or source_policy.get("default_protocol")
            or target_policy.get("default_protocol")
            or "message_text"
        ).strip()

        contract = {
            "source_agent": source_label,
            "target_agent": target_label,
            "protocol": selected_protocol,
            "accepted_protocols": list(target_source_policy.get("accepted_protocols") or source_target_policy.get("accepted_protocols") or []),
            "emitted_protocols": list(source_target_policy.get("emitted_protocols") or source_policy.get("emitted_protocols") or []),
            "handoff_schema": str(target_source_policy.get("handoff_schema") or source_target_policy.get("handoff_schema") or "").strip(),
            "workflow_name": str(
                target_source_policy.get("workflow_name")
                or source_target_policy.get("workflow_name")
                or (get_agent_config(target_label).get("workflow_name") if target_label else "")
                or ""
            ).strip(),
            "instructions": list(target_source_policy.get("instructions") or source_target_policy.get("instructions") or []),
        }
        schema_name = str(contract.get("handoff_schema") or "").strip()
        schema_config = get_handoff_schema_config(schema_name) if schema_name else {}
        if schema_config:
            contract["schema"] = schema_config
            if not contract["workflow_name"]:
                contract["workflow_name"] = str(schema_config.get("workflow_name") or "")
            if not contract["instructions"]:
                contract["instructions"] = list(schema_config.get("instructions") or [])
            if schema_config.get("protocol") and not protocol:
                contract["protocol"] = str(schema_config.get("protocol") or contract["protocol"])
        else:
            contract["schema"] = {}
        return contract

    def normalize_agent_response_object(
        self,
        value: Any,
        *,
        source_object_name: str | None,
        target_object_name: str | None,
    ) -> dict[str, Any]:
        if isinstance(value, dict):
            payload = deepcopy(value)
        elif isinstance(value, str):
            payload = {"msg": value}
        elif value is None:
            payload = {}
        else:
            payload = {"output": value}

        source_label = self.normalize_object_name(payload.get("agent_label") or source_object_name)
        if source_label:
            payload["agent_label"] = source_label

        resolved_target = self.normalize_object_name(payload.get("handoff_to") or target_object_name)
        if resolved_target:
            payload["handoff_to"] = resolved_target

        has_content = any(payload.get(key) not in (None, "", []) for key in ("output", "generated", "msg"))
        if not has_content:
            message_text = self.extract_object_text(payload)
            if message_text:
                payload["msg"] = message_text

        return payload

    def build_object_handoff(
        self,
        *,
        source_object_name: str | None,
        target_object_name: str | None = None,
        protocol: str | None = None,
        message_text: str | None = None,
        agent_response: Any = None,
        handoff_payload: Any = None,
        handoff_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_label = self.normalize_object_name(source_object_name)
        selected_protocol = str(
            protocol
            or (
                "agent_handoff_v1"
                if agent_response is not None or handoff_payload is not None
                else "message_text"
            )
        ).strip()
        if selected_protocol not in HANDOFF_PROTOCOL_CONFIGS:
            raise ValueError(f"Unknown handoff protocol: {selected_protocol}")

        metadata = deepcopy(handoff_metadata or {})

        if selected_protocol == "message_text":
            resolved_target = self.normalize_object_name(target_object_name)
            rendered_message = self.extract_object_text(message_text or handoff_payload or agent_response)
            if not rendered_message:
                raise ValueError("message_text handoff requires message_text, user_question, handoff_payload, or agent_response")
            return {
                "protocol": selected_protocol,
                "source_agent": source_label,
                "target_agent": resolved_target,
                "message_text": rendered_message,
                "handoff_payload": None,
                "metadata": metadata,
            }

        normalized_payload = self.normalize_agent_response_object(
            agent_response if agent_response is not None else handoff_payload,
            source_object_name=source_label,
            target_object_name=target_object_name,
        )
        resolved_target = self.normalize_object_name(normalized_payload.get("handoff_to") or target_object_name)
        if not resolved_target:
            raise ValueError("agent_handoff_v1 requires a target_agent or handoff_to")
        normalized_payload["handoff_to"] = resolved_target
        if normalized_payload.get("agent_label") in (None, "") and source_label:
            normalized_payload["agent_label"] = source_label
        if not any(normalized_payload.get(key) not in (None, "", []) for key in ("output", "generated", "msg")):
            raise ValueError("agent_handoff_v1 requires one of: output, generated, msg")

        envelope = {
            "protocol": selected_protocol,
            "source_agent": source_label or normalized_payload.get("agent_label") or "",
            "target_agent": resolved_target,
            "agent_response": normalized_payload,
            "metadata": metadata,
        }
        return {
            "protocol": selected_protocol,
            "source_agent": envelope["source_agent"],
            "target_agent": resolved_target,
            "message_text": json.dumps(envelope, ensure_ascii=False),
            "handoff_payload": normalized_payload,
            "metadata": metadata,
        }

    def validate_object_handoff(
        self,
        target_object_name: str,
        handoff: dict[str, Any],
        *,
        source_object_name: str | None = None,
    ) -> dict[str, Any]:
        target_label = normalize_agent_label(target_object_name)
        source_label = self.normalize_object_name(source_object_name or handoff.get("source_agent"))
        protocol = str(handoff.get("protocol") or "message_text").strip()
        target_policy = get_agent_handoff_policy(target_label)
        source_policy = get_agent_handoff_policy(source_label) if source_label else {}
        contract = self.load_route_contract(source_label, target_label, protocol=protocol)
        schema = dict(contract.get("schema") or {})
        errors: list[str] = []

        allowed_sources = [normalize_agent_label(str(value)) for value in (target_policy.get("allowed_sources") or []) if str(value).strip()]
        if source_label and allowed_sources and source_label != target_label and source_label not in set(allowed_sources):
            errors.append(f"source '{source_label}' is not allowed by handoff_policy.allowed_sources")

        emitted_protocols = [str(value) for value in (source_policy.get("emitted_protocols") or []) if str(value).strip()]
        if emitted_protocols and protocol not in set(emitted_protocols):
            errors.append(f"protocol '{protocol}' is not emitted by source agent '{source_label}'")

        accepted_protocols = [str(value) for value in (target_policy.get("accepted_protocols") or []) if str(value).strip()]
        if accepted_protocols and protocol not in set(accepted_protocols):
            errors.append(f"protocol '{protocol}' is not accepted by target agent '{target_label}'")

        contract_protocols = [str(value) for value in (contract.get("accepted_protocols") or []) if str(value).strip()]
        if contract_protocols and protocol not in set(contract_protocols):
            errors.append(f"protocol '{protocol}' is not accepted by the {source_label}->{target_label} handoff contract")

        schema_protocol = str(schema.get("protocol") or "").strip()
        if schema_protocol and protocol != schema_protocol:
            errors.append(f"protocol '{protocol}' does not match handoff schema '{schema_protocol}'")

        if bool(schema.get("required_message_text")) and not self.extract_object_text(handoff.get("message_text")):
            errors.append("handoff schema requires non-empty message_text")

        handoff_payload = handoff.get("handoff_payload") if isinstance(handoff.get("handoff_payload"), dict) else {}
        metadata = handoff.get("metadata") if isinstance(handoff.get("metadata"), dict) else {}
        for key_path in schema.get("required_payload_paths") or []:
            if not _handoff_path_exists(handoff_payload, str(key_path)):
                errors.append(f"handoff payload is missing required path '{key_path}'")
        for key_path in schema.get("required_metadata_paths") or []:
            if not _handoff_path_exists(metadata, str(key_path)):
                errors.append(f"handoff metadata is missing required path '{key_path}'")

        required_any_paths = [str(value) for value in (schema.get("required_payload_any") or []) if str(value).strip()]
        if required_any_paths and not any(_handoff_path_exists(handoff_payload, key_path) for key_path in required_any_paths):
            errors.append("handoff payload is missing all allowed content paths: " + ", ".join(required_any_paths))

        return {
            "valid": not errors,
            "errors": errors,
            "contract": contract,
        }

    def prepare_incoming_object_handoff(
        self,
        target_object_name: str,
        handoff: dict[str, Any],
        *,
        source_object_name: str | None = None,
    ) -> dict[str, Any]:
        target_label = normalize_agent_label(target_object_name)
        source_label = self.normalize_object_name(source_object_name or handoff.get("source_agent"))
        protocol = str(handoff.get("protocol") or "message_text").strip()
        contract = self.load_route_contract(source_label, target_label, protocol=protocol)
        schema = dict(contract.get("schema") or {})
        handoff_payload = deepcopy(handoff.get("handoff_payload") or {}) if isinstance(handoff.get("handoff_payload"), dict) else {}
        metadata = deepcopy(handoff.get("metadata") or {}) if isinstance(handoff.get("metadata"), dict) else {}

        preferred_paths = [str(value) for value in (schema.get("preferred_payload_paths") or []) if str(value).strip()]
        target_input_path = str(schema.get("target_input_path") or "").strip()
        selected_input: Any = None
        if target_input_path:
            selected_input = _config_payload_value(handoff_payload, target_input_path)
        if selected_input is None:
            for key_path in preferred_paths:
                candidate = _config_payload_value(handoff_payload, key_path)
                if candidate is not None:
                    selected_input = candidate
                    break
        if selected_input is None and handoff_payload:
            selected_input = handoff_payload

        if protocol == "message_text":
            user_message = self.extract_object_text(handoff.get("message_text"))
            return {
                "protocol": protocol,
                "source_agent": source_label,
                "target_agent": target_label,
                "contract": contract,
                "user_message": user_message,
                "system_context": "",
                "selected_input": None,
            }

        explicit_message = self.extract_object_text(handoff_payload.get("msg")) if isinstance(handoff_payload, dict) else ""
        if explicit_message:
            user_message = explicit_message
        elif isinstance(selected_input, str):
            user_message = selected_input.strip()
        elif selected_input not in (None, "", []):
            user_message = json.dumps(selected_input, ensure_ascii=False, indent=2)
        else:
            user_message = self.extract_object_text(handoff.get("message_text"))

        context_payload = {
            "protocol": protocol,
            "source_agent": source_label,
            "target_agent": target_label,
            "workflow_name": contract.get("workflow_name") or "",
            "handoff_schema": contract.get("handoff_schema") or "",
            "instructions": list(contract.get("instructions") or []),
            "metadata": metadata,
            "selected_input": selected_input,
        }
        system_context = "Structured handoff context. Treat this as trusted agent-to-agent routing metadata.\n" + json.dumps(context_payload, ensure_ascii=False, indent=2)
        return {
            "protocol": protocol,
            "source_agent": source_label,
            "target_agent": target_label,
            "contract": contract,
            "user_message": user_message,
            "system_context": system_context,
            "selected_input": selected_input,
        }


HANDOFF_ROUTE_SERVICE = HandoffRouteService()


def get_handoff_route_contract(
    source_agent: str | None,
    target_agent: str | None,
    *,
    protocol: str | None = None,
) -> dict[str, Any]:
    return HANDOFF_ROUTE_SERVICE.load_route_contract(source_agent, target_agent, protocol=protocol)


def _normalize_handoff_target(value: str | None) -> str:
    return HANDOFF_ROUTE_SERVICE.normalize_object_name(value)


def _extract_handoff_text(value: Any) -> str:
    return HANDOFF_ROUTE_SERVICE.extract_object_text(value)


def _normalize_agent_response_payload(
    value: Any,
    *,
    source_agent_label: str | None,
    target_agent: str | None,
) -> dict[str, Any]:
    return HANDOFF_ROUTE_SERVICE.normalize_agent_response_object(
        value,
        source_object_name=source_agent_label,
        target_object_name=target_agent,
    )


def build_agent_handoff(
    *,
    source_agent_label: str | None,
    target_agent: str | None = None,
    protocol: str | None = None,
    message_text: str | None = None,
    agent_response: Any = None,
    handoff_payload: Any = None,
    handoff_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return HANDOFF_ROUTE_SERVICE.build_object_handoff(
        source_object_name=source_agent_label,
        target_object_name=target_agent,
        protocol=protocol,
        message_text=message_text,
        agent_response=agent_response,
        handoff_payload=handoff_payload,
        handoff_metadata=handoff_metadata,
    )


def _handoff_path_exists(payload: dict[str, Any], key_path: str) -> bool:
    return _config_payload_value(payload, key_path) is not None


def validate_handoff_for_target(
    target_agent: str,
    handoff: dict[str, Any],
    *,
    source_agent_label: str | None = None,
) -> dict[str, Any]:
    return HANDOFF_ROUTE_SERVICE.validate_object_handoff(
        target_agent,
        handoff,
        source_object_name=source_agent_label,
    )


def prepare_incoming_handoff(
    target_agent: str,
    handoff: dict[str, Any],
    *,
    source_agent_label: str | None = None,
) -> dict[str, Any]:
    return HANDOFF_ROUTE_SERVICE.prepare_incoming_object_handoff(
        target_agent,
        handoff,
        source_object_name=source_agent_label,
    )


def get_agent_workflow_config(agent_name: str) -> dict[str, Any]:
    return WORKFLOW_CONFIG_SERVICE.load_agent_object_config(agent_name)


class WorkflowValidationObject:
    def __init__(
        self,
        workflow_name: str,
        workflow_config: dict[str, Any] | None = None,
    ) -> None:
        self.workflow_name = workflow_name
        self.config = deepcopy(workflow_config if workflow_config is not None else WORKFLOW_CONFIGS.get(workflow_name, {}))
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.states = self.config.get("states") or {}
        self.transitions = self.config.get("transitions") or []
        self.entry_state = str(self.config.get("entry_state") or "")
        self.retry_policy = self.config.get("retry_policy") or {}

    def load_missing_report(self) -> dict[str, Any]:
        return {
            "name": self.workflow_name,
            "valid": False,
            "errors": ["workflow definition is missing"],
            "warnings": [],
            "stats": {},
        }

    def load_known_agent_names(self) -> set[str]:
        return set(AGENT_RUNTIME_CONFIG.keys())

    def load_known_tool_names(self) -> set[str]:
        return {normalize_tool_name(name) for name in get_available_tool_names()} | {"route_to_agent", "vectordb_tool"}

    def validate_entry_state(self) -> None:
        if not self.entry_state:
            self.errors.append("entry_state is missing")
        elif self.entry_state not in self.states:
            self.errors.append(f"entry_state '{self.entry_state}' is not defined in states")

        if not self.states:
            self.errors.append("states definition is empty")

    def validate_retry_policy(self) -> tuple[int, list[int]]:
        try:
            max_attempts = int(self.retry_policy.get("max_attempts") or 0)
            if max_attempts < 0:
                self.errors.append("retry_policy.max_attempts must be >= 0")
        except Exception:
            self.errors.append("retry_policy.max_attempts must be an integer")
            max_attempts = 0

        raw_backoff = self.retry_policy.get("backoff_seconds") or []
        backoff_seconds: list[int] = []
        for index, value in enumerate(raw_backoff):
            try:
                parsed = int(value)
            except Exception:
                self.errors.append(f"retry_policy.backoff_seconds[{index}] must be an integer")
                continue
            if parsed < 0:
                self.errors.append(f"retry_policy.backoff_seconds[{index}] must be >= 0")
            backoff_seconds.append(parsed)

        if max_attempts and backoff_seconds and len(backoff_seconds) > max_attempts:
            self.warnings.append("retry_policy.backoff_seconds has more entries than max_attempts")
        return max_attempts, backoff_seconds

    def validate_states(
        self,
        known_agents: set[str],
        known_tools: set[str],
    ) -> set[str]:
        terminal_states = {state_name for state_name, state in self.states.items() if bool((state or {}).get("terminal", False))}
        for state_name, state_config in self.states.items():
            actor = (state_config or {}).get("actor") or {}
            actor_kind = str(actor.get("kind") or "")
            actor_name = str(actor.get("name") or "")
            if actor_kind not in {"agent", "tool", "state", ""}:
                self.errors.append(f"state '{state_name}' uses unsupported actor.kind '{actor_kind}'")
            if actor_kind == "agent" and actor_name and actor_name not in known_agents:
                self.errors.append(f"state '{state_name}' references unknown agent '{actor_name}'")
            if actor_kind == "tool" and actor_name and normalize_tool_name(actor_name) not in known_tools:
                self.errors.append(f"state '{state_name}' references unknown tool '{actor_name}'")
        return terminal_states

    def load_normalized_transitions(self, known_tools: set[str]) -> tuple[list[dict[str, Any]], set[str]]:
        normalized_transitions: list[dict[str, Any]] = []
        states_with_outgoing: set[str] = set()
        for index, transition in enumerate(self.transitions):
            if not isinstance(transition, dict):
                self.errors.append(f"transition[{index}] is not an object")
                continue
            sources_raw = transition.get("from")
            sources = [str(sources_raw)] if isinstance(sources_raw, str) else [str(item) for item in (sources_raw or [])]
            if not sources:
                self.errors.append(f"transition[{index}] is missing 'from'")
            for source in sources:
                if source not in self.states:
                    self.errors.append(f"transition[{index}] references unknown source state '{source}'")
                else:
                    states_with_outgoing.add(source)

            target_state = str(transition.get("to") or "")
            if not target_state:
                self.errors.append(f"transition[{index}] is missing 'to'")
            elif target_state not in self.states:
                self.errors.append(f"transition[{index}] references unknown target state '{target_state}'")

            event = transition.get("on") or {}
            event_kind = str(event.get("kind") or "")
            event_name = event.get("name")
            if event_kind not in {"tool", "state"}:
                self.errors.append(f"transition[{index}] uses unsupported event kind '{event_kind}'")
            if event_name in (None, "", []):
                self.errors.append(f"transition[{index}] is missing event name")
            if event_kind == "tool":
                names = [str(event_name)] if isinstance(event_name, str) else [str(item) for item in (event_name or [])]
                for name in names:
                    if normalize_tool_name(name) not in known_tools:
                        self.errors.append(f"transition[{index}] references unknown tool event '{name}'")

            normalized_transitions.append({"sources": sources, "target": target_state})
        return normalized_transitions, states_with_outgoing

    def load_reachable_states(self, normalized_transitions: list[dict[str, Any]]) -> set[str]:
        reachable_states: set[str] = {self.entry_state} if self.entry_state in self.states else set()
        frontier = list(reachable_states)
        while frontier:
            current = frontier.pop(0)
            for transition in normalized_transitions:
                if current not in transition["sources"]:
                    continue
                target_state = transition["target"]
                if target_state and target_state not in reachable_states:
                    reachable_states.add(target_state)
                    frontier.append(target_state)
        return reachable_states

    def validate_reachability(
        self,
        terminal_states: set[str],
        states_with_outgoing: set[str],
        reachable_states: set[str],
    ) -> None:
        for state_name in self.states:
            if state_name not in reachable_states:
                self.warnings.append(f"state '{state_name}' is unreachable from entry_state")
            if state_name in terminal_states and state_name in states_with_outgoing:
                self.warnings.append(f"terminal state '{state_name}' has outgoing transitions")
            if state_name not in terminal_states and state_name not in states_with_outgoing:
                self.warnings.append(f"non-terminal state '{state_name}' has no outgoing transitions")

    def build_report(self) -> dict[str, Any]:
        if not self.config:
            return self.load_missing_report()

        self.validate_entry_state()
        self.validate_retry_policy()
        known_agents = self.load_known_agent_names()
        known_tools = self.load_known_tool_names()
        terminal_states = self.validate_states(known_agents, known_tools)
        normalized_transitions, states_with_outgoing = self.load_normalized_transitions(known_tools)
        reachable_states = self.load_reachable_states(normalized_transitions)
        self.validate_reachability(terminal_states, states_with_outgoing, reachable_states)
        return {
            "name": self.workflow_name,
            "valid": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": {
                "state_count": len(self.states),
                "transition_count": len(self.transitions),
                "reachable_state_count": len(reachable_states),
                "terminal_state_count": len(terminal_states),
            },
        }


class BatchWorkflowValidationObject:
    def __init__(
        self,
        workflow_name: str,
        workflow_config: dict[str, Any] | None = None,
    ) -> None:
        self.workflow_name = workflow_name
        self.config = deepcopy(workflow_config if workflow_config is not None else BATCH_WORKFLOW_CONFIGS.get(workflow_name, {}))
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def load_missing_report(self) -> dict[str, Any]:
        return {
            "name": self.workflow_name,
            "valid": False,
            "errors": ["batch workflow config is missing"],
            "warnings": [],
            "stats": {"stage_count": 0},
        }

    def load_dispatcher_tool_name(self) -> str:
        dispatcher = dict(self.config.get("dispatcher") or {})
        return normalize_tool_name(str(dispatcher.get("tool_name") or ""))

    def load_stages(self) -> list[Any]:
        stages = self.config.get("stages") or []
        if not isinstance(stages, list) or not stages:
            self.errors.append("stages definition must contain at least one stage")
            return []
        return stages

    def validate_dispatcher(self) -> str:
        dispatcher_tool_name = self.load_dispatcher_tool_name()
        if not dispatcher_tool_name:
            self.errors.append("dispatcher.tool_name is required")
        elif not get_tool_config(dispatcher_tool_name):
            self.errors.append(f"dispatcher.tool_name '{dispatcher_tool_name}' is not defined in TOOL_CONFIGS")
        return dispatcher_tool_name

    def validate_stages(self, stages: list[Any]) -> None:
        stage_names: set[str] = set()
        for index, stage in enumerate(stages):
            stage_config = dict(stage or {})
            stage_name = str(stage_config.get("name") or "").strip()
            if not stage_name:
                self.errors.append(f"stage[{index}] is missing name")
                continue
            if stage_name in stage_names:
                self.errors.append(f"duplicate batch stage name '{stage_name}'")
            stage_names.add(stage_name)

            prompt = dict(stage_config.get("prompt") or {})
            agent_type = str(prompt.get("agent_type") or "").strip()
            task_name = str(prompt.get("task_name") or "").strip()
            if not agent_type or not task_name:
                self.errors.append(f"stage '{stage_name}' is missing prompt.agent_type or prompt.task_name")
            elif not get_specialized_system_prompt(agent_type, task_name):
                self.errors.append(f"stage '{stage_name}' references unknown specialized prompt '{agent_type}:{task_name}'")

            if "input" not in stage_config and "input_template" not in stage_config:
                self.errors.append(f"stage '{stage_name}' must define input or input_template")

            response_format = str(stage_config.get("response_format") or "json").strip()
            if response_format not in {"json", "text"}:
                self.errors.append(f"stage '{stage_name}' has unsupported response_format '{response_format}'")

    def validate_document_output(self) -> str:
        document_output = dict(self.config.get("document_output") or {})
        text_writer_tool = normalize_tool_name(str(document_output.get("text_writer_tool") or ""))
        if not text_writer_tool:
            self.errors.append("document_output.text_writer_tool is required")
        elif not get_tool_config(text_writer_tool):
            self.errors.append(f"document_output.text_writer_tool '{text_writer_tool}' is not defined in TOOL_CONFIGS")

        pdf_writer = str(document_output.get("pdf_writer") or "").strip()
        if pdf_writer and pdf_writer not in {"internal_text_pdf"}:
            self.errors.append(f"document_output.pdf_writer '{pdf_writer}' is not supported")
        return text_writer_tool

    def validate_dispatcher_record(self) -> None:
        dispatcher_record = dict(self.config.get("dispatcher_record") or {})
        if not isinstance(dispatcher_record.get("success_updates"), dict):
            self.errors.append("dispatcher_record.success_updates must be defined")
        if not isinstance(dispatcher_record.get("failure_updates"), dict):
            self.errors.append("dispatcher_record.failure_updates must be defined")

    def validate_filters(self) -> None:
        filters = dict(self.config.get("filters") or {})
        skip_basenames = filters.get("skip_basenames") or []
        if skip_basenames and not isinstance(skip_basenames, list):
            self.errors.append("filters.skip_basenames must be a list when provided")

    def build_report(self) -> dict[str, Any]:
        if not self.config:
            return self.load_missing_report()

        dispatcher_tool_name = self.validate_dispatcher()
        stages = self.load_stages()
        self.validate_stages(stages)
        text_writer_tool = self.validate_document_output()
        self.validate_dispatcher_record()
        self.validate_filters()
        return {
            "name": self.workflow_name,
            "valid": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": {
                "stage_count": len(stages),
                "has_dispatcher": bool(dispatcher_tool_name),
                "has_document_output": bool(text_writer_tool),
            },
        }


class WorkflowValidationService:
    def load_object_validation(
        self,
        workflow_name: str,
        workflow_config: dict[str, Any] | None = None,
    ) -> WorkflowValidationObject:
        return WorkflowValidationObject(workflow_name, workflow_config)

    def load_batch_object_validation(
        self,
        workflow_name: str,
        workflow_config: dict[str, Any] | None = None,
    ) -> BatchWorkflowValidationObject:
        return BatchWorkflowValidationObject(workflow_name, workflow_config)

    def validate_object_workflow(
        self,
        workflow_name: str,
        workflow_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.load_object_validation(workflow_name, workflow_config).build_report()

    def validate_batch_object_workflow(
        self,
        workflow_name: str,
        workflow_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.load_batch_object_validation(workflow_name, workflow_config).build_report()

    def validate_all_objects(self) -> dict[str, Any]:
        workflow_reports = [self.validate_object_workflow(name, config) for name, config in WORKFLOW_CONFIGS.items()]
        invalid_reports = [report for report in workflow_reports if not report.get("valid")]
        batch_workflow_reports = [self.validate_batch_object_workflow(name, config) for name, config in BATCH_WORKFLOW_CONFIGS.items()]
        invalid_batch_reports = [report for report in batch_workflow_reports if not report.get("valid")]
        map_errors: list[str] = []
        for agent_label, workflow_name in AGENT_WORKFLOW_MAP.items():
            if agent_label not in AGENT_MANIFESTS:
                map_errors.append(f"agent '{agent_label}' in AGENT_WORKFLOW_MAP is not defined in AGENT_MANIFESTS")
            if workflow_name not in WORKFLOW_CONFIGS:
                map_errors.append(f"agent '{agent_label}' references unknown workflow '{workflow_name}'")
        return {
            "valid": not invalid_reports and not invalid_batch_reports and not map_errors,
            "workflow_count": len(workflow_reports),
            "valid_count": len([report for report in workflow_reports if report.get("valid")]),
            "invalid_count": len(invalid_reports),
            "batch_workflow_count": len(batch_workflow_reports),
            "valid_batch_workflow_count": len([report for report in batch_workflow_reports if report.get("valid")]),
            "invalid_batch_workflow_count": len(invalid_batch_reports),
            "mapping_errors": map_errors,
            "workflows": workflow_reports,
            "batch_workflows": batch_workflow_reports,
        }


WORKFLOW_VALIDATION_SERVICE = WorkflowValidationService()


def validate_workflow_config(workflow_name: str, workflow_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return WORKFLOW_VALIDATION_SERVICE.validate_object_workflow(workflow_name, workflow_config)


def validate_batch_workflow_config(workflow_name: str, workflow_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return WORKFLOW_VALIDATION_SERVICE.validate_batch_object_workflow(workflow_name, workflow_config)


def validate_all_workflows() -> dict[str, Any]:
    return WORKFLOW_VALIDATION_SERVICE.validate_all_objects()


class AgentSystemActionRequestObject:
    def __init__(
        self,
        object_name: str,
        action_request: dict[str, Any] | None = None,
    ) -> None:
        request_config = dict(action_request or {})
        system_name = str(request_config.get("system_name") or object_name or "agent_system").strip() or "agent_system"
        system_slug = _normalize_config_object_token(str(request_config.get("system_slug") or system_name), fallback="agent_system")
        self.config = set_config_values(
            {
                "system_name": system_name,
                "system_slug": system_slug,
                "assistant_agent_name": "_primary_assistant",
                "planner_agent_name": f"_{system_slug}_planner",
                "worker_agent_name": f"_{system_slug}_worker",
                "planner_prompt_name": f"{system_slug}_planner",
                "worker_prompt_name": f"{system_slug}_worker",
                "planner_workflow_name": f"{system_slug}_planner_router",
                "builder_workflow_name": f"{system_slug}_builder_leaf",
                "primary_to_planner_schema_name": f"primary_to_{system_slug}_planner",
                "planner_to_builder_schema_name": f"{system_slug}_planner_to_builder",
                "action_request_schema_name": f"{system_slug}_builder_request",
                "action_tool_name": "build_agent_system_configs",
                "route_prefix": "/create agents",
                "route_name": f"{system_slug}_create_agents_command",
                "planner_model": "gpt-4o",
                "worker_model": "gpt-4o-mini",
                "agent_specs": [
                    {
                        "name": "planner",
                        "agent_name": f"_{system_slug}_planner",
                        "role": "planner_router",
                        "responsibility": "Interactively clarify the requested agent system and prepare a structured build brief.",
                        "tools": ["route_to_agent"],
                    },
                    {
                        "name": "worker",
                        "agent_name": f"_{system_slug}_worker",
                        "role": "worker",
                        "responsibility": "Materialize persisted prompt, runtime, handoff, builder workflow, and route config bundles.",
                        "tools": ["build_agent_system_configs", "@doc_rw"],
                    },
                ],
                "workflow_specs": [
                    {
                        "name": f"{system_slug}_planner_router",
                        "kind": "router",
                        "entry_state": "planner_ready",
                        "owner_agent": f"_{system_slug}_planner",
                    },
                    {
                        "name": f"{system_slug}_builder_leaf",
                        "kind": "leaf",
                        "entry_state": "builder_active",
                        "owner_agent": f"_{system_slug}_worker",
                    },
                ],
                "integration_targets": {
                    "assistant_agent_name": "_primary_assistant",
                    "route_prefix": "/create agents",
                    "persisted_config_target": f"generated_agent_system_configs/{system_slug}_persisted_config.py",
                },
                "planning_schema": {
                    "required_steps": [
                        "capture_goal",
                        "identify_agents",
                        "define_workflows",
                        "confirm_tools",
                        "handoff_builder",
                    ],
                    "required_sections": [
                        "agent_specs",
                        "workflow_specs",
                        "integration_targets",
                    ],
                    "required_agent_fields": [
                        "name",
                        "agent_name",
                        "role",
                        "responsibility",
                        "tools",
                    ],
                    "required_workflow_fields": [
                        "name",
                        "kind",
                        "entry_state",
                        "owner_agent",
                    ],
                    "required_integration_fields": [
                        "assistant_agent_name",
                        "route_prefix",
                        "persisted_config_target",
                    ],
                    "interactive": True,
                    "builder_tool": "build_agent_system_configs",
                },
            },
            request_config,
        )

    def load_system_name(self) -> str:
        return str(self.config.get("system_name") or "agent_system").strip() or "agent_system"

    def load_system_slug(self) -> str:
        return _normalize_config_object_token(str(self.config.get("system_slug") or self.load_system_name()), fallback="agent_system")

    def load_assistant_agent_name(self) -> str:
        return normalize_agent_label(str(self.config.get("assistant_agent_name") or "_primary_assistant"))

    def load_agent_name(self, object_name: str) -> str:
        normalized_object_name = str(object_name or "").strip()
        default_values = {
            "planner_agent_name": f"_{self.load_system_slug()}_planner",
            "worker_agent_name": f"_{self.load_system_slug()}_worker",
        }
        default_value = default_values.get(normalized_object_name, "")
        return normalize_agent_label(str(self.config.get(normalized_object_name) or default_value))

    def load_planner_agent_name(self, object_name: str = "planner_agent_name") -> str:
        return self.load_agent_name(object_name)

    def load_worker_agent_name(self, object_name: str = "worker_agent_name") -> str:
        return self.load_agent_name(object_name)

    def load_planner_prompt_name(self) -> str:
        default_value = f"{self.load_system_slug()}_planner"
        return _normalize_config_object_token(str(self.config.get("planner_prompt_name") or default_value), fallback=default_value)

    def load_worker_prompt_name(self) -> str:
        default_value = f"{self.load_system_slug()}_worker"
        return _normalize_config_object_token(str(self.config.get("worker_prompt_name") or default_value), fallback=default_value)

    def load_planner_workflow_name(self) -> str:
        default_value = f"{self.load_system_slug()}_planner_router"
        return _normalize_config_object_token(str(self.config.get("planner_workflow_name") or default_value), fallback=default_value)

    def load_builder_workflow_name(self) -> str:
        default_value = f"{self.load_system_slug()}_builder_leaf"
        return _normalize_config_object_token(str(self.config.get("builder_workflow_name") or default_value), fallback=default_value)

    def load_primary_to_planner_schema_name(self) -> str:
        default_value = f"primary_to_{self.load_system_slug()}_planner"
        return _normalize_config_object_token(str(self.config.get("primary_to_planner_schema_name") or default_value), fallback=default_value)

    def load_planner_to_builder_schema_name(self) -> str:
        default_value = f"{self.load_system_slug()}_planner_to_builder"
        return _normalize_config_object_token(str(self.config.get("planner_to_builder_schema_name") or default_value), fallback=default_value)

    def load_action_request_schema_name(self) -> str:
        default_value = f"{self.load_system_slug()}_builder_request"
        return _normalize_config_object_token(str(self.config.get("action_request_schema_name") or default_value), fallback=default_value)

    def load_action_tool_name(self) -> str:
        return normalize_tool_name(str(self.config.get("action_tool_name") or "build_agent_system_configs"))

    def load_route_prefix(self) -> str:
        return str(self.config.get("route_prefix") or "/create agents").strip() or "/create agents"

    def load_route_name(self) -> str:
        default_value = f"{self.load_system_slug()}_create_agents_command"
        return _normalize_config_object_token(str(self.config.get("route_name") or default_value), fallback=default_value)

    def load_planner_model(self) -> str:
        return str(self.config.get("planner_model") or "gpt-4o").strip() or "gpt-4o"

    def load_worker_model(self) -> str:
        return str(self.config.get("worker_model") or "gpt-4o-mini").strip() or "gpt-4o-mini"

    def load_planning_schema(self) -> dict[str, Any]:
        planning_schema = self.config.get("planning_schema") or {}
        return deepcopy(planning_schema if isinstance(planning_schema, dict) else {})

    def load_agent_specs(self) -> list[dict[str, Any]]:
        agent_specs = self.config.get("agent_specs") or []
        return [dict(spec or {}) for spec in agent_specs if isinstance(spec, dict)]

    def load_workflow_specs(self) -> list[dict[str, Any]]:
        workflow_specs = self.config.get("workflow_specs") or []
        return [dict(spec or {}) for spec in workflow_specs if isinstance(spec, dict)]

    def load_integration_targets(self) -> dict[str, Any]:
        integration_targets = self.config.get("integration_targets") or {}
        return deepcopy(integration_targets if isinstance(integration_targets, dict) else {})

    def load_persisted_config_target(self) -> str:
        integration_targets = self.load_integration_targets()
        default_target = f"generated_agent_system_configs/{self.load_system_slug()}_persisted_config.py"
        return str(integration_targets.get("persisted_config_target") or default_target).strip() or default_target

    def build_validation_report(self) -> dict[str, Any]:
        planning_schema = self.load_planning_schema()
        errors: list[str] = []

        required_steps = [str(value).strip() for value in (planning_schema.get("required_steps") or []) if str(value).strip()]
        if not required_steps:
            errors.append("planning_schema.required_steps must contain at least one step")

        required_sections = [str(value).strip() for value in (planning_schema.get("required_sections") or []) if str(value).strip()]
        for section_name in required_sections:
            section_value = self.config.get(section_name)
            if section_name in {"agent_specs", "workflow_specs"}:
                if not isinstance(section_value, list) or not section_value:
                    errors.append(f"{section_name} must contain at least one object")
            elif section_name == "integration_targets":
                if not isinstance(section_value, dict) or not section_value:
                    errors.append("integration_targets must be a non-empty object")
            elif section_value in (None, "", [], {}):
                errors.append(f"{section_name} is required by planning_schema.required_sections")

        required_agent_fields = [str(value).strip() for value in (planning_schema.get("required_agent_fields") or []) if str(value).strip()]
        for index, agent_spec in enumerate(self.load_agent_specs()):
            for field_name in required_agent_fields:
                field_value = agent_spec.get(field_name)
                if field_value in (None, "", [], {}):
                    errors.append(f"agent_specs[{index}].{field_name} is required")

        required_workflow_fields = [str(value).strip() for value in (planning_schema.get("required_workflow_fields") or []) if str(value).strip()]
        for index, workflow_spec in enumerate(self.load_workflow_specs()):
            for field_name in required_workflow_fields:
                field_value = workflow_spec.get(field_name)
                if field_value in (None, "", [], {}):
                    errors.append(f"workflow_specs[{index}].{field_name} is required")

        integration_targets = self.load_integration_targets()
        required_integration_fields = [
            str(value).strip() for value in (planning_schema.get("required_integration_fields") or []) if str(value).strip()
        ]
        for field_name in required_integration_fields:
            field_value = integration_targets.get(field_name)
            if field_value in (None, "", [], {}):
                errors.append(f"integration_targets.{field_name} is required")

        return {
            "valid": not errors,
            "errors": errors,
            "required_steps": required_steps,
            "required_sections": required_sections,
        }

    def load_planner_canonical_name(self) -> str:
        return normalize_agent_name(self.load_planner_agent_name())

    def load_worker_canonical_name(self) -> str:
        return normalize_agent_name(self.load_worker_agent_name())

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "system_name": self.load_system_name(),
            "system_slug": self.load_system_slug(),
            "assistant_agent_name": self.load_assistant_agent_name(),
            "planner_agent_name": self.load_planner_agent_name(),
            "worker_agent_name": self.load_worker_agent_name(),
            "planner_prompt_name": self.load_planner_prompt_name(),
            "worker_prompt_name": self.load_worker_prompt_name(),
            "planner_workflow_name": self.load_planner_workflow_name(),
            "builder_workflow_name": self.load_builder_workflow_name(),
            "primary_to_planner_schema_name": self.load_primary_to_planner_schema_name(),
            "planner_to_builder_schema_name": self.load_planner_to_builder_schema_name(),
            "action_request_schema_name": self.load_action_request_schema_name(),
            "action_tool_name": self.load_action_tool_name(),
            "route_prefix": self.load_route_prefix(),
            "route_name": self.load_route_name(),
            "planner_model": self.load_planner_model(),
            "worker_model": self.load_worker_model(),
            "planning_schema": self.load_planning_schema(),
            "agent_specs": self.load_agent_specs(),
            "workflow_specs": self.load_workflow_specs(),
            "integration_targets": self.load_integration_targets(),
        }


class AgentSystemBasicConfigService:
    def load_action_request(
        self,
        object_name: str,
        action_request: dict[str, Any] | None = None,
    ) -> AgentSystemActionRequestObject:
        return AgentSystemActionRequestObject(object_name, action_request)

    def validate_action_request(self, action_request: AgentSystemActionRequestObject) -> dict[str, Any]:
        report = action_request.build_validation_report()
        if not report.get("valid"):
            raise ValueError("invalid agent system action request: " + "; ".join(report.get("errors") or []))
        return report

    def build_persisted_config_updates(self, config_bundle: dict[str, Any]) -> dict[str, Any]:
        return {
            "SYSTEM_PROMPT": deepcopy(config_bundle.get("prompt_configs") or {}),
            "AGENT_RUNTIME_CONFIG": deepcopy(config_bundle.get("agent_runtime_configs") or {}),
            "AGENT_MANIFEST_OVERRIDES": deepcopy(config_bundle.get("agent_manifest_override_configs") or {}),
            "HANDOFF_SCHEMA_CONFIGS": deepcopy(config_bundle.get("handoff_schema_configs") or {}),
            "ACTION_REQUEST_SCHEMA_CONFIGS": deepcopy(config_bundle.get("action_request_schema_configs") or {}),
            "TOOL_CONFIGS": list((config_bundle.get("tool_configs") or {}).values()),
            "WORKFLOW_CONFIGS": deepcopy(config_bundle.get("workflow_configs") or {}),
            "FORCED_ROUTE_CONFIGS": deepcopy(config_bundle.get("forced_route_configs") or {}),
            "PRIMARY_ASSISTANT_MANIFEST_OVERRIDE": deepcopy((config_bundle.get("assistant_integration") or {}).get("manifest_override") or {}),
            "PRIMARY_ASSISTANT_WORKFLOW_CONFIG": deepcopy((config_bundle.get("assistant_integration") or {}).get("workflow_config") or {}),
        }

    def render_persisted_config_module(
        self,
        action_request: AgentSystemActionRequestObject,
        persisted_updates: dict[str, Any],
    ) -> dict[str, Any]:
        variable_map = {
            "SYSTEM_PROMPT": "SYSTEM_PROMPT_UPDATES",
            "AGENT_RUNTIME_CONFIG": "AGENT_RUNTIME_CONFIG_UPDATES",
            "AGENT_MANIFEST_OVERRIDES": "AGENT_MANIFEST_OVERRIDE_UPDATES",
            "HANDOFF_SCHEMA_CONFIGS": "HANDOFF_SCHEMA_CONFIG_UPDATES",
            "ACTION_REQUEST_SCHEMA_CONFIGS": "ACTION_REQUEST_SCHEMA_CONFIG_UPDATES",
            "TOOL_CONFIGS": "TOOL_CONFIG_UPDATES",
            "WORKFLOW_CONFIGS": "WORKFLOW_CONFIG_UPDATES",
            "FORCED_ROUTE_CONFIGS": "FORCED_ROUTE_CONFIG_UPDATES",
            "PRIMARY_ASSISTANT_MANIFEST_OVERRIDE": "PRIMARY_ASSISTANT_MANIFEST_OVERRIDE_UPDATE",
            "PRIMARY_ASSISTANT_WORKFLOW_CONFIG": "PRIMARY_ASSISTANT_WORKFLOW_CONFIG_UPDATE",
        }
        section_lines = [
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
        ]
        for section_name, variable_name in variable_map.items():
            value = persisted_updates.get(section_name)
            annotation = "dict[str, Any]" if not isinstance(value, list) else "list[dict[str, Any]]"
            section_lines.append(f"{variable_name}: {annotation} = {_python_literal_block(value)}")
            section_lines.append("")
        section_lines.append("PERSISTED_CONFIG_UPDATES: dict[str, Any] = {")
        for section_name, variable_name in variable_map.items():
            section_lines.append(f"    {section_name!r}: {variable_name},")
        section_lines.append("}")
        content = "\n".join(section_lines).rstrip() + "\n"
        return {
            "relative_path": action_request.load_persisted_config_target(),
            "content": content,
        }

    def build_assistant_workflow_config(self, action_request: AgentSystemActionRequestObject) -> dict[str, Any]:
        planner_agent_name = action_request.load_planner_agent_name()
        workflow_config = create_workflow_config("primary_assistant_router")
        states = dict(workflow_config.get("states") or {})
        transitions = list(workflow_config.get("transitions") or [])

        states.setdefault(
            "planner_delegated",
            {
                "actor": {"kind": "tool", "name": "route_to_agent"},
                "terminal": False,
            },
        )

        if not any(
            str(transition.get("to") or "") == "planner_delegated"
            for transition in transitions
        ):
            transitions.append(
                {
                    "from": "assistant_ready",
                    "on": {
                        "kind": "tool",
                        "name": "route_to_agent",
                        "conditions": {"target_agent": planner_agent_name},
                    },
                    "to": "planner_delegated",
                }
            )

        complete_transition = next(
            (
                transition
                for transition in transitions
                if str(transition.get("to") or "") == "workflow_complete"
                and dict(transition.get("on") or {}).get("kind") == "state"
                and dict(transition.get("on") or {}).get("name") == "routed_agent_complete"
            ),
            None,
        )
        if isinstance(complete_transition, dict):
            from_states = complete_transition.get("from") or []
            if isinstance(from_states, list) and "planner_delegated" not in from_states:
                complete_transition["from"] = [*from_states, "planner_delegated"]
            conditions = dict(dict(complete_transition.get("on") or {}).get("conditions") or {})
            target_condition = conditions.get("target_agent") or {}
            target_agents = list(dict(target_condition).get("in") or []) if isinstance(target_condition, dict) else []
            if planner_agent_name not in target_agents:
                target_agents.append(planner_agent_name)
            conditions["target_agent"] = {"in": target_agents}
            complete_transition["on"] = set_config_value(dict(complete_transition.get("on") or {}), "conditions", conditions)

        failure_transition = next(
            (
                transition
                for transition in transitions
                if str(transition.get("to") or "") == "assistant_retry_pending"
            ),
            None,
        )
        if isinstance(failure_transition, dict):
            from_states = failure_transition.get("from") or []
            if isinstance(from_states, list) and "planner_delegated" not in from_states:
                failure_transition["from"] = [*from_states, "planner_delegated"]
            conditions = dict(dict(failure_transition.get("on") or {}).get("conditions") or {})
            any_conditions = list(conditions.get("any") or [])
            target_condition = next(
                (
                    condition
                    for condition in any_conditions
                    if isinstance(condition, dict) and "target_agent" in condition
                ),
                None,
            )
            if not isinstance(target_condition, dict):
                target_condition = {"target_agent": {"in": [planner_agent_name]}}
                any_conditions.append(target_condition)
            target_agents = list(dict(target_condition.get("target_agent") or {}).get("in") or [])
            if planner_agent_name not in target_agents:
                target_agents.append(planner_agent_name)
            target_condition["target_agent"] = {"in": target_agents}
            conditions["any"] = any_conditions
            failure_transition["on"] = set_config_value(dict(failure_transition.get("on") or {}), "conditions", conditions)

        workflow_config["states"] = states
        workflow_config["transitions"] = transitions
        return workflow_config

    def create_object_config(
        self,
        object_name: str,
        action_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = self.load_action_request(object_name, action_request)
        validation_report = self.validate_action_request(request)
        planner_agent_name = request.load_planner_agent_name()
        worker_agent_name = request.load_worker_agent_name()
        planner_workflow_name = request.load_planner_workflow_name()
        builder_workflow_name = request.load_builder_workflow_name()
        planner_prompt_name = request.load_planner_prompt_name()
        worker_prompt_name = request.load_worker_prompt_name()
        primary_to_planner_schema_name = request.load_primary_to_planner_schema_name()
        planner_to_builder_schema_name = request.load_planner_to_builder_schema_name()
        action_request_schema_name = request.load_action_request_schema_name()
        action_tool_name = request.load_action_tool_name()
        route_prefix = request.load_route_prefix()
        planning_schema = request.load_planning_schema()

        planner_prompt = create_prompt_config(
            planner_prompt_name,
            {
                "prompt": (
                    f"=== Agent: {planner_prompt_name} ===\n"
                    "Description: Interactive planner for building agentic systems from a user request.\n"
                    "Goal: Clarify the target system, produce a schema-aligned plan, then delegate the concrete config generation to the builder worker.\n\n"
                    "Rules:\n"
                    "- Ask focused follow-up questions until the requested agent system is specific enough to implement.\n"
                    "- Follow the planning_schema strictly and keep the plan structured.\n"
                    f"- Delegate config bundle creation only to {worker_agent_name}.\n"
                    f"- When the user already provided enough detail, hand off to {worker_agent_name} immediately with a structured brief."
                ),
                "task.mode": "agent_system_planner",
                "task.route_prefix": route_prefix,
                "task.planning_schema": planning_schema,
                "output_schema.plan.required": planning_schema.get("required_steps") or [],
                "output_schema.plan.worker_agent": worker_agent_name,
            },
        )
        worker_prompt = create_prompt_config(
            worker_prompt_name,
            {
                "prompt": (
                    f"=== Agent: {worker_prompt_name} ===\n"
                    "Description: Worker agent that materializes planner-approved agent/workflow configuration bundles.\n"
                    "Goal: Convert the planning brief into concrete prompt, runtime, manifest, workflow, handoff, and forced-route configs.\n\n"
                    "Rules:\n"
                    f"- Use {action_tool_name} to generate the canonical config bundle.\n"
                    "- Keep names generic and reusable.\n"
                    "- Preserve Domain -> Object -> Function structure in the generated configuration.\n"
                    "- Return the produced config bundle and call out remaining manual integration steps when needed."
                ),
                "task.mode": "agent_system_worker",
                "task.action_tool": action_tool_name,
                "task.action_request_schema": action_request_schema_name,
                "output_schema.bundle_sections": [
                    "prompt_configs",
                    "agent_runtime_configs",
                    "agent_manifest_override_configs",
                    "handoff_schema_configs",
                    "action_request_schema_configs",
                    "tool_configs",
                    "workflow_configs",
                    "forced_route_configs",
                    "assistant_integration",
                ],
            },
        )

        planner_runtime = create_agent_runtime_config(
            planner_agent_name,
            {
                "canonical_name": request.load_planner_canonical_name(),
                "model": request.load_planner_model(),
                "tools": ["route_to_agent"],
                "defaults": {},
                "workflow.definition": planner_workflow_name,
            },
        )
        worker_runtime = create_agent_runtime_config(
            worker_agent_name,
            {
                "canonical_name": request.load_worker_canonical_name(),
                "model": request.load_worker_model(),
                "tools": [action_tool_name, "@doc_rw"],
                "defaults": {},
                "workflow.definition": builder_workflow_name,
            },
        )

        planner_manifest_override = create_agent_manifest_override_config(
            planner_agent_name,
            {
                "role": "planner_router",
                "skill_profile": "conversation_router",
                "instance_policy": "session_scoped",
                "routing_policy.mode": "planner_router",
                "routing_policy.can_route": True,
                "handoff_policy.allowed_sources": [request.load_assistant_agent_name()],
                "handoff_policy.allowed_targets": [worker_agent_name],
                f"handoff_policy.source_policies.{request.load_assistant_agent_name()}.accepted_protocols": ["message_text", "agent_handoff_v1"],
                f"handoff_policy.source_policies.{request.load_assistant_agent_name()}.handoff_schema": primary_to_planner_schema_name,
                f"handoff_policy.target_policies.{worker_agent_name}.default_protocol": "agent_handoff_v1",
                f"handoff_policy.target_policies.{worker_agent_name}.accepted_protocols": ["agent_handoff_v1"],
                f"handoff_policy.target_policies.{worker_agent_name}.handoff_schema": planner_to_builder_schema_name,
            },
        )
        worker_manifest_override = create_agent_manifest_override_config(
            worker_agent_name,
            {
                "role": "worker",
                "skill_profile": "structured_writer",
                f"handoff_policy.allowed_sources": [planner_agent_name],
                f"handoff_policy.source_policies.{planner_agent_name}.accepted_protocols": ["agent_handoff_v1"],
                f"handoff_policy.source_policies.{planner_agent_name}.handoff_schema": planner_to_builder_schema_name,
            },
        )
        assistant_manifest_override = create_agent_manifest_override_config(
            request.load_assistant_agent_name(),
            {
                "handoff_policy.allowed_targets": list(
                    {
                        *list((get_agent_manifest(request.load_assistant_agent_name()).get("handoff_policy") or {}).get("allowed_targets") or []),
                        planner_agent_name,
                    }
                ),
                f"handoff_policy.target_policies.{planner_agent_name}.default_protocol": "agent_handoff_v1",
                f"handoff_policy.target_policies.{planner_agent_name}.accepted_protocols": ["message_text", "agent_handoff_v1"],
                f"handoff_policy.target_policies.{planner_agent_name}.handoff_schema": primary_to_planner_schema_name,
            },
        )

        primary_to_planner_schema = create_handoff_schema_config(
            primary_to_planner_schema_name,
            {
                "protocol": "agent_handoff_v1",
                "description": "Primary assistant brief for the agent-system planner.",
                "required_payload_any": ["output", "generated", "msg"],
                "preferred_payload_paths": ["output", "generated", "msg"],
                "workflow_name": planner_workflow_name,
                "instructions": [
                    "Treat the handoff payload as the planner brief for the requested agent system.",
                    "Clarify missing system requirements interactively before delegating the build step.",
                ],
            },
        )
        planner_to_builder_schema = create_handoff_schema_config(
            planner_to_builder_schema_name,
            {
                "protocol": "agent_handoff_v1",
                "description": "Planner brief for the builder worker that materializes config bundles.",
                "required_payload_any": ["output", "generated", "msg"],
                "preferred_payload_paths": ["output", "generated", "msg"],
                "workflow_name": builder_workflow_name,
                "instructions": [
                    "Treat the handoff payload as the approved build brief.",
                    f"Use the {action_tool_name} tool to produce the canonical config bundle.",
                ],
            },
        )
        action_request_schema = create_action_request_schema_config(
            action_request_schema_name,
            {
                "description": "Builder request for creating a basic planner/builder agent system configuration bundle.",
                "actions": [action_tool_name, "create_agents_basic_config", "create_agent_system"],
                "required_paths": ["action", "system_name"],
                "recommended_paths": [
                    "assistant_agent_name",
                    "planner_agent_name",
                    "worker_agent_name",
                    "route_prefix",
                ],
            },
        )
        action_tool_config = create_tool_config(action_tool_name)

        planner_workflow = create_workflow_config(
            planner_workflow_name,
            {
                "description": "Planner workflow that either continues clarification or delegates config generation to the builder worker.",
                "entry_state": "planner_ready",
                "states.planner_ready.actor.kind": "agent",
                f"states.planner_ready.actor.name": planner_agent_name,
                "states.planner_ready.terminal": False,
                "states.builder_delegated.actor.kind": "tool",
                "states.builder_delegated.actor.name": "route_to_agent",
                "states.builder_delegated.terminal": False,
                "states.planner_retry_pending.actor.kind": "state",
                "states.planner_retry_pending.actor.name": "retry_pending",
                "states.planner_retry_pending.terminal": False,
                "states.planner_failed.actor.kind": "state",
                "states.planner_failed.actor.name": "workflow_failed",
                "states.planner_failed.terminal": True,
                "states.workflow_complete.actor.kind": "state",
                "states.workflow_complete.actor.name": "workflow_complete",
                "states.workflow_complete.terminal": True,
                "transitions": [
                    {
                        "from": "planner_ready",
                        "on": {
                            "kind": "tool",
                            "name": "route_to_agent",
                            "conditions": {"target_agent": worker_agent_name},
                        },
                        "to": "builder_delegated",
                    },
                    {
                        "from": "builder_delegated",
                        "on": {
                            "kind": "state",
                            "name": "routed_agent_complete",
                            "conditions": {"target_agent": worker_agent_name},
                        },
                        "to": "workflow_complete",
                    },
                    {
                        "from": ["planner_ready", "builder_delegated"],
                        "on": {
                            "kind": "state",
                            "name": ["model_failed", "routed_agent_failed"],
                            "conditions": {
                                "any": [
                                    {"error": {"exists": True}},
                                    {"result": {"exists": True}},
                                    {"target_agent": {"in": [worker_agent_name]}},
                                ]
                            },
                        },
                        "to": "planner_retry_pending",
                    },
                    {
                        "from": "planner_retry_pending",
                        "on": {"kind": "state", "name": "retry_requested"},
                        "to": "planner_ready",
                    },
                    {
                        "from": "planner_retry_pending",
                        "on": {"kind": "state", "name": "retry_exhausted"},
                        "to": "planner_failed",
                    },
                ],
            },
        )
        builder_workflow = create_workflow_config(
            builder_workflow_name,
            {
                "description": "Leaf workflow for the deterministic builder worker.",
                "entry_state": "builder_active",
                "states.builder_active.actor.kind": "agent",
                f"states.builder_active.actor.name": worker_agent_name,
                "states.builder_active.terminal": False,
                "states.builder_complete.actor.kind": "state",
                "states.builder_complete.actor.name": "workflow_complete",
                "states.builder_complete.terminal": True,
                "states.builder_failed.actor.kind": "state",
                "states.builder_failed.actor.name": "workflow_failed",
                "states.builder_failed.terminal": True,
                "transitions": [
                    {
                        "from": "builder_active",
                        "on": {"kind": "state", "name": "followup_complete"},
                        "to": "builder_complete",
                    },
                    {
                        "from": "builder_active",
                        "on": {"kind": "state", "name": ["model_failed", "tool_failed"]},
                        "to": "builder_failed",
                    },
                ],
            },
        )

        forced_route_configs = {
            request.load_assistant_agent_name(): [
                {
                    "name": request.load_route_name(),
                    "trigger": {
                        "type": "text_prefix",
                        "prefix": route_prefix,
                        "ignore_case": True,
                    },
                    "route": {
                        "target_agent": planner_agent_name,
                        "user_question": "__trigger_remainder__",
                    },
                }
            ]
        }

        config_bundle = {
            "system_name": request.load_system_name(),
            "request": request.to_config_dict(),
            "validation": validation_report,
            "prompt_configs": {
                planner_prompt_name: planner_prompt,
                worker_prompt_name: worker_prompt,
            },
            "agent_runtime_configs": {
                planner_agent_name: planner_runtime,
                worker_agent_name: worker_runtime,
            },
            "agent_manifest_override_configs": {
                planner_agent_name: planner_manifest_override,
                worker_agent_name: worker_manifest_override,
            },
            "handoff_schema_configs": {
                primary_to_planner_schema_name: primary_to_planner_schema,
                planner_to_builder_schema_name: planner_to_builder_schema,
            },
            "action_request_schema_configs": {
                action_request_schema_name: action_request_schema,
            },
            "tool_configs": {
                action_tool_name: action_tool_config,
            },
            "workflow_configs": {
                planner_workflow_name: planner_workflow,
_workflow_name: builder_workflow,
            },
            "forced_route_configs": forced_route_configs,
            "assistant_integration": {
                "manifest_override": assistant_manifest_override,
                "workflow_config": self.build_assistant_workflow_config(request),
            },
        }
        persisted_updates = self.build_persisted_config_updates(config_bundle)
        config_bundle["persisted_config_updates"] = persisted_updates
        config_bundle["persisted_module"] = self.render_persisted_config_module(request, persisted_updates)
        return config_bundle


AGENT_SYSTEM_BASIC_CONFIG_SERVICE = AgentSystemBasicConfigService()


AgentSystemBuilderRequestObject = AgentSystemActionRequestObject


def create_agent_system_basic_config(system_name: str, action_request: dict[str, Any] | None = None) -> dict[str, Any]:
    return AGENT_SYSTEM_BASIC_CONFIG_SERVICE.create_object_config(system_name, action_request)


def create_agent_system_persisted_config_module(system_name: str, action_request: dict[str, Any] | None = None) -> dict[str, Any]:
    config_bundle = AGENT_SYSTEM_BASIC_CONFIG_SERVICE.create_object_config(system_name, action_request)
    return deepcopy(config_bundle.get("persisted_module") or {})


def validate_agent_manifest(agent_name: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    agent_label = normalize_agent_label(agent_name)
    config = deepcopy(manifest if manifest is not None else AGENT_MANIFESTS.get(agent_label, {}))
    errors: list[str] = []
    warnings: list[str] = []

    if not config:
        return {
            "name": agent_label,
            "valid": False,
            "errors": ["agent manifest is missing"],
            "warnings": [],
        }

    role_name = str(config.get("role") or "")
    if role_name not in AGENT_ROLE_CONFIGS:
        errors.append(f"role '{role_name}' is not defined in AGENT_ROLE_CONFIGS")

    skill_profile_name = str(config.get("skill_profile") or "")
    if skill_profile_name and skill_profile_name not in AGENT_SKILL_PROFILES:
        errors.append(f"skill_profile '{skill_profile_name}' is not defined in AGENT_SKILL_PROFILES")

    prompt_config_name = str(config.get("prompt_config_name") or "")
    if prompt_config_name and prompt_config_name not in SYSTEM_PROMPT:
        errors.append(f"prompt_config_name '{prompt_config_name}' is not defined in SYSTEM_PROMPT")

    workflow_name = str(config.get("workflow_name") or "")
    if workflow_name and workflow_name not in WORKFLOW_CONFIGS:
        errors.append(f"workflow_name '{workflow_name}' is not defined in WORKFLOW_CONFIGS")

    instance_policy = str(config.get("instance_policy") or "ephemeral")
    if instance_policy not in ALLOWED_INSTANCE_POLICIES:
        allowed = ", ".join(sorted(ALLOWED_INSTANCE_POLICIES))
        errors.append(f"instance_policy '{instance_policy}' must be one of: {allowed}")

    routing_policy = config.get("routing_policy") or {}
    can_route = bool(routing_policy.get("can_route"))
    direct_tools = {normalize_tool_name(name) for name in (config.get("direct_tools") or [])}
    if can_route and "route_to_agent" not in direct_tools:
        warnings.append("routing_policy.can_route is true but route_to_agent is not in direct_tools")
    if not can_route and "route_to_agent" in direct_tools:
        warnings.append("route_to_agent is still exposed even though routing_policy.can_route is false")

    for fragment_name in config.get("prompt_fragments") or []:
        if fragment_name not in PROMPT_FRAGMENT_CONFIGS:
            errors.append(f"prompt fragment '{fragment_name}' is not defined in PROMPT_FRAGMENT_CONFIGS")

    history_policy = config.get("history_policy") or {}
    for key in ("followup_history_depth", "routed_history_depth"):
        value = history_policy.get(key)
        if value is None:
            continue
        try:
            if int(value) < 0:
                errors.append(f"history_policy.{key} must be >= 0")
        except Exception:
            errors.append(f"history_policy.{key} must be an integer")

    handoff_policy = config.get("handoff_policy") or {}
    default_protocol = str(handoff_policy.get("default_protocol") or "")
    if default_protocol and default_protocol not in HANDOFF_PROTOCOL_CONFIGS:
        errors.append(f"handoff_policy.default_protocol '{default_protocol}' is not defined in HANDOFF_PROTOCOL_CONFIGS")
    for key in ("accepted_protocols", "emitted_protocols"):
        values = handoff_policy.get(key) or []
        if not isinstance(values, list):
            errors.append(f"handoff_policy.{key} must be a list")
            continue
        for protocol_name in values:
            protocol_name = str(protocol_name or "")
            if protocol_name and protocol_name not in HANDOFF_PROTOCOL_CONFIGS:
                errors.append(f"handoff_policy.{key} references unknown protocol '{protocol_name}'")
    allowed_targets = handoff_policy.get("allowed_targets") or []
    if allowed_targets and not isinstance(allowed_targets, list):
        errors.append("handoff_policy.allowed_targets must be a list")
    elif isinstance(allowed_targets, list):
        known_agents = set(AGENT_RUNTIME_CONFIG.keys())
        for target in allowed_targets:
            normalized_target = normalize_agent_label(str(target or ""))
            if normalized_target and normalized_target not in known_agents:
                errors.append(f"handoff_policy.allowed_targets references unknown agent '{target}'")
    allowed_sources = handoff_policy.get("allowed_sources") or []
    if allowed_sources and not isinstance(allowed_sources, list):
        errors.append("handoff_policy.allowed_sources must be a list")
    elif isinstance(allowed_sources, list):
        known_agents = set(AGENT_RUNTIME_CONFIG.keys())
        for source in allowed_sources:
            normalized_source = normalize_agent_label(str(source or ""))
            if normalized_source and normalized_source not in known_agents:
                errors.append(f"handoff_policy.allowed_sources references unknown agent '{source}'")
    for key in ("target_policies", "source_policies"):
        policy_map = handoff_policy.get(key) or {}
        if policy_map and not isinstance(policy_map, dict):
            errors.append(f"handoff_policy.{key} must be an object")
            continue
        for peer_agent, policy_config in (policy_map.items() if isinstance(policy_map, dict) else []):
            normalized_peer = normalize_agent_label(str(peer_agent or ""))
            if normalized_peer not in AGENT_RUNTIME_CONFIG:
                errors.append(f"handoff_policy.{key} references unknown agent '{peer_agent}'")
            if not isinstance(policy_config, dict):
                errors.append(f"handoff_policy.{key}.{peer_agent} must be an object")
                continue
            for list_key in ("accepted_protocols", "emitted_protocols"):
                values = policy_config.get(list_key) or []
                if values and not isinstance(values, list):
                    errors.append(f"handoff_policy.{key}.{peer_agent}.{list_key} must be a list")
                    continue
                for protocol_name in values:
                    protocol_name = str(protocol_name or "")
                    if protocol_name and protocol_name not in HANDOFF_PROTOCOL_CONFIGS:
                        errors.append(f"handoff_policy.{key}.{peer_agent}.{list_key} references unknown protocol '{protocol_name}'")
            schema_name = str(policy_config.get("handoff_schema") or "")
            if schema_name and schema_name not in HANDOFF_SCHEMA_CONFIGS:
                errors.append(f"handoff_policy.{key}.{peer_agent}.handoff_schema '{schema_name}' is not defined in HANDOFF_SCHEMA_CONFIGS")

    return {
        "name": agent_label,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def validate_all_agent_manifests() -> dict[str, Any]:
    reports = [validate_agent_manifest(agent_label, manifest) for agent_label, manifest in AGENT_MANIFESTS.items()]
    invalid_reports = [report for report in reports if not report.get("valid")]
    return {
        "valid": not invalid_reports,
        "agent_count": len(reports),
        "valid_count": len(reports) - len(invalid_reports),
        "invalid_count": len(invalid_reports),
        "agents": reports,
    }


def validate_all_action_request_schemas() -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for schema_name, config in ACTION_REQUEST_SCHEMA_CONFIGS.items():
        errors: list[str] = []
        actions = config.get("actions") or []
        if not isinstance(actions, list) or not actions:
            errors.append("actions must be a non-empty list")
        required_paths = config.get("required_paths") or []
        if required_paths and not isinstance(required_paths, list):
            errors.append("required_paths must be a list")
        recommended_paths = config.get("recommended_paths") or []
        if recommended_paths and not isinstance(recommended_paths, list):
            errors.append("recommended_paths must be a list")
        reports.append(
            {
                "name": schema_name,
                "valid": not errors,
                "errors": errors,
                "warnings": [],
            }
        )
    invalid_reports = [report for report in reports if not report.get("valid")]
    return {
        "valid": not invalid_reports,
        "schema_count": len(reports),
        "valid_count": len(reports) - len(invalid_reports),
        "invalid_count": len(invalid_reports),
        "schemas": reports,
    }


def get_specialized_system_prompt(agent_type: str, task_name: str) -> str:
    canonical_name = _SPECIALIZED_AGENT_MAP.get((agent_type, task_name))
    if not canonical_name:
        return ""

    base_name = f"{agent_type}_agent"
    base_prompt = get_system_prompt(base_name)
    specialized_prompt = get_system_prompt(canonical_name)

    if base_prompt and specialized_prompt and base_prompt != specialized_prompt:
        return f"{base_prompt}\n\n{specialized_prompt}".strip()
    return specialized_prompt or base_prompt


_SYSTEM_PROMPT: dict[str, str] = {
    alias: get_system_prompt(canonical_name)
    for alias, canonical_name in _LEGACY_AGENT_NAME_MAP.items()
}


__all__ = [
    "AGENT_MANIFEST_OVERRIDES",
    "AGENT_MANIFESTS",
    "AGENT_ROLE_CONFIGS",
    "AGENT_RUNTIME_CONFIG",
    "AGENT_SKILL_PROFILES",
    "ACTION_REQUEST_SCHEMA_CONFIGS",
    "BATCH_WORKFLOW_CONFIGS",
    "FORCED_ROUTE_CONFIGS",
    "HANDOFF_PROTOCOL_CONFIGS",
    "HANDOFF_SCHEMA_CONFIGS",
    "PROMPT_FRAGMENT_CONFIGS",
    "SYSTEM_PROMPT",
    "TOOL_CONFIGS",
    "TOOL_GROUP_CONFIGS",
    "TOOL_NAME_ALIASES",
    "WORKFLOW_CONFIGS",
    "AGENT_WORKFLOW_MAP",
    "_SYSTEM_PROMPT",
    "build_agent_handoff",
    "create_action_request_schema_config",
    "create_agent_config",
    "create_agent_manifest_override_config",
    "create_agent_runtime_config",
    "create_agent_system_basic_config",
    "create_batch_workflow_config",
    "create_handoff_protocol_config",
    "create_handoff_schema_config",
    "create_prompt_config",
    "create_tool_config",
    "create_workflow_config",
    "get_agent_config",
    "get_agent_handoff_policy",
    "get_handoff_route_contract",
    "get_agent_manifest",
    "get_agent_manifests",
    "get_agent_workflow_config",
    "get_agents_registry_data",
    "get_action_request_schema_config",
    "get_action_request_schema_configs",
    "get_available_agent_labels",
    "get_available_tool_names",
    "get_batch_workflow_config",
    "get_batch_workflow_configs",
    "get_handoff_protocol_config",
    "get_handoff_protocol_configs",
    "get_handoff_schema_config",
    "get_handoff_schema_configs",
    "get_prompt_config",
    "get_specialized_system_prompt",
    "normalize_agent_label",
    "normalize_tool_name",
    "get_tool_config",
    "get_tool_configs",
    "get_tool_group_config",
    "get_tool_group_configs",
    "get_workflow_config",
    "get_workflow_configs",
    "get_system_prompt",
    "normalize_agent_name",
    "prepare_incoming_handoff",
    "resolve_forced_route",
    "set_config_value",
    "set_config_values",
    "validate_action_request",
    "validate_all_action_request_schemas",
    "validate_handoff_for_target",
    "validate_agent_manifest",
    "validate_all_agent_manifests",
    "validate_batch_workflow_config",
    "validate_workflow_config",
    "validate_all_workflows",
]
