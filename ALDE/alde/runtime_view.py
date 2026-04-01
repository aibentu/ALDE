from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

try:
    from .runtime_metrics import RUNTIME_METRICS_SERVICE, load_runtime_metrics
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from runtime_metrics import RUNTIME_METRICS_SERVICE, load_runtime_metrics  # type: ignore
    else:
        raise


class RuntimeViewService:
    def load_generated_root(self, base_dir: str | None = None) -> Path:
        return Path(base_dir) if base_dir else Path(__file__).resolve().parents[1] / "AppData" / "generated"

    def sort_events(self, runtime_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [event_object for event_object in runtime_events if isinstance(event_object, dict)],
            key=lambda event_object: (
                str(event_object.get("timestamp") or ""),
                str(event_object.get("event_id") or ""),
            ),
        )

    def load_summary(self, runtime_event: dict[str, Any], metadata: dict[str, Any]) -> str:
        event_type = str(runtime_event.get("event_type") or "").strip()
        payload = runtime_event.get("payload") if isinstance(runtime_event.get("payload"), dict) else {}
        if event_type == "query":
            return f"query:{payload.get('tool_name')}"
        if event_type == "outcome":
            status = "ok" if payload.get("success") else "failed"
            return f"outcome:{payload.get('tool_name')}:{status}"
        if event_type == "tool_call":
            return f"tool:{payload.get('tool_name')}:{payload.get('phase')}"
        if event_type == "agent_handoff":
            return f"handoff:{payload.get('source_agent')}->{payload.get('target_agent')}:{metadata.get('event_status') or 'requested'}"
        if event_type == "workflow_state":
            return f"state:{payload.get('state_name')}:{metadata.get('event_name') or metadata.get('event_family') or payload.get('state_phase')}"
        return event_type or "event"

    def build_timeline_entry(self, runtime_event: dict[str, Any]) -> dict[str, Any]:
        payload = runtime_event.get("payload") if isinstance(runtime_event.get("payload"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return {
            "timestamp": runtime_event.get("timestamp"),
            "event_id": runtime_event.get("event_id"),
            "event_type": runtime_event.get("event_type"),
            "session_id": runtime_event.get("session_id"),
            "agent_label": runtime_event.get("agent_label"),
            "workflow_name": runtime_event.get("workflow_name"),
            "status": metadata.get("event_status"),
            "family": metadata.get("event_family") or runtime_event.get("event_type"),
            "summary": self.load_summary(runtime_event, metadata),
            "tool_name": payload.get("tool_name"),
            "state_name": payload.get("state_name"),
            "target_agent": payload.get("target_agent"),
        }

    def build_session_summary(
        self,
        *,
        base_dir: str | None,
        session_id: str,
        runtime_events: list[dict[str, Any]],
        history_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ordered_events = self.sort_events(runtime_events)
        workflow_state_events = [
            event_object
            for event_object in ordered_events
            if str(event_object.get("event_type") or "") == "workflow_state"
        ]
        handoff_events = [
            event_object
            for event_object in ordered_events
            if str(event_object.get("event_type") or "") == "agent_handoff"
        ]
        retry_events = [
            event_object
            for event_object in workflow_state_events
            if isinstance(event_object.get("payload"), dict)
            and isinstance(event_object["payload"].get("metadata"), dict)
            and str(event_object["payload"]["metadata"].get("event_family") or "") == "retry"
        ]
        failure_events = [
            event_object
            for event_object in ordered_events
            if (
                str(event_object.get("event_type") or "") == "outcome"
                and isinstance(event_object.get("payload"), dict)
                and not bool(event_object["payload"].get("success"))
            )
            or (
                isinstance(event_object.get("payload"), dict)
                and isinstance(event_object["payload"].get("metadata"), dict)
                and str(event_object["payload"]["metadata"].get("event_status") or "") == "failed"
            )
        ]
        latest_workflow_state = workflow_state_events[-1] if workflow_state_events else None
        latest_handoff = handoff_events[-1] if handoff_events else None
        metrics = RUNTIME_METRICS_SERVICE.summarize_event_objects(
            ordered_events,
            session_id=session_id,
        )
        agent_labels = sorted({str(event_object.get("agent_label") or "").strip() for event_object in ordered_events if str(event_object.get("agent_label") or "").strip()})
        workflow_names = sorted({str(event_object.get("workflow_name") or "").strip() for event_object in ordered_events if str(event_object.get("workflow_name") or "").strip()})
        return {
            "session_id": session_id,
            "event_count": len(ordered_events),
            "agent_labels": agent_labels,
            "workflow_names": workflow_names,
            "first_timestamp": ordered_events[0].get("timestamp") if ordered_events else None,
            "last_timestamp": ordered_events[-1].get("timestamp") if ordered_events else None,
            "latest_workflow_state": self.build_timeline_entry(latest_workflow_state) if isinstance(latest_workflow_state, dict) else None,
            "latest_handoff": self.build_timeline_entry(latest_handoff) if isinstance(latest_handoff, dict) else None,
            "retry": {
                "requested_count": sum(
                    1
                    for event_object in retry_events
                    if str(((event_object.get("payload") or {}).get("metadata") or {}).get("event_name") or "") == "retry_requested"
                ),
                "exhausted_count": sum(
                    1
                    for event_object in retry_events
                    if str(((event_object.get("payload") or {}).get("metadata") or {}).get("event_name") or "") == "retry_exhausted"
                ),
            },
            "handoffs": {
                "count": len(handoff_events),
                "completed_count": sum(
                    1
                    for event_object in handoff_events
                    if str(((event_object.get("payload") or {}).get("metadata") or {}).get("event_status") or "") == "completed"
                ),
                "failed_count": sum(
                    1
                    for event_object in handoff_events
                    if str(((event_object.get("payload") or {}).get("metadata") or {}).get("event_status") or "") == "failed"
                ),
            },
            "failure_count": len(failure_events),
            "metrics": metrics,
        }

    def build_view_object(
        self,
        *,
        base_dir: str | None = None,
        session_id: str | None = None,
        history_entries: list[dict[str, Any]] | None = None,
        event_limit: int | None = None,
    ) -> dict[str, Any]:
        runtime_events = RUNTIME_METRICS_SERVICE.load_event_objects(
            base_dir=base_dir,
            session_id=session_id,
            history_entries=history_entries,
        )
        ordered_events = self.sort_events(runtime_events)
        if event_limit is not None and event_limit >= 0:
            ordered_events = ordered_events[-event_limit:]

        grouped_events: dict[str, list[dict[str, Any]]] = {}
        for event_object in ordered_events:
            group_session_id = str(event_object.get("session_id") or "unknown").strip() or "unknown"
            grouped_events.setdefault(group_session_id, []).append(event_object)

        session_views = [
            self.build_session_summary(
                base_dir=base_dir,
                session_id=session_key,
                runtime_events=grouped_events[session_key],
                history_entries=history_entries,
            )
            for session_key in sorted(grouped_events)
        ]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "session_count": len(session_views),
            "event_count": len(ordered_events),
            "metrics": load_runtime_metrics(base_dir=base_dir, session_id=session_id, history_entries=history_entries),
            "sessions": session_views,
            "events": [self.build_timeline_entry(event_object) for event_object in ordered_events],
        }

    def export_view_object(
        self,
        *,
        base_dir: str | None = None,
        session_id: str | None = None,
        history_entries: list[dict[str, Any]] | None = None,
        event_limit: int | None = None,
    ) -> str:
        target_root = self.load_generated_root(base_dir)
        target_root.mkdir(parents=True, exist_ok=True)
        if session_id:
            safe_session_id = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in str(session_id))
            target_path = target_root / f"runtime_view_{safe_session_id}.json"
        else:
            target_path = target_root / "runtime_view_latest.json"
        view_object = self.build_view_object(
            base_dir=base_dir,
            session_id=session_id,
            history_entries=history_entries,
            event_limit=event_limit,
        )
        with open(target_path, "w", encoding="utf-8") as view_file:
            json.dump(view_object, view_file, ensure_ascii=False, indent=2)
        return str(target_path)


RUNTIME_VIEW_SERVICE = RuntimeViewService()


def load_runtime_view(
    *,
    base_dir: str | None = None,
    session_id: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
    event_limit: int | None = None,
) -> dict[str, Any]:
    return RUNTIME_VIEW_SERVICE.build_view_object(
        base_dir=base_dir,
        session_id=session_id,
        history_entries=history_entries,
        event_limit=event_limit,
    )


def export_runtime_view(
    *,
    base_dir: str | None = None,
    session_id: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
    event_limit: int | None = None,
) -> str:
    return RUNTIME_VIEW_SERVICE.export_view_object(
        base_dir=base_dir,
        session_id=session_id,
        history_entries=history_entries,
        event_limit=event_limit,
    )