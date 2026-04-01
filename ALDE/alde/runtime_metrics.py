from __future__ import annotations

from pathlib import Path
from typing import Any
import json

try:
    from .event_store import load_runtime_events
    from .runtime_events import load_projected_runtime_events
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from event_store import load_runtime_events  # type: ignore
        from runtime_events import load_projected_runtime_events  # type: ignore
    else:
        raise


class RuntimeMetricsService:
    def summarize_event_objects(
        self,
        runtime_events: list[dict[str, Any]],
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        event_type_counts: dict[str, int] = {}
        tool_name_counts: dict[str, int] = {}
        handoff_target_counts: dict[str, int] = {}
        latency_values: list[int] = []
        reward_values: list[float] = []
        success_count = 0
        failure_count = 0

        for runtime_event in runtime_events:
            event_type = str(runtime_event.get("event_type") or "unknown")
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1

            payload = runtime_event.get("payload") if isinstance(runtime_event.get("payload"), dict) else {}
            tool_name = str(payload.get("tool_name") or "").strip()
            if tool_name:
                tool_name_counts[tool_name] = tool_name_counts.get(tool_name, 0) + 1

            target_agent = str(payload.get("target_agent") or "").strip()
            if event_type == "agent_handoff" and target_agent:
                handoff_target_counts[target_agent] = handoff_target_counts.get(target_agent, 0) + 1

            latency_ms = payload.get("latency_ms")
            if isinstance(latency_ms, int) and latency_ms >= 0:
                latency_values.append(latency_ms)

            reward_value = payload.get("reward")
            if isinstance(reward_value, (int, float)):
                reward_values.append(float(reward_value))

            if event_type == "outcome":
                if bool(payload.get("success")):
                    success_count += 1
                else:
                    failure_count += 1

        average_latency_ms = round(sum(latency_values) / len(latency_values), 2) if latency_values else 0.0
        average_reward = round(sum(reward_values) / len(reward_values), 4) if reward_values else 0.0

        return {
            "event_count": len(runtime_events),
            "session_id": session_id,
            "event_type_counts": event_type_counts,
            "tool_name_counts": tool_name_counts,
            "handoff_target_counts": handoff_target_counts,
            "success_count": success_count,
            "failure_count": failure_count,
            "average_latency_ms": average_latency_ms,
            "average_reward": average_reward,
        }

    def load_event_objects(
        self,
        *,
        base_dir: str | None = None,
        session_id: str | None = None,
        history_entries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        combined_events = list(load_projected_runtime_events(base_dir=base_dir, history_entries=history_entries))
        combined_events.extend(load_runtime_events(base_dir=base_dir))

        unique_events: list[dict[str, Any]] = []
        seen_event_keys: set[str] = set()
        for runtime_event in combined_events:
            if not isinstance(runtime_event, dict):
                continue
            event_session_id = str(runtime_event.get("session_id") or "").strip()
            if session_id and event_session_id != str(session_id):
                continue
            event_id = str(runtime_event.get("event_id") or "").strip()
            event_key = event_id or json.dumps(runtime_event, ensure_ascii=False, sort_keys=True)
            if event_key in seen_event_keys:
                continue
            seen_event_keys.add(event_key)
            unique_events.append(runtime_event)
        return unique_events

    def load_metric_snapshot(
        self,
        *,
        base_dir: str | None = None,
        session_id: str | None = None,
        history_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        runtime_events = self.load_event_objects(
            base_dir=base_dir,
            session_id=session_id,
            history_entries=history_entries,
        )
        return self.summarize_event_objects(runtime_events, session_id=session_id)

    def export_metric_snapshot(
        self,
        *,
        base_dir: str | None = None,
        session_id: str | None = None,
        history_entries: list[dict[str, Any]] | None = None,
    ) -> str:
        target_root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1] / "AppData" / "generated"
        target_root.mkdir(parents=True, exist_ok=True)
        target_path = target_root / "runtime_metrics_latest.json"
        snapshot = self.load_metric_snapshot(base_dir=base_dir, session_id=session_id, history_entries=history_entries)
        with open(target_path, "w", encoding="utf-8") as metrics_file:
            json.dump(snapshot, metrics_file, ensure_ascii=False, indent=2)
        return str(target_path)


RUNTIME_METRICS_SERVICE = RuntimeMetricsService()


def load_runtime_metrics(
    *,
    base_dir: str | None = None,
    session_id: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return RUNTIME_METRICS_SERVICE.load_metric_snapshot(
        base_dir=base_dir,
        session_id=session_id,
        history_entries=history_entries,
    )


def export_runtime_metrics(
    *,
    base_dir: str | None = None,
    session_id: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
) -> str:
    return RUNTIME_METRICS_SERVICE.export_metric_snapshot(
        base_dir=base_dir,
        session_id=session_id,
        history_entries=history_entries,
    )