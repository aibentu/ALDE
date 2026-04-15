from __future__ import annotations


def load_runtime_metrics(
    *,
    base_dir: str | None = None,
    session_id: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    from .control_plane_runtime import RUNTIME_METRICS_SERVICE

    return RUNTIME_METRICS_SERVICE.load_runtime_metrics(
        base_dir=base_dir,
        session_id=session_id,
        history_entries=history_entries,
    )


def load_runtime_observability_snapshot(
    *,
    base_dir: str | None = None,
    session_id: str | None = None,
    history_entries: list[dict[str, Any]] | None = None,
    event_limit: int | None = None,
    trace_limit: int | None = None,
) -> dict[str, object]:
    from .control_plane_runtime import load_runtime_observability_snapshot as _load_runtime_observability_snapshot

    return _load_runtime_observability_snapshot(
        base_dir=base_dir,
        session_id=session_id,
        history_entries=history_entries,
        event_limit=event_limit,
        trace_limit=trace_limit,
    )


__all__ = [
    "load_runtime_metrics",
    "load_runtime_observability_snapshot",
]