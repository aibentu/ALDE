from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import importlib
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any

from .config import settings
from .repository import repo
from .services import _call_agent_runtime


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
        self._queue: Queue[JobMessage] = Queue()
        self._stop = Event()
        self._thread = Thread(target=self._work_loop, daemon=True, name="alde-agent-runner")

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread = Thread(target=self._work_loop, daemon=True, name="alde-agent-runner")
            self._stop.clear()
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def submit(self, msg: JobMessage) -> None:
        self._queue.put(msg)

    def _work_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                process_job_message(msg)
            finally:
                self._queue.task_done()


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
        return "inmemory", True

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
