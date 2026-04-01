from __future__ import annotations

import atexit
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from .runtime_core import AgentRuntimeCoreService, InMemoryMessageRunnerService


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class DesktopAgentRun:
    run_id: str
    request_kind: str
    target_agent: str
    prompt: str
    attachments: list[str] = field(default_factory=list)
    model_name: str = ""
    status: str = "queued"
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)


@dataclass(slots=True)
class DesktopAgentRunMessage:
    run_id: str


class DesktopAgentRunPersistenceService:
    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else self.load_object_storage_path()

    def load_object_storage_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "AppData" / "desktop_runs.json"

    def _sanitize_object_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth >= 4:
            return str(value)
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (bytes, bytearray)):
            return {"kind": "bytes", "length": len(value)}
        if isinstance(value, dict):
            return {
                str(key): self._sanitize_object_value(item, depth=depth + 1)
                for key, item in list(value.items())[:32]
            }
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize_object_value(item, depth=depth + 1) for item in list(value)[:32]]
        return str(value)

    def _serialize_object_run(self, run: DesktopAgentRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "request_kind": run.request_kind,
            "target_agent": run.target_agent,
            "prompt": run.prompt,
            "attachments": list(run.attachments or []),
            "model_name": run.model_name,
            "status": run.status,
            "output": self._sanitize_object_value(run.output),
            "error": run.error,
            "metadata": self._sanitize_object_value(run.metadata),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    def _deserialize_object_run(self, payload: dict[str, Any]) -> DesktopAgentRun | None:
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            return None
        status = str(payload.get("status") or "queued").strip() or "queued"
        error = payload.get("error")
        metadata = dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}
        if status in {"queued", "running"}:
            status = "interrupted"
            if not error:
                error = "Recovered unfinished local desktop run from previous session."
            metadata = {**metadata, "recovered_after_restart": True}
        return DesktopAgentRun(
            run_id=run_id,
            request_kind=str(payload.get("request_kind") or "chat").strip() or "chat",
            target_agent=str(payload.get("target_agent") or "_xplaner_xrouter").strip() or "_xplaner_xrouter",
            prompt=str(payload.get("prompt") or ""),
            attachments=list(payload.get("attachments") or []),
            model_name=str(payload.get("model_name") or ""),
            status=status,
            output=payload.get("output"),
            error=str(error) if error else None,
            metadata=metadata,
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            updated_at=str(payload.get("updated_at") or payload.get("created_at") or _utc_now_iso()),
        )

    def load_object_runs(self) -> dict[str, DesktopAgentRun]:
        try:
            if not self.storage_path.is_file():
                return {}
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        rows = payload.get("runs") if isinstance(payload, dict) else []
        runs: dict[str, DesktopAgentRun] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            run = self._deserialize_object_run(row)
            if run is not None:
                runs[run.run_id] = run
        return runs

    def store_object_runs(self, runs: list[DesktopAgentRun]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "desktop_runs_v1",
            "updated_at": _utc_now_iso(),
            "runs": [self._serialize_object_run(run) for run in runs],
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class DesktopAgentRunStoreService:
    def __init__(self, *, persistence_service: DesktopAgentRunPersistenceService | None = None) -> None:
        self.persistence_service = persistence_service or DesktopAgentRunPersistenceService()
        self._lock = Lock()
        self._runs: dict[str, DesktopAgentRun] = self.persistence_service.load_object_runs()
        self._persist_object_runs(list(self._runs.values()))

    def _persist_object_runs(self, runs: list[DesktopAgentRun]) -> None:
        try:
            self.persistence_service.store_object_runs(runs)
        except Exception:
            return

    def create_object_run(
        self,
        *,
        request_kind: str,
        target_agent: str,
        prompt: str,
        attachments: list[str] | None = None,
        model_name: str = "",
        metadata: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> DesktopAgentRun:
        run = DesktopAgentRun(
            run_id=uuid4().hex,
            request_kind=str(request_kind or "chat").strip() or "chat",
            target_agent=str(target_agent or "_xplaner_xrouter").strip() or "_xplaner_xrouter",
            prompt=str(prompt or ""),
            attachments=list(attachments or []),
            model_name=str(model_name or ""),
            status=status,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._runs[run.run_id] = run
            persisted_runs = list(self._runs.values())
        self._persist_object_runs(persisted_runs)
        return run

    def update_object_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        output: Any = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DesktopAgentRun | None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                return None
            updated = replace(
                current,
                status=status or current.status,
                output=current.output if output is None else output,
                error=error if error is not None else current.error,
                metadata={**current.metadata, **dict(metadata or {})},
                updated_at=_utc_now_iso(),
            )
            self._runs[run_id] = updated
            persisted_runs = list(self._runs.values())
        self._persist_object_runs(persisted_runs)
        return updated

    def load_object_run(self, run_id: str) -> DesktopAgentRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_object_runs(self, *, status_in: set[str] | None = None) -> list[DesktopAgentRun]:
        with self._lock:
            runs = list(self._runs.values())
        if not status_in:
            return runs
        return [run for run in runs if run.status in status_in]


class DesktopAgentRuntimeExecutionService(AgentRuntimeCoreService):
    def _normalize_image_description(self, response: Any) -> str:
        if hasattr(response, "choices") and getattr(response, "choices", None):
            choice = response.choices[0]
            message = getattr(choice, "message", None)
            content = getattr(message, "content", None)
            return str(content or "")
        if hasattr(response, "content"):
            return str(getattr(response, "content") or "")
        return str(response or "")

    def execute_chat_object(self, run: DesktopAgentRun) -> str:
        return super().execute_chat_object(
            target_agent=run.target_agent,
            prompt=run.prompt,
            attachments=run.attachments,
            model_name=run.model_name,
        )

    def execute_image_description_object(self, run: DesktopAgentRun) -> str:
        _, ImageDescription, _ = self.load_chat_components()
        image_url = str((run.attachments or [""])[0] or "").strip()
        response = ImageDescription(
            _model=run.model_name or "gpt-5",
            _url=image_url,
            _input_text=run.prompt,
        ).get_descript()
        return self._normalize_image_description(response)

    def execute_image_creation_object(self, run: DesktopAgentRun) -> Any:
        _, _, ImageCreate = self.load_chat_components()
        return ImageCreate(
            _model=run.model_name or "gpt-5",
            _input_text=run.prompt,
        ).get_img()

    def execute_object_run(self, run: DesktopAgentRun) -> Any:
        request_kind = str(run.request_kind or "chat").strip().lower()
        if request_kind == "chat":
            return self.execute_chat_object(run)
        if request_kind == "image_description":
            return self.execute_image_description_object(run)
        if request_kind == "image_create":
            return self.execute_image_creation_object(run)
        raise ValueError(f"unsupported desktop request kind: {request_kind}")


class DesktopAgentRunQueueService:
    def __init__(
        self,
        *,
        store_service: DesktopAgentRunStoreService,
        execution_service: DesktopAgentRuntimeExecutionService,
    ) -> None:
        self.store_service = store_service
        self.execution_service = execution_service
        self._runner = InMemoryMessageRunnerService[
            DesktopAgentRunMessage
        ](
            worker_name="alde-desktop-agent-runner",
            process_object_message=self._process_object_message,
        )

    def start_object_runner(self) -> None:
        self._runner.start_object_runner()

    def stop_object_runner(self) -> None:
        self._runner.stop_object_runner()

    def submit_object_run(self, run: DesktopAgentRun) -> None:
        self._runner.submit_object_message(DesktopAgentRunMessage(run_id=run.run_id))

    def load_object_queue_health(self) -> dict[str, Any]:
        return self._runner.load_object_health()

    def _process_object_message(self, message: DesktopAgentRunMessage) -> None:
        try:
            run = self.store_service.load_object_run(message.run_id)
            if run is None:
                return
            self.store_service.update_object_run(run.run_id, status="running")
            result = self.execution_service.execute_object_run(run)
            self.store_service.update_object_run(run.run_id, status="completed", output=result, error=None)
        except Exception as exc:
            self.store_service.update_object_run(
                message.run_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )


class DesktopAgentRunMonitorService:
    def __init__(
        self,
        *,
        store_service: DesktopAgentRunStoreService,
        queue_service: DesktopAgentRunQueueService,
    ) -> None:
        self.store_service = store_service
        self.queue_service = queue_service

    def load_object_snapshot(self, *, limit: int = 8) -> dict[str, Any]:
        runs = sorted(
            self.store_service.list_object_runs(),
            key=lambda run: (str(run.updated_at or ""), str(run.created_at or "")),
            reverse=True,
        )
        status_counts: dict[str, int] = {}
        recent_runs: list[dict[str, Any]] = []
        for run in runs:
            status_counts[run.status] = status_counts.get(run.status, 0) + 1
        for run in runs[: max(int(limit or 0), 0)]:
            recent_runs.append(
                {
                    "run_id": run.run_id,
                    "status": run.status,
                    "request_kind": run.request_kind,
                    "target_agent": run.target_agent,
                    "updated_at": run.updated_at,
                    "created_at": run.created_at,
                    "prompt_preview": str(run.prompt or "")[:120],
                    "error": run.error,
                }
            )

        queue_health = self.queue_service.load_object_queue_health()
        return {
            "run_count": len(runs),
            "queued_count": status_counts.get("queued", 0),
            "running_count": status_counts.get("running", 0),
            "completed_count": status_counts.get("completed", 0),
            "failure_count": status_counts.get("failed", 0),
            "active_count": status_counts.get("queued", 0) + status_counts.get("running", 0),
            "latest_run": recent_runs[0] if recent_runs else None,
            "recent_runs": recent_runs,
            "queue_backend": str(queue_health.get("backend") or "inmemory"),
            "queue_healthy": bool(queue_health.get("healthy", True)),
            "runner_alive": bool(queue_health.get("runner_alive", False)),
            "pending_count": int(queue_health.get("pending_count") or 0),
        }

    def load_object_activity_view(self, *, limit: int = 12) -> list[dict[str, Any]]:
        activity_items: list[dict[str, Any]] = []
        for run in self.load_object_snapshot(limit=limit).get("recent_runs") or []:
            status = str(run.get("status") or "unknown")
            summary = str(run.get("prompt_preview") or "")
            if run.get("error"):
                summary = f"{summary} | {run.get('error')}".strip()
            activity_items.append(
                {
                    "timestamp": str(run.get("updated_at") or run.get("created_at") or "n/a"),
                    "source": "desktop",
                    "kind": "local_run",
                    "title": f"{status} {str(run.get('target_agent') or 'local run')}",
                    "summary": summary,
                    "status": status,
                    "run_id": str(run.get("run_id") or ""),
                    "target_agent": str(run.get("target_agent") or ""),
                }
            )
        return activity_items


class DesktopAgentRunFacadeService:
    def __init__(
        self,
        *,
        store_service: DesktopAgentRunStoreService,
        queue_service: DesktopAgentRunQueueService,
        execution_service: DesktopAgentRuntimeExecutionService,
        monitor_service: DesktopAgentRunMonitorService,
    ) -> None:
        self.store_service = store_service
        self.queue_service = queue_service
        self.execution_service = execution_service
        self.monitor_service = monitor_service

    def run_object_sync(
        self,
        *,
        request_kind: str,
        target_agent: str,
        prompt: str,
        attachments: list[str] | None = None,
        model_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DesktopAgentRun:
        run = self.store_service.create_object_run(
            request_kind=request_kind,
            target_agent=target_agent,
            prompt=prompt,
            attachments=attachments,
            model_name=model_name,
            metadata=metadata,
            status="running",
        )
        try:
            result = self.execution_service.execute_object_run(run)
            updated = self.store_service.update_object_run(run.run_id, status="completed", output=result, error=None)
            return updated or run
        except Exception as exc:
            updated = self.store_service.update_object_run(
                run.run_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return updated or run

    def queue_object_run(
        self,
        *,
        request_kind: str,
        target_agent: str,
        prompt: str,
        attachments: list[str] | None = None,
        model_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DesktopAgentRun:
        run = self.store_service.create_object_run(
            request_kind=request_kind,
            target_agent=target_agent,
            prompt=prompt,
            attachments=attachments,
            model_name=model_name,
            metadata=metadata,
            status="queued",
        )
        self.queue_service.submit_object_run(run)
        return run

    def load_object_run(self, run_id: str) -> DesktopAgentRun | None:
        return self.store_service.load_object_run(run_id)

    def list_object_runs(self, *, status_in: set[str] | None = None) -> list[DesktopAgentRun]:
        return self.store_service.list_object_runs(status_in=status_in)

    def load_monitoring_snapshot(self, *, limit: int = 8) -> dict[str, Any]:
        return self.monitor_service.load_object_snapshot(limit=limit)

    def load_queue_health(self) -> dict[str, Any]:
        return self.queue_service.load_object_queue_health()

    def load_activity_view(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.monitor_service.load_object_activity_view(limit=limit)

    def describe_object_image(
        self,
        *,
        prompt: str,
        image_path: str,
        model_name: str = "gpt-5",
        metadata: dict[str, Any] | None = None,
    ) -> DesktopAgentRun:
        return self.run_object_sync(
            request_kind="image_description",
            target_agent="_xplaner_xrouter",
            prompt=prompt,
            attachments=[image_path],
            model_name=model_name,
            metadata=metadata,
        )

    def create_object_image(
        self,
        *,
        prompt: str,
        model_name: str = "gpt-5",
        metadata: dict[str, Any] | None = None,
    ) -> DesktopAgentRun:
        return self.run_object_sync(
            request_kind="image_create",
            target_agent="_xplaner_xrouter",
            prompt=prompt,
            attachments=[],
            model_name=model_name,
            metadata=metadata,
        )


DESKTOP_AGENT_RUN_PERSISTENCE_SERVICE = DesktopAgentRunPersistenceService()
DESKTOP_AGENT_RUN_STORE_SERVICE = DesktopAgentRunStoreService(
    persistence_service=DESKTOP_AGENT_RUN_PERSISTENCE_SERVICE,
)
DESKTOP_AGENT_RUNTIME_EXECUTION_SERVICE = DesktopAgentRuntimeExecutionService()
DESKTOP_AGENT_RUN_QUEUE_SERVICE = DesktopAgentRunQueueService(
    store_service=DESKTOP_AGENT_RUN_STORE_SERVICE,
    execution_service=DESKTOP_AGENT_RUNTIME_EXECUTION_SERVICE,
)
DESKTOP_AGENT_RUN_MONITOR_SERVICE = DesktopAgentRunMonitorService(
    store_service=DESKTOP_AGENT_RUN_STORE_SERVICE,
    queue_service=DESKTOP_AGENT_RUN_QUEUE_SERVICE,
)
DESKTOP_AGENT_RUN_FACADE_SERVICE = DesktopAgentRunFacadeService(
    store_service=DESKTOP_AGENT_RUN_STORE_SERVICE,
    queue_service=DESKTOP_AGENT_RUN_QUEUE_SERVICE,
    execution_service=DESKTOP_AGENT_RUNTIME_EXECUTION_SERVICE,
    monitor_service=DESKTOP_AGENT_RUN_MONITOR_SERVICE,
)

atexit.register(DESKTOP_AGENT_RUN_QUEUE_SERVICE.stop_object_runner)