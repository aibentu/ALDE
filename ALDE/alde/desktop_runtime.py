from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Lock
import uuid
from typing import Any

try:
    from .runtime_core import AgentRuntimeCoreService, InMemoryMessageRunnerService  # type: ignore
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from ALDE.alde.runtime_core import AgentRuntimeCoreService, InMemoryMessageRunnerService  # type: ignore
    else:
        raise


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class DesktopAgentRun:
    run_id: str
    request_kind: str
    target_agent: str
    prompt: str
    attachments: list[str] = field(default_factory=list)
    model_name: str = ""
    status: str = "queued"
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request_kind": self.request_kind,
            "target_agent": self.target_agent,
            "prompt": self.prompt,
            "attachments": list(self.attachments),
            "model_name": self.model_name,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "DesktopAgentRun":
        return cls(
            run_id=str(record.get("run_id") or uuid.uuid4().hex),
            request_kind=str(record.get("request_kind") or "chat"),
            target_agent=str(record.get("target_agent") or "_xplaner_xrouter"),
            prompt=str(record.get("prompt") or ""),
            attachments=[str(value) for value in (record.get("attachments") or [])],
            model_name=str(record.get("model_name") or ""),
            status=str(record.get("status") or "queued"),
            output=None if record.get("output") is None else str(record.get("output")),
            error=None if record.get("error") is None else str(record.get("error")),
            metadata=dict(record.get("metadata") or {}),
            created_at=str(record.get("created_at") or _utc_now_iso()),
            updated_at=str(record.get("updated_at") or _utc_now_iso()),
        )


class DesktopAgentRunPersistenceService:
    def __init__(self, *, storage_path: Path | None = None) -> None:
        default_storage_path = Path(__file__).resolve().parents[1] / "AppData" / "desktop_runs.json"
        self.storage_path = Path(storage_path or default_storage_path)

    def load_object_runs(self) -> list[DesktopAgentRun]:
        if not self.storage_path.exists():
            return []
        payload = json.loads(self.storage_path.read_text(encoding="utf-8") or "{}")
        runs = [DesktopAgentRun.from_record(record) for record in (payload.get("runs") or []) if isinstance(record, dict)]
        updated_runs: list[DesktopAgentRun] = []
        mutated = False
        for run in runs:
            if run.status in {"queued", "running"}:
                run.status = "interrupted"
                run.error = "Recovered unfinished local desktop run during startup."
                run.updated_at = _utc_now_iso()
                mutated = True
            updated_runs.append(run)
        if mutated:
            self.store_object_runs(updated_runs)
        return updated_runs

    def store_object_runs(self, runs: list[DesktopAgentRun]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "desktop_runs_v1",
            "updated_at": _utc_now_iso(),
            "runs": [run.to_record() for run in runs],
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class DesktopAgentRunStoreService:
    def __init__(self, *, persistence_service: DesktopAgentRunPersistenceService) -> None:
        self.persistence_service = persistence_service
        self._lock = Lock()
        self._runs: dict[str, DesktopAgentRun] = {
            run.run_id: run
            for run in self.persistence_service.load_object_runs()
        }

    def _persist_object_runs(self) -> None:
        runs = sorted(self._runs.values(), key=lambda run: run.updated_at, reverse=False)
        self.persistence_service.store_object_runs(runs)

    def create_object_run(
        self,
        *,
        request_kind: str,
        target_agent: str,
        prompt: str,
        attachments: list[str] | None = None,
        model_name: str = "",
        status: str = "queued",
        metadata: dict[str, Any] | None = None,
    ) -> DesktopAgentRun:
        with self._lock:
            run = DesktopAgentRun(
                run_id=uuid.uuid4().hex,
                request_kind=request_kind,
                target_agent=target_agent,
                prompt=prompt,
                attachments=list(attachments or []),
                model_name=model_name,
                status=status,
                metadata=dict(metadata or {}),
            )
            self._runs[run.run_id] = run
            self._persist_object_runs()
            return run

    def update_object_run(self, run_id: str, **updates: Any) -> DesktopAgentRun | None:
        with self._lock:
            run = self._runs.get(str(run_id))
            if run is None:
                return None
            for key, value in updates.items():
                if hasattr(run, key):
                    setattr(run, key, value)
            run.updated_at = _utc_now_iso()
            self._persist_object_runs()
            return run

    def load_object_run(self, run_id: str) -> DesktopAgentRun | None:
        with self._lock:
            return self._runs.get(str(run_id))

    def list_object_runs(self, *, limit: int | None = None) -> list[DesktopAgentRun]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda run: run.updated_at, reverse=True)
            if limit is None or limit <= 0:
                return list(runs)
            return list(runs[:limit])


