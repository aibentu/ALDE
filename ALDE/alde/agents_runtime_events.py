from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _merged_metadata(defaults: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(defaults)
    if isinstance(metadata, dict):
        merged.update(metadata)
    return merged


def validate_runtime_event(event_object: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(event_object, dict):
        return False, "runtime event must be an object"

    event_type = _safe_str(event_object.get("event_type"))
    event_id = _safe_str(event_object.get("event_id"))
    timestamp = _safe_str(event_object.get("timestamp"))
    payload = event_object.get("payload")

    if not event_type:
        return False, "event_type is required"
    if not event_id:
        return False, "event_id is required"
    if not timestamp:
        return False, "timestamp is required"
    if not isinstance(payload, dict):
        return False, "payload must be an object"

    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return False, "payload.metadata must be an object when present"

    if event_type == "query":
        if not _safe_str(payload.get("query_text")):
            return False, "query payload requires query_text"
        if not _safe_str(payload.get("tool_name")):
            return False, "query payload requires tool_name"
    elif event_type == "outcome":
        if not _safe_str(payload.get("query_event_id")):
            return False, "outcome payload requires query_event_id"
        if not _safe_str(payload.get("tool_name")):
            return False, "outcome payload requires tool_name"
        if not isinstance(payload.get("success"), bool):
            return False, "outcome payload requires boolean success"
    elif event_type == "tool_call":
        if not _safe_str(payload.get("tool_name")):
            return False, "tool_call payload requires tool_name"
        if not _safe_str(payload.get("phase")):
            return False, "tool_call payload requires phase"
    elif event_type == "agent_handoff":
        if not _safe_str(payload.get("source_agent")):
            return False, "agent_handoff payload requires source_agent"
        if not _safe_str(payload.get("target_agent")):
            return False, "agent_handoff payload requires target_agent"
        if not _safe_str(payload.get("protocol")):
            return False, "agent_handoff payload requires protocol"
    elif event_type == "workflow_state":
        if not _safe_str(payload.get("state_name")):
            return False, "workflow_state payload requires state_name"

    return True, ""


def _build_runtime_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    correlation_id: str | None = None,
    agent_label: str | None = None,
    workflow_name: str | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    event_object = {
        "event_type": event_type,
        "event_id": _safe_str(event_id) or f"{event_type}:{uuid.uuid4()}",
        "timestamp": _safe_str(timestamp) or _utc_now_iso(),
        "payload": dict(payload or {}),
        "session_id": _safe_str(session_id) or None,
        "correlation_id": _safe_str(correlation_id) or None,
        "agent_label": _safe_str(agent_label) or None,
        "workflow_name": _safe_str(workflow_name) or None,
    }
    ok, reason = validate_runtime_event(event_object)
    if not ok:
        raise ValueError(reason)
    return event_object


def create_query_event(
    *,
    query_text: str,
    tool_name: str,
    session_id: str | None = None,
    correlation_id: str | None = None,
    agent_label: str | None = None,
    workflow_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return _build_runtime_event(
        event_type="query",
        event_id=event_id,
        timestamp=timestamp,
        session_id=session_id,
        correlation_id=correlation_id,
        agent_label=agent_label,
        workflow_name=workflow_name,
        payload={
            "query_text": _safe_str(query_text),
            "tool_name": _safe_str(tool_name),
            "metadata": _merged_metadata({"event_family": "query", "event_status": "requested"}, metadata),
        },
    )


def create_outcome_event(
    *,
    query_event_id: str,
    tool_name: str,
    success: bool,
    session_id: str | None = None,
    correlation_id: str | None = None,
    agent_label: str | None = None,
    workflow_name: str | None = None,
    latency_ms: float | int | None = None,
    reward: float | int | None = None,
    result_count: int | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return _build_runtime_event(
        event_type="outcome",
        event_id=event_id,
        timestamp=timestamp,
        session_id=session_id,
        correlation_id=correlation_id or _safe_str(query_event_id),
        agent_label=agent_label,
        workflow_name=workflow_name,
        payload={
            "query_event_id": _safe_str(query_event_id),
            "tool_name": _safe_str(tool_name),
            "success": bool(success),
            "latency_ms": latency_ms,
            "reward": reward,
            "result_count": result_count,
            "metadata": _merged_metadata(
                {"event_family": "completion" if success else "failure", "event_status": "completed" if success else "failed"},
                metadata,
            ),
        },
    )


def create_tool_call_event(
    *,
    tool_name: str,
    phase: str,
    session_id: str | None = None,
    correlation_id: str | None = None,
    agent_label: str | None = None,
    workflow_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    normalized_phase = _safe_str(phase)
    event_status = "completed" if normalized_phase in {"completed", "tool_result"} else "requested"
    return _build_runtime_event(
        event_type="tool_call",
        event_id=event_id,
        timestamp=timestamp,
        session_id=session_id,
        correlation_id=correlation_id,
        agent_label=agent_label,
        workflow_name=workflow_name,
        payload={
            "tool_name": _safe_str(tool_name),
            "phase": normalized_phase,
            "metadata": _merged_metadata({"event_family": "tool", "event_status": event_status}, metadata),
        },
    )


def create_agent_handoff_event(
    *,
    source_agent: str,
    target_agent: str,
    protocol: str,
    session_id: str | None = None,
    correlation_id: str | None = None,
    agent_label: str | None = None,
    workflow_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    normalized_source_agent = _safe_str(source_agent)
    normalized_target_agent = _safe_str(target_agent)
    normalized_protocol = _safe_str(protocol)
    if not normalized_target_agent:
        raise ValueError("agent_handoff payload requires target_agent")
    return _build_runtime_event(
        event_type="agent_handoff",
        event_id=event_id,
        timestamp=timestamp,
        session_id=session_id,
        correlation_id=correlation_id,
        agent_label=agent_label or normalized_source_agent,
        workflow_name=workflow_name,
        payload={
            "source_agent": normalized_source_agent,
            "target_agent": normalized_target_agent,
            "protocol": normalized_protocol,
            "metadata": _merged_metadata({"event_family": "handoff", "event_status": "requested"}, metadata),
        },
    )


def create_workflow_state_event(
    *,
    state_name: str,
    state_phase: str,
    session_id: str | None = None,
    correlation_id: str | None = None,
    agent_label: str | None = None,
    workflow_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return _build_runtime_event(
        event_type="workflow_state",
        event_id=event_id,
        timestamp=timestamp,
        session_id=session_id,
        correlation_id=correlation_id,
        agent_label=agent_label,
        workflow_name=workflow_name,
        payload={
            "state_name": _safe_str(state_name),
            "state_phase": _safe_str(state_phase),
            "metadata": _merged_metadata({"event_family": "state", "event_status": "active"}, metadata),
        },
    )


def load_projected_runtime_events(
    *,
    base_dir: str | None = None,
    session_id: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from .control_plane_runtime import RUNTIME_PROJECTION_SERVICE

    return RUNTIME_PROJECTION_SERVICE.load_runtime_events(
        base_dir=base_dir,
        session_id=session_id,
        history_entries=history_entries,
    )


__all__ = [
    "create_agent_handoff_event",
    "create_outcome_event",
    "create_query_event",
    "create_tool_call_event",
    "create_workflow_state_event",
    "load_projected_runtime_events",
    "validate_runtime_event",
]