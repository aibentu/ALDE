from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import uuid


RuntimePayload = dict[str, Any]


@dataclass(slots=True)
class RuntimeEventObject:
    event_type: str
    event_id: str
    timestamp: str
    payload: RuntimePayload = field(default_factory=dict)
    session_id: str | None = None
    correlation_id: str | None = None
    agent_label: str | None = None
    workflow_name: str | None = None

    def load_object(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeEventValidationService:
    _PAYLOAD_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
        "query": ("query_text", "tool_name"),
        "outcome": ("query_event_id", "tool_name", "success"),
        "tool_call": ("tool_name", "phase"),
        "agent_handoff": ("source_agent", "target_agent", "protocol"),
        "workflow_state": ("state_name", "state_phase"),
    }

    def validate_object(self, event_object: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(event_object, dict):
            return False, "event_object_must_be_dict"

        for required_field in ("event_type", "event_id", "timestamp", "payload"):
            if required_field not in event_object:
                return False, f"missing_required_field:{required_field}"

        event_type = str(event_object.get("event_type") or "").strip()
        if not event_type:
            return False, "event_type_must_be_non_empty"

        event_id = str(event_object.get("event_id") or "").strip()
        if not event_id:
            return False, "event_id_must_be_non_empty"

        timestamp = str(event_object.get("timestamp") or "").strip()
        if not timestamp:
            return False, "timestamp_must_be_non_empty"

        payload = event_object.get("payload")
        if not isinstance(payload, dict):
            return False, "payload_must_be_dict"

        required_payload_fields = self._PAYLOAD_REQUIRED_FIELDS.get(event_type, ())
        for required_payload_field in required_payload_fields:
            payload_value = payload.get(required_payload_field)
            if payload_value is None:
                return False, f"missing_payload_field:{required_payload_field}"
            if isinstance(payload_value, str) and not payload_value.strip():
                return False, f"empty_payload_field:{required_payload_field}"

        return True, ""


class RuntimeEventFactory:
    def __init__(self, validation_service: RuntimeEventValidationService | None = None) -> None:
        self.validation_service = validation_service or RuntimeEventValidationService()

    def load_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def load_event_id(self, event_type: str) -> str:
        normalized_event_type = str(event_type or "event").strip().lower().replace(" ", "_") or "event"
        return f"{normalized_event_type}:{uuid.uuid4()}"

    def create_object(
        self,
        *,
        event_type: str,
        payload: RuntimePayload,
        event_id: str | None = None,
        timestamp: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        agent_label: str | None = None,
        workflow_name: str | None = None,
    ) -> dict[str, Any]:
        runtime_event = RuntimeEventObject(
            event_type=str(event_type or "").strip(),
            event_id=str(event_id or self.load_event_id(event_type)).strip(),
            timestamp=str(timestamp or self.load_timestamp()).strip(),
            payload=dict(payload or {}),
            session_id=str(session_id).strip() if isinstance(session_id, str) and session_id.strip() else None,
            correlation_id=str(correlation_id).strip() if isinstance(correlation_id, str) and correlation_id.strip() else None,
            agent_label=str(agent_label).strip() if isinstance(agent_label, str) and agent_label.strip() else None,
            workflow_name=str(workflow_name).strip() if isinstance(workflow_name, str) and workflow_name.strip() else None,
        ).load_object()
        ok, reason = self.validation_service.validate_object(runtime_event)
        if not ok:
            raise ValueError(reason)
        return runtime_event

    def create_query_object(
        self,
        *,
        query_text: str,
        tool_name: str,
        event_id: str | None = None,
        timestamp: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        agent_label: str | None = None,
        workflow_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "query_text": str(query_text or ""),
            "tool_name": str(tool_name or ""),
            "metadata": dict(metadata or {}),
        }
        return self.create_object(
            event_type="query",
            payload=payload,
            event_id=event_id,
            timestamp=timestamp,
            session_id=session_id,
            correlation_id=correlation_id,
            agent_label=agent_label,
            workflow_name=workflow_name,
        )

    def create_outcome_object(
        self,
        *,
        query_event_id: str,
        tool_name: str,
        success: bool,
        event_id: str | None = None,
        timestamp: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        agent_label: str | None = None,
        workflow_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "query_event_id": str(query_event_id or ""),
            "tool_name": str(tool_name or ""),
            "success": bool(success),
            "metadata": dict(metadata or {}),
        }
        return self.create_object(
            event_type="outcome",
            payload=payload,
            event_id=event_id,
            timestamp=timestamp,
            session_id=session_id,
            correlation_id=correlation_id,
            agent_label=agent_label,
            workflow_name=workflow_name,
        )

    def create_tool_call_object(
        self,
        *,
        tool_name: str,
        phase: str,
        event_id: str | None = None,
        timestamp: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        agent_label: str | None = None,
        workflow_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "tool_name": str(tool_name or ""),
            "phase": str(phase or ""),
            "metadata": dict(metadata or {}),
        }
        return self.create_object(
            event_type="tool_call",
            payload=payload,
            event_id=event_id,
            timestamp=timestamp,
            session_id=session_id,
            correlation_id=correlation_id,
            agent_label=agent_label,
            workflow_name=workflow_name,
        )

    def create_agent_handoff_object(
        self,
        *,
        source_agent: str,
        target_agent: str,
        protocol: str,
        event_id: str | None = None,
        timestamp: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        agent_label: str | None = None,
        workflow_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "source_agent": str(source_agent or ""),
            "target_agent": str(target_agent or ""),
            "protocol": str(protocol or ""),
            "metadata": dict(metadata or {}),
        }
        return self.create_object(
            event_type="agent_handoff",
            payload=payload,
            event_id=event_id,
            timestamp=timestamp,
            session_id=session_id,
            correlation_id=correlation_id,
            agent_label=agent_label,
            workflow_name=workflow_name,
        )

    def create_workflow_state_object(
        self,
        *,
        state_name: str,
        state_phase: str,
        event_id: str | None = None,
        timestamp: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        agent_label: str | None = None,
        workflow_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "state_name": str(state_name or ""),
            "state_phase": str(state_phase or ""),
            "metadata": dict(metadata or {}),
        }
        return self.create_object(
            event_type="workflow_state",
            payload=payload,
            event_id=event_id,
            timestamp=timestamp,
            session_id=session_id,
            correlation_id=correlation_id,
            agent_label=agent_label,
            workflow_name=workflow_name,
        )


class RuntimeEventProjectionService:
    FAILURE_EVENT_NAMES = {"tool_failed", "model_failed", "routed_agent_failed", "workflow_failed"}
    COMPLETION_EVENT_NAMES = {"tool_complete", "followup_complete", "routed_agent_complete", "workflow_complete"}
    RETRY_EVENT_NAMES = {"retry_requested", "retry_exhausted"}

    def load_generated_root(self, base_dir: str | None = None) -> Path:
        return Path(base_dir) if base_dir else Path(__file__).resolve().parents[1] / "AppData" / "generated"

    def load_learning_events(self, base_dir: str | None = None) -> list[dict[str, Any]]:
        target_path = self.load_generated_root(base_dir) / "learning_events.jsonl"
        if not target_path.exists():
            return []

        entries: list[dict[str, Any]] = []
        with open(target_path, "r", encoding="utf-8") as event_file:
            for raw_line in event_file:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
        return entries

    def load_history_entries(self, history_entries: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if isinstance(history_entries, list):
            return [entry for entry in history_entries if isinstance(entry, dict)]

        try:
            try:
                from .chat_completion import ChatHistory  # type: ignore
            except ImportError as e:
                msg = str(e)
                if "attempted relative import" in msg or "no known parent package" in msg:
                    from chat_completion import ChatHistory  # type: ignore
                else:
                    raise
            loaded_history = getattr(ChatHistory(), "_history_", None)
            if isinstance(loaded_history, list):
                return [entry for entry in loaded_history if isinstance(entry, dict)]
        except Exception:
            return []
        return []

    def load_history_timestamp(self, history_entry: dict[str, Any]) -> str:
        timestamp = str(history_entry.get("time") or "").strip()
        if timestamp:
            return timestamp
        date_value = str(history_entry.get("date") or "").strip()
        if date_value:
            return date_value
        return datetime.now(timezone.utc).isoformat()

    def load_tool_name(self, tool_call: Any, default: str = "unknown_tool") -> str:
        if isinstance(tool_call, dict):
            function_object = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
            return str(function_object.get("name") or tool_call.get("name") or tool_call.get("type") or default).strip()
        return str(default)

    def load_effective_workflow_event(
        self,
        workflow_event: dict[str, Any],
        snapshot_event: dict[str, Any],
    ) -> dict[str, Any]:
        payload = workflow_event.get("payload") if isinstance(workflow_event.get("payload"), dict) else {}
        return {
            "kind": workflow_event.get("kind") or snapshot_event.get("kind"),
            "name": workflow_event.get("name") or snapshot_event.get("name"),
            "payload": dict(payload),
            "tool_name": payload.get("tool_name") or snapshot_event.get("tool_name"),
            "target_agent": payload.get("target_agent") or snapshot_event.get("target_agent"),
            "correlation_id": payload.get("correlation_id") or snapshot_event.get("correlation_id"),
            "action": payload.get("action") or snapshot_event.get("action"),
        }

    def load_event_family(
        self,
        *,
        event_kind: str | None,
        event_name: str | None,
        target_agent: str | None,
    ) -> str:
        normalized_name = str(event_name or "").strip()
        if normalized_name in self.RETRY_EVENT_NAMES:
            return "retry"
        if normalized_name in self.FAILURE_EVENT_NAMES:
            return "failure"
        if normalized_name in self.COMPLETION_EVENT_NAMES:
            return "completion"
        if target_agent:
            return "handoff"
        if str(event_kind or "").strip() == "tool":
            return "tool"
        return "state"

    def load_event_status(
        self,
        *,
        event_family: str,
        event_name: str | None,
        phase: str,
        role: str,
    ) -> str:
        normalized_name = str(event_name or "").strip()
        normalized_phase = str(phase or "").strip()
        if event_family == "failure":
            return "failed"
        if event_family == "completion":
            return "completed"
        if event_family == "retry" and normalized_name == "retry_requested":
            return "scheduled"
        if event_family == "retry" and normalized_name == "retry_exhausted":
            return "exhausted"
        if role == "tool":
            return "completed"
        if normalized_phase == "tool_call_start":
            return "requested"
        if normalized_phase == "tool_result":
            return "completed"
        return "active"

    def project_learning_entry(
        self,
        learning_entry: dict[str, Any],
        *,
        query_context_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        event_type = str(learning_entry.get("event_type") or "").strip()
        payload = learning_entry.get("payload") if isinstance(learning_entry.get("payload"), dict) else {}
        timestamp = str(payload.get("timestamp") or learning_entry.get("timestamp") or datetime.now(timezone.utc).isoformat())
        if query_context_by_id is None:
            query_context_by_id = {}

        if event_type == "query":
            metadata = dict(payload)
            tool_name = str(metadata.pop("tool", metadata.pop("tool_name", "")) or "")
            query_text = str(metadata.pop("query_text", "") or "")
            event_object = create_query_event(
                event_id=str(payload.get("event_id") or f"learning:query:{uuid.uuid4()}"),
                timestamp=timestamp,
                query_text=query_text,
                tool_name=tool_name,
                session_id=str(payload.get("session_id") or "").strip() or None,
                correlation_id=str(payload.get("event_id") or "").strip() or None,
                agent_label=str(payload.get("agent") or "").strip() or None,
                metadata=metadata,
            )
            query_context_by_id[event_object["event_id"]] = {
                "session_id": event_object.get("session_id"),
                "agent_label": event_object.get("agent_label"),
                "correlation_id": event_object.get("correlation_id"),
            }
            return [event_object]

        if event_type == "outcome":
            metadata = dict(payload)
            tool_name = str(metadata.pop("tool", metadata.pop("tool_name", "")) or "")
            query_event_id = str(metadata.pop("query_event_id", "") or "")
            success = bool(metadata.pop("success", False))
            query_context = (query_context_by_id.get(query_event_id) or {}) if query_event_id else {}
            return [
                create_outcome_event(
                    event_id=str(payload.get("event_id") or f"learning:outcome:{uuid.uuid4()}"),
                    timestamp=timestamp,
                    query_event_id=query_event_id,
                    tool_name=tool_name,
                    success=success,
                    session_id=str(payload.get("session_id") or query_context.get("session_id") or "").strip() or None,
                    correlation_id=str(query_event_id or query_context.get("correlation_id") or "").strip() or None,
                    agent_label=str(payload.get("agent") or query_context.get("agent_label") or "").strip() or None,
                    metadata=metadata,
                )
            ]

        return []

    def project_history_entry(self, history_entry: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        data_object = history_entry.get("data") if isinstance(history_entry.get("data"), dict) else {}
        workflow_object = data_object.get("workflow") if isinstance(data_object.get("workflow"), dict) else {}
        workflow_event = workflow_object.get("event") if isinstance(workflow_object.get("event"), dict) else {}
        snapshot_object = workflow_object.get("snapshot") if isinstance(workflow_object.get("snapshot"), dict) else {}
        snapshot_event = snapshot_object.get("event") if isinstance(snapshot_object.get("event"), dict) else {}
        actor_object = snapshot_object.get("actor") if isinstance(snapshot_object.get("actor"), dict) else {}
        retry_object = workflow_object.get("retry") if isinstance(workflow_object.get("retry"), dict) else {}
        effective_event = self.load_effective_workflow_event(workflow_event, snapshot_event)
        workflow_payload = effective_event.get("payload") if isinstance(effective_event.get("payload"), dict) else {}
        phase = str(workflow_object.get("phase") or history_entry.get("thread-name") or "history").strip()
        timestamp = self.load_history_timestamp(history_entry)
        message_id = str(history_entry.get("message-id") or uuid.uuid4())
        session_id = str(workflow_object.get("scope_key") or history_entry.get("thread-id") or "").strip() or None
        agent_label = str(
            workflow_object.get("agent_label")
            or history_entry.get("assistant-name")
            or history_entry.get("name")
            or ""
        ).strip() or None
        workflow_name = str(workflow_object.get("workflow_name") or "").strip() or None
        event_kind = str(effective_event.get("kind") or "").strip() or None
        event_name = str(effective_event.get("name") or "").strip() or None
        tool_name_hint = str(effective_event.get("tool_name") or "").strip() or None
        target_agent = str(effective_event.get("target_agent") or "").strip() or None
        correlation_id = str(effective_event.get("correlation_id") or "").strip() or None
        action_name = str(effective_event.get("action") or "").strip() or None
        role = str(history_entry.get("role") or "").strip()
        event_family = self.load_event_family(
            event_kind=event_kind,
            event_name=event_name,
            target_agent=target_agent,
        )
        event_status = self.load_event_status(
            event_family=event_family,
            event_name=event_name,
            phase=phase,
            role=role,
        )

        state_name = str(workflow_object.get("current_state") or "").strip()
        if state_name:
            events.append(
                create_workflow_state_event(
                    event_id=f"history:{message_id}:workflow_state",
                    timestamp=timestamp,
                    state_name=state_name,
                    state_phase=phase,
                    session_id=session_id,
                    correlation_id=event_name,
                    agent_label=agent_label,
                    workflow_name=workflow_name,
                    metadata={
                        "source": "chat_history",
                        "event_kind": event_kind,
                        "event_name": event_name,
                        "event_payload": dict(workflow_payload),
                        "thread_id": history_entry.get("thread-id"),
                        "thread_name": history_entry.get("thread-name"),
                        "terminal": bool(workflow_object.get("terminal")),
                        "event_family": event_family,
                        "event_status": event_status,
                        "actor_kind": actor_object.get("kind"),
                        "actor_name": actor_object.get("name"),
                        "tool_name": tool_name_hint,
                        "target_agent": target_agent,
                        "correlation_id": correlation_id,
                        "action": action_name,
                        "retry": dict(retry_object),
                    },
                )
            )

        tool_calls = history_entry.get("tool_calls") if isinstance(history_entry.get("tool_calls"), list) else []
        for index, tool_call in enumerate(tool_calls):
            tool_call_id = None
            if isinstance(tool_call, dict):
                tool_call_id = str(tool_call.get("id") or "").strip() or None
            tool_name = self.load_tool_name(tool_call)
            events.append(
                create_tool_call_event(
                    event_id=f"history:{message_id}:tool_call:{tool_call_id or index}",
                    timestamp=timestamp,
                    tool_name=tool_name,
                    phase=phase or "tool_call_start",
                    session_id=session_id,
                    correlation_id=tool_call_id,
                    agent_label=agent_label,
                    workflow_name=workflow_name,
                    metadata={
                        "source": "chat_history",
                        "event_family": "tool",
                        "event_status": "requested",
                        "content": history_entry.get("content"),
                        "thread_id": history_entry.get("thread-id"),
                        "thread_name": history_entry.get("thread-name"),
                        "event_name": event_name,
                        "target_agent": target_agent,
                    },
                )
            )

        tool_name = str(history_entry.get("name") or "").strip()
        tool_call_id = str(history_entry.get("tool_call_id") or "").strip() or None
        if role == "tool" and tool_name:
            tool_event_family = "failure" if event_name == "tool_failed" else "completion"
            tool_event_status = "failed" if event_name == "tool_failed" else "completed"
            events.append(
                create_tool_call_event(
                    event_id=f"history:{message_id}:tool_result:{tool_call_id or tool_name}",
                    timestamp=timestamp,
                    tool_name=tool_name,
                    phase=phase or "tool_result",
                    session_id=session_id,
                    correlation_id=tool_call_id,
                    agent_label=agent_label,
                    workflow_name=workflow_name,
                    metadata={
                        "source": "chat_history",
                        "event_family": tool_event_family,
                        "event_status": tool_event_status,
                        "content": history_entry.get("content"),
                        "thread_id": history_entry.get("thread-id"),
                        "thread_name": history_entry.get("thread-name"),
                        "event_kind": event_kind,
                        "event_name": event_name,
                        "target_agent": target_agent,
                    },
                )
            )

        if target_agent:
            source_agent = str(workflow_payload.get("source_agent") or agent_label or "").strip()
            protocol = str(workflow_payload.get("protocol") or action_name or "workflow_history").strip()
            handoff_status = "completed" if event_name == "routed_agent_complete" else "failed" if event_name == "routed_agent_failed" else "requested"
            events.append(
                create_agent_handoff_event(
                    event_id=f"history:{message_id}:agent_handoff:{target_agent}",
                    timestamp=timestamp,
                    source_agent=source_agent,
                    target_agent=target_agent,
                    protocol=protocol,
                    session_id=session_id,
                    correlation_id=correlation_id or event_name,
                    agent_label=agent_label,
                    workflow_name=workflow_name,
                    metadata={
                        "source": "chat_history",
                        "event_kind": event_kind,
                        "event_name": event_name,
                        "event_family": "handoff",
                        "event_status": handoff_status,
                        "payload": dict(workflow_payload),
                    },
                )
            )

        return events

    def load_projected_objects(
        self,
        *,
        base_dir: str | None = None,
        history_entries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        projected_events: list[dict[str, Any]] = []
        query_context_by_id: dict[str, dict[str, Any]] = {}
        for learning_entry in self.load_learning_events(base_dir):
            projected_events.extend(
                self.project_learning_entry(
                    learning_entry,
                    query_context_by_id=query_context_by_id,
                )
            )
        for history_entry in self.load_history_entries(history_entries):
            projected_events.extend(self.project_history_entry(history_entry))
        return projected_events


RUNTIME_EVENT_FACTORY = RuntimeEventFactory()
RUNTIME_EVENT_VALIDATION_SERVICE = RuntimeEventValidationService()
RUNTIME_EVENT_PROJECTION_SERVICE = RuntimeEventProjectionService()


def create_runtime_event(**kwargs: Any) -> dict[str, Any]:
    return RUNTIME_EVENT_FACTORY.create_object(**kwargs)


def create_query_event(**kwargs: Any) -> dict[str, Any]:
    return RUNTIME_EVENT_FACTORY.create_query_object(**kwargs)


def create_outcome_event(**kwargs: Any) -> dict[str, Any]:
    return RUNTIME_EVENT_FACTORY.create_outcome_object(**kwargs)


def create_tool_call_event(**kwargs: Any) -> dict[str, Any]:
    return RUNTIME_EVENT_FACTORY.create_tool_call_object(**kwargs)


def create_agent_handoff_event(**kwargs: Any) -> dict[str, Any]:
    return RUNTIME_EVENT_FACTORY.create_agent_handoff_object(**kwargs)


def create_workflow_state_event(**kwargs: Any) -> dict[str, Any]:
    return RUNTIME_EVENT_FACTORY.create_workflow_state_object(**kwargs)


def validate_runtime_event(event_object: dict[str, Any]) -> tuple[bool, str]:
    return RUNTIME_EVENT_VALIDATION_SERVICE.validate_object(event_object)


def load_projected_runtime_events(
    *,
    base_dir: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return RUNTIME_EVENT_PROJECTION_SERVICE.load_projected_objects(
        base_dir=base_dir,
        history_entries=history_entries,
    )