class DesktopAgentRuntimeExecutionService(AgentRuntimeCoreService):
    def execute_chat_object(self, run: DesktopAgentRun) -> str:
        return super().execute_chat_object(
            target_agent=run.target_agent,
            prompt=run.prompt,
            attachments=list(run.attachments),
            model_name=run.model_name,
        )

    def execute_object_run(self, run: DesktopAgentRun) -> str:
        if run.request_kind != "chat":
            raise ValueError(f"Unsupported desktop request_kind: {run.request_kind}")
        return self.execute_chat_object(run)


class DesktopAgentRunQueueService:
    def __init__(self, *, store_service: DesktopAgentRunStoreService, execution_service: Any) -> None:
        self.store_service = store_service
        self.execution_service = execution_service
        self.runner_service = InMemoryMessageRunnerService[
            DesktopAgentRun
        ](
            worker_name="alde-desktop-runner",
            process_object_message=self.process_object_run,
            poll_interval_seconds=0.05,
        )

    def process_object_run(self, run: DesktopAgentRun) -> None:
        self.store_service.update_object_run(run.run_id, status="running", error=None)
        try:
            output = str(self.execution_service.execute_object_run(run) or "")
        except Exception as exc:
            self.store_service.update_object_run(
                run.run_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self.store_service.update_object_run(run.run_id, status="completed", output=output, error=None)

    def submit_object_run(self, run: DesktopAgentRun) -> None:
        self.runner_service.submit_object_message(run)

    def stop_object_runner(self) -> None:
        self.runner_service.stop_object_runner()

    def load_object_health(self) -> dict[str, Any]:
        return self.runner_service.load_object_health()


class DesktopAgentRunMonitorService:
    def __init__(self, *, store_service: DesktopAgentRunStoreService, queue_service: DesktopAgentRunQueueService) -> None:
        self.store_service = store_service
        self.queue_service = queue_service

    def load_runtime_observability_snapshot(self) -> dict[str, Any]:
        try:
            if __package__:
                from .runtime_metrics import load_runtime_observability_snapshot  # type: ignore
            else:
                from alde.runtime_metrics import load_runtime_observability_snapshot  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from runtime_metrics import load_runtime_observability_snapshot  # type: ignore
            else:
                raise

        try:
            snapshot = load_runtime_observability_snapshot()
            return dict(snapshot if isinstance(snapshot, dict) else {})
        except Exception as exc:
            return {
                "healthy": False,
                "queue_backend": "unknown",
                "queue_healthy": False,
                "validation": {
                    "valid": False,
                    "errors": [f"runtime observability unavailable: {type(exc).__name__}: {exc}"],
                },
                "error": f"runtime observability unavailable: {type(exc).__name__}: {exc}",
            }

    def load_object_snapshot(self, *, limit: int = 10) -> dict[str, Any]:
        runs = self.store_service.list_object_runs()
        return {
            "backend": "desktop_local",
            "run_count": len(runs),
            "active_count": sum(1 for run in runs if run.status in {"queued", "running"}),
            "failure_count": sum(1 for run in runs if run.status == "failed"),
            "recent_runs": [run.to_record() for run in runs[:limit]],
            "queue_health": self.queue_service.load_object_health(),
            "runtime_observability": self.load_runtime_observability_snapshot(),
        }

    def load_object_activity_view(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return [run.to_record() for run in self.store_service.list_object_runs(limit=limit)]


class DesktopAgentRunFacadeService:
    def __init__(
        self,
        *,
        store_service: DesktopAgentRunStoreService,
        queue_service: DesktopAgentRunQueueService,
        execution_service: Any,
        monitor_service: DesktopAgentRunMonitorService,
    ) -> None:
        self.store_service = store_service
        self.queue_service = queue_service
        self.execution_service = execution_service
        self.monitor_service = monitor_service

    def queue_object_run(
        self,
        *,
        request_kind: str,
        target_agent: str,
        prompt: str,
        attachments: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_name: str = "",
    ) -> DesktopAgentRun:
        run = self.store_service.create_object_run(
            request_kind=request_kind,
            target_agent=target_agent,
            prompt=prompt,
            attachments=attachments,
            metadata=metadata,
            model_name=model_name,
            status="queued",
        )
        self.queue_service.submit_object_run(run)
        return run

    def load_object_run(self, run_id: str) -> DesktopAgentRun | None:
        return self.store_service.load_object_run(run_id)

    def load_object_snapshot(self, *, limit: int = 10) -> dict[str, Any]:
        return self.monitor_service.load_object_snapshot(limit=limit)

    def load_object_activity_view(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return self.monitor_service.load_object_activity_view(limit=limit)


__all__ = [
    "DesktopAgentRun",
    "DesktopAgentRunFacadeService",
    "DesktopAgentRunMonitorService",
    "DesktopAgentRunPersistenceService",
    "DesktopAgentRunQueueService",
    "DesktopAgentRunStoreService",
    "DesktopAgentRuntimeExecutionService",
]