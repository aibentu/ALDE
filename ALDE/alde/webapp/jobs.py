from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import importlib
from typing import Any

from .config import settings
from .repository import repo
from .services import _call_agent_runtime
from ..runtime_core import InMemoryMessageRunnerService


@dataclass(slots=True)
class JobMessage:
    job_id: str
    run_id: str
    tenant_id: str
    user_id: str
    target_agent: str
    prompt: str
    metadata: dict


def process_job_message(msg: JobMessage) -> None:
    repo.update_async_job(job_id=msg.job_id, status="running")
    repo.append_audit(
        tenant_id=msg.tenant_id,
        user_id=msg.user_id,
        event_type="agent.run_started",
        detail={"job_id": msg.job_id, "run_id": msg.run_id, "target_agent": msg.target_agent},
    )

    try:
        output = _call_agent_runtime(target_agent=msg.target_agent, prompt=msg.prompt)
        repo.update_run(
            run_id=msg.run_id,
            status="completed",
            output=output,
            metadata={**msg.metadata, "executed_at": datetime.now(UTC).isoformat()},
        )
        repo.update_async_job(job_id=msg.job_id, status="completed")
        repo.append_audit(
            tenant_id=msg.tenant_id,
            user_id=msg.user_id,
            event_type="agent.run_completed",
            detail={"job_id": msg.job_id, "run_id": msg.run_id},
        )
    except Exception as exc:
        repo.update_run(
            run_id=msg.run_id,
            status="failed",
            output="",
            metadata={**msg.metadata, "error": f"{type(exc).__name__}: {exc}"},
        )
        repo.update_async_job(job_id=msg.job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        repo.append_audit(
            tenant_id=msg.tenant_id,
            user_id=msg.user_id,
            event_type="agent.run_failed",
            detail={"job_id": msg.job_id, "run_id": msg.run_id, "error": f"{type(exc).__name__}: {exc}"},
        )


def process_rq_job(payload: dict[str, Any]) -> None:
    process_job_message(JobMessage(**payload))


class AgentJobRunner:
    def __init__(self) -> None:
        self._runner = InMemoryMessageRunnerService[
            JobMessage
        ](
            worker_name="alde-agent-runner",
            process_object_message=process_job_message,
        )

    def start(self) -> None:
        self._runner.start_object_runner()

    def stop(self) -> None:
        self._runner.stop_object_runner()

    def submit(self, msg: JobMessage) -> None:
        self._runner.submit_object_message(msg)

    def load_health(self) -> dict[str, Any]:
        return self._runner.load_object_health()


runner = AgentJobRunner()


def _rq_queue() -> Any | None:
    if settings.queue_backend != "rq":
        return None

    try:
        redis_module = importlib.import_module("redis")
        rq_module = importlib.import_module("rq")
    except Exception:
        return None

    try:
        Redis = getattr(redis_module, "Redis")
        RQQueue = getattr(rq_module, "Queue")
        redis_conn = Redis.from_url(settings.redis_url)
        return RQQueue(name=settings.rq_queue_name, connection=redis_conn)
    except Exception:
        return None


def submit_agent_job(msg: JobMessage) -> None:
    rq_queue = _rq_queue()
    if rq_queue is None:
        runner.submit(msg)
        return

    try:
        rq_module = importlib.import_module("rq")
        Retry = getattr(rq_module, "Retry")

        retry_intervals = [
            int(v.strip())
            for v in settings.rq_retry_intervals.split(",")
            if v.strip()
        ]
        if settings.rq_retry_max > 0:
            retry = Retry(max=settings.rq_retry_max, interval=retry_intervals or None)
        else:
            retry = None

        rq_queue.enqueue(
            process_rq_job,
            payload=asdict(msg),
            job_timeout=settings.rq_job_timeout_seconds,
            result_ttl=settings.rq_result_ttl_seconds,
            failure_ttl=settings.rq_failure_ttl_seconds,
            retry=retry,
        )
    except Exception:
        # Fail-safe behavior for production robustness: if Redis enqueue fails,
        # continue processing through the in-process worker.
        runner.submit(msg)


def get_queue_health() -> tuple[str, bool]:
    if settings.queue_backend != "rq":
        runner_health = runner.load_health()
        return str(runner_health.get("backend") or "inmemory"), bool(runner_health.get("healthy", True))

    try:
        redis_module = importlib.import_module("redis")
    except Exception:
        return "rq", False

    try:
        Redis = getattr(redis_module, "Redis")
        redis_conn = Redis.from_url(settings.redis_url)
        redis_conn.ping()
        return "rq", True
    except Exception:
        return "rq", False
