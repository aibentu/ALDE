from __future__ import annotations

from datetime import datetime, UTC

from fastapi import APIRouter

from ..jobs import get_queue_health
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    queue_backend, queue_ok = get_queue_health()
    return HealthResponse(
        status="ok",
        service="alde-webapp",
        timestamp=datetime.now(UTC),
        queue_backend=queue_backend,
        queue_ok=queue_ok,
    )
