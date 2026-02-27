from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass
class BenchmarkResult:
    jobs: int
    workers: int
    submit_seconds: float
    complete_seconds: float
    completed: int
    failed: int
    pending: int
    throughput_jobs_per_sec: float
    p50_completion_seconds: float
    p95_completion_seconds: float


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    idx = int(round((len(values) - 1) * p))
    idx = min(max(idx, 0), len(values) - 1)
    return sorted(values)[idx]


def _start_redislite_url(run_id: str) -> tuple[str, Any]:
    from redislite import Redis

    appdata = Path("AppData")
    appdata.mkdir(exist_ok=True)
    redis_dir = appdata / "redis-lite"
    redis_dir.mkdir(exist_ok=True)
    redis_db = redis_dir / f"benchmark-queue-{run_id}.db"

    redis = Redis(str(redis_db))
    redis_socket = redis.connection_pool.connection_kwargs.get("path")
    if not redis_socket:
        raise RuntimeError("redislite did not provide socket path")
    redis_url = f"unix://{redis_socket}?db=0"
    return redis_url, redis


def run_benchmark(
    *,
    py_exec: str,
    host: str,
    port: int,
    workers: int,
    jobs: int,
    timeout_seconds: int,
    redis_url: str,
    queue_name: str,
) -> BenchmarkResult:
    run_id = str(int(time.time()))
    base = f"http://{host}:{port}"

    env = os.environ.copy()
    env["ALDE_WEB_DATABASE_URL"] = f"sqlite:///./AppData/alde_web_benchmark_{run_id}.db"
    env["ALDE_WEB_QUEUE_BACKEND"] = "rq"
    env["ALDE_WEB_REDIS_URL"] = redis_url
    env["ALDE_WEB_RQ_QUEUE"] = queue_name

    api = subprocess.Popen(
        [py_exec, "-m", "uvicorn", "alde.webapp.main:app", "--host", host, "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    worker_procs = [
        subprocess.Popen(
            [py_exec, "-m", "alde.webapp.rq_worker"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(workers)
    ]

    client = httpx.Client(timeout=20.0)
    submit_times: dict[str, float] = {}
    finish_times: dict[str, float] = {}

    try:
        for _ in range(120):
            try:
                h = client.get(f"{base}/api/v1/health")
                if h.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)

        slug = f"bench{run_id}"
        reg = client.post(
            f"{base}/api/v1/auth/register-tenant",
            json={
                "slug": slug,
                "name": "Queue Benchmark",
                "admin_email": f"admin+{slug}@next.local",
                "admin_display_name": "Bench Admin",
            },
        )
        reg.raise_for_status()
        token = reg.json()["token"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        t_submit_start = time.time()
        job_ids: list[str] = []
        for idx in range(jobs):
            submit_t = time.time()
            resp = client.post(
                f"{base}/api/v1/agents/runs/async",
                headers=headers,
                json={
                    "target_agent": "_primary_assistant",
                    "prompt": f"benchmark job {idx}",
                    "metadata": {"bench": True, "idx": idx},
                },
            )
            resp.raise_for_status()
            job_id = resp.json()["job_id"]
            job_ids.append(job_id)
            submit_times[job_id] = submit_t
        submit_seconds = time.time() - t_submit_start

        deadline = time.time() + timeout_seconds
        pending = set(job_ids)
        while pending and time.time() < deadline:
            done: list[str] = []
            now = time.time()
            for job_id in list(pending):
                status = client.get(f"{base}/api/v1/agents/jobs/{job_id}", headers=headers).json()["status"]
                if status in {"completed", "failed"}:
                    finish_times[job_id] = now
                    done.append(job_id)
            for d in done:
                pending.remove(d)
            if pending:
                time.sleep(0.15)

        completed = 0
        failed = 0
        for job_id in job_ids:
            status = client.get(f"{base}/api/v1/agents/jobs/{job_id}", headers=headers).json()["status"]
            if status == "completed":
                completed += 1
            elif status == "failed":
                failed += 1

        completion_latencies = [
            finish_times[job_id] - submit_times[job_id]
            for job_id in job_ids
            if job_id in finish_times and job_id in submit_times
        ]
        complete_seconds = max(completion_latencies) if completion_latencies else 0.0

        return BenchmarkResult(
            jobs=jobs,
            workers=workers,
            submit_seconds=submit_seconds,
            complete_seconds=complete_seconds,
            completed=completed,
            failed=failed,
            pending=len(pending),
            throughput_jobs_per_sec=(completed / complete_seconds) if complete_seconds > 0 else 0.0,
            p50_completion_seconds=_percentile(completion_latencies, 0.50),
            p95_completion_seconds=_percentile(completion_latencies, 0.95),
        )
    finally:
        client.close()
        api.terminate()
        for p in worker_procs:
            p.terminate()
        for p in [api, *worker_procs]:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ALDE webapp RQ queue throughput and completion latency.")
    parser.add_argument("--python", default=sys_executable_default(), help="Python executable path.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--jobs", type=int, default=40)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--queue-name", default="alde-agent-runs")
    parser.add_argument("--redis-url", default="", help="Redis URL. If omitted, redislite is used.")
    parser.add_argument("--output-json", default="", help="Optional path to write JSON report.")
    args = parser.parse_args()

    redis_ref = None
    redis_url = args.redis_url
    if not redis_url:
        run_id = str(int(time.time()))
        redis_url, redis_ref = _start_redislite_url(run_id)

    try:
        result = run_benchmark(
            py_exec=args.python,
            host=args.host,
            port=args.port,
            workers=args.workers,
            jobs=args.jobs,
            timeout_seconds=args.timeout_seconds,
            redis_url=redis_url,
            queue_name=args.queue_name,
        )
    finally:
        if redis_ref is not None:
            try:
                redis_ref.shutdown()
            except Exception:
                pass

    report = {
        "jobs": result.jobs,
        "workers": result.workers,
        "submit_seconds": round(result.submit_seconds, 4),
        "complete_seconds": round(result.complete_seconds, 4),
        "completed": result.completed,
        "failed": result.failed,
        "pending": result.pending,
        "throughput_jobs_per_sec": round(result.throughput_jobs_per_sec, 4),
        "p50_completion_seconds": round(result.p50_completion_seconds, 4),
        "p95_completion_seconds": round(result.p95_completion_seconds, 4),
    }

    print(json.dumps(report, indent=2))
    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def sys_executable_default() -> str:
    import sys

    return sys.executable


if __name__ == "__main__":
    main()
