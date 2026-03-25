from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from alde.webapp.jobs import JobMessage, _rq_queue, get_queue_health, process_job_message, settings, submit_agent_job


class TestWebappJobs(unittest.TestCase):
    def test_rq_queue_returns_none_when_backend_is_not_rq(self) -> None:
        fake_settings = SimpleNamespace(queue_backend="inmemory")

        with patch("alde.webapp.jobs.settings", fake_settings):
            self.assertIsNone(_rq_queue())

    def test_rq_queue_builds_queue_when_redis_and_rq_are_available(self) -> None:
        redis_connection = object()

        class _FakeRedisClient:
            @staticmethod
            def from_url(url: str):
                return redis_connection

        class _FakeRedisModule:
            Redis = _FakeRedisClient

        class _FakeQueueFactory:
            def __init__(self, *, name: str, connection: object) -> None:
                self.name = name
                self.connection = connection

        class _FakeRqModule:
            Queue = _FakeQueueFactory

        fake_settings = SimpleNamespace(
            queue_backend="rq",
            redis_url="redis://example.test/1",
            rq_queue_name="alde-tests",
        )

        with patch("alde.webapp.jobs.settings", fake_settings), patch.dict(
            sys.modules, {"redis": _FakeRedisModule, "rq": _FakeRqModule}
        ):
            queue = _rq_queue()

        self.assertIsNotNone(queue)
        self.assertEqual(queue.name, "alde-tests")
        self.assertIs(queue.connection, redis_connection)

    def test_get_queue_health_returns_unhealthy_when_redis_import_fails(self) -> None:
        fake_settings = SimpleNamespace(queue_backend="rq", redis_url="redis://example.test/1")

        with patch("alde.webapp.jobs.settings", fake_settings), patch(
            "alde.webapp.jobs.importlib.import_module", side_effect=ImportError("redis missing")
        ):
            backend, healthy = get_queue_health()

        self.assertEqual(backend, "rq")
        self.assertFalse(healthy)

    def test_get_queue_health_returns_healthy_when_ping_succeeds(self) -> None:
        class _FakeRedisConnection:
            def ping(self) -> None:
                return None

        class _FakeRedisClient:
            @staticmethod
            def from_url(url: str):
                return _FakeRedisConnection()

        class _FakeRedisModule:
            Redis = _FakeRedisClient

        fake_settings = SimpleNamespace(queue_backend="rq", redis_url="redis://example.test/1")

        with patch("alde.webapp.jobs.settings", fake_settings), patch.dict(
            sys.modules, {"redis": _FakeRedisModule}
        ):
            backend, healthy = get_queue_health()

        self.assertEqual(backend, "rq")
        self.assertTrue(healthy)

    def test_get_queue_health_returns_unhealthy_when_ping_fails(self) -> None:
        class _FakeRedisConnection:
            def ping(self) -> None:
                raise RuntimeError("ping failed")

        class _FakeRedisClient:
            @staticmethod
            def from_url(url: str):
                return _FakeRedisConnection()

        class _FakeRedisModule:
            Redis = _FakeRedisClient

        fake_settings = SimpleNamespace(queue_backend="rq", redis_url="redis://example.test/1")

        with patch("alde.webapp.jobs.settings", fake_settings), patch.dict(
            sys.modules, {"redis": _FakeRedisModule}
        ):
            backend, healthy = get_queue_health()

        self.assertEqual(backend, "rq")
        self.assertFalse(healthy)

    def test_submit_agent_job_enqueues_rq_job_with_retry(self) -> None:
        msg = JobMessage(
            job_id="job-4",
            run_id="run-4",
            tenant_id="tenant-4",
            user_id="user-4",
            target_agent="_writer_agent",
            prompt="draft text",
            metadata={"source": "rq"},
        )

        class _FakeRetry:
            def __init__(self, *, max: int, interval: list[int] | None = None) -> None:
                self.max = max
                self.interval = interval

        class _FakeRqModule:
            Retry = _FakeRetry

        class _FakeQueue:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def enqueue(self, func, **kwargs):
                self.calls.append({"func": func, **kwargs})

        fake_queue = _FakeQueue()

        with patch("alde.webapp.jobs._rq_queue", return_value=fake_queue), patch.dict(
            sys.modules, {"rq": _FakeRqModule}
        ), patch("alde.webapp.jobs.runner.submit") as submit:
            submit_agent_job(msg)

        submit.assert_not_called()
        self.assertEqual(len(fake_queue.calls), 1)
        enqueue_call = fake_queue.calls[0]
        self.assertEqual(enqueue_call["payload"]["job_id"], "job-4")
        self.assertEqual(enqueue_call["payload"]["metadata"]["source"], "rq")
        if settings.rq_retry_max > 0:
            self.assertIsNotNone(enqueue_call["retry"])
            self.assertEqual(enqueue_call["retry"].max, settings.rq_retry_max)
            self.assertEqual(
                enqueue_call["retry"].interval,
                [int(value.strip()) for value in settings.rq_retry_intervals.split(",") if value.strip()] or None,
            )
        else:
            self.assertIsNone(enqueue_call["retry"])

    def test_submit_agent_job_falls_back_when_rq_enqueue_fails(self) -> None:
        msg = JobMessage(
            job_id="job-5",
            run_id="run-5",
            tenant_id="tenant-5",
            user_id="user-5",
            target_agent="_writer_agent",
            prompt="draft text",
            metadata={"source": "rq"},
        )

        class _FakeRetry:
            def __init__(self, *, max: int, interval: list[int] | None = None) -> None:
                self.max = max
                self.interval = interval

        class _FakeRqModule:
            Retry = _FakeRetry

        class _FailingQueue:
            def enqueue(self, func, **kwargs):
                raise RuntimeError("enqueue failed")

        with patch("alde.webapp.jobs._rq_queue", return_value=_FailingQueue()), patch.dict(
            sys.modules, {"rq": _FakeRqModule}
        ), patch("alde.webapp.jobs.runner.submit") as submit:
            submit_agent_job(msg)

        submit.assert_called_once_with(msg)

    def test_process_job_message_marks_run_completed(self) -> None:
        msg = JobMessage(
            job_id="job-1",
            run_id="run-1",
            tenant_id="tenant-1",
            user_id="user-1",
            target_agent="_writer_agent",
            prompt="draft text",
            metadata={"source": "test"},
        )

        with patch("alde.webapp.jobs._call_agent_runtime", return_value="runtime output"), patch(
            "alde.webapp.jobs.repo.update_async_job"
        ) as update_async_job, patch("alde.webapp.jobs.repo.append_audit") as append_audit, patch(
            "alde.webapp.jobs.repo.update_run"
        ) as update_run:
            process_job_message(msg)

        update_async_job.assert_any_call(job_id="job-1", status="running")
        update_async_job.assert_any_call(job_id="job-1", status="completed")
        update_run.assert_called_once()
        self.assertEqual(update_run.call_args.kwargs["run_id"], "run-1")
        self.assertEqual(update_run.call_args.kwargs["status"], "completed")
        self.assertEqual(update_run.call_args.kwargs["output"], "runtime output")
        self.assertEqual(update_run.call_args.kwargs["metadata"]["source"], "test")
        self.assertIn("executed_at", update_run.call_args.kwargs["metadata"])
        self.assertEqual(append_audit.call_count, 2)

    def test_process_job_message_marks_run_failed(self) -> None:
        msg = JobMessage(
            job_id="job-2",
            run_id="run-2",
            tenant_id="tenant-2",
            user_id="user-2",
            target_agent="_writer_agent",
            prompt="draft text",
            metadata={"source": "test"},
        )

        with patch("alde.webapp.jobs._call_agent_runtime", side_effect=RuntimeError("boom")), patch(
            "alde.webapp.jobs.repo.update_async_job"
        ) as update_async_job, patch("alde.webapp.jobs.repo.append_audit") as append_audit, patch(
            "alde.webapp.jobs.repo.update_run"
        ) as update_run:
            process_job_message(msg)

        update_async_job.assert_any_call(job_id="job-2", status="running")
        update_async_job.assert_any_call(job_id="job-2", status="failed", error="RuntimeError: boom")
        update_run.assert_called_once()
        self.assertEqual(update_run.call_args.kwargs["run_id"], "run-2")
        self.assertEqual(update_run.call_args.kwargs["status"], "failed")
        self.assertEqual(update_run.call_args.kwargs["output"], "")
        self.assertIn("RuntimeError: boom", update_run.call_args.kwargs["metadata"]["error"])
        self.assertEqual(append_audit.call_count, 2)

    def test_submit_agent_job_uses_inmemory_runner_when_rq_is_unavailable(self) -> None:
        msg = JobMessage(
            job_id="job-3",
            run_id="run-3",
            tenant_id="tenant-3",
            user_id="user-3",
            target_agent="_writer_agent",
            prompt="draft text",
            metadata={},
        )

        with patch("alde.webapp.jobs._rq_queue", return_value=None), patch("alde.webapp.jobs.runner.submit") as submit:
            submit_agent_job(msg)

        submit.assert_called_once_with(msg)