from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_principal
from ..schemas import AuditEventResponse
from ..security import Principal
from ..services import list_audit_events

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=list[AuditEventResponse])
def list_events(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(get_principal),
) -> list[AuditEventResponse]:
    rows = list_audit_events(tenant_id=principal.tenant_id, limit=limit)
    return [AuditEventResponse(**row) for row in rows]
