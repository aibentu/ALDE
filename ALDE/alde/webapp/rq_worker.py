from __future__ import annotations

from redis import Redis
from rq import Queue, Worker

from .config import settings


def run_worker() -> None:
    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue(name=settings.rq_queue_name, connection=redis_conn)
    worker = Worker([queue], connection=redis_conn, name="alde-rq-worker")
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    run_worker()
