from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..authorization import ensure_agent_access, ensure_tool_access
from ..dependencies import get_principal
from ..jobs import JobMessage, submit_agent_job
from ..schemas import AgentRunRequest, AgentRunResponse, AgentRunStatusResponse, AsyncJobResponse, AsyncJobStatusResponse
from ..security import Principal
from ..services import get_job_status, get_run_status, queue_agent_run, run_agent

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/runs", response_model=AgentRunResponse, status_code=status.HTTP_202_ACCEPTED)
def run_agent_endpoint(req: AgentRunRequest, principal: Principal = Depends(get_principal)) -> AgentRunResponse:
    # Guardrail: ensure the caller can only submit runs in their own tenant context.
    if principal.role not in {"tenant_admin", "member"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    ensure_agent_access(principal=principal, target_agent=req.target_agent)
    ensure_tool_access(principal=principal, metadata=req.metadata)

    run = run_agent(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        target_agent=req.target_agent,
        prompt=req.prompt,
        metadata=req.metadata,
    )

    return AgentRunResponse(
        run_id=run.id,
        target_agent=run.target_agent,
        status=run.status,
        output=run.output,
        metadata=run.metadata,
        created_at=run.created_at,
    )


@router.post("/runs/async", response_model=AsyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
def run_agent_async(req: AgentRunRequest, principal: Principal = Depends(get_principal)) -> AsyncJobResponse:
    if principal.role not in {"tenant_admin", "member"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    ensure_agent_access(principal=principal, target_agent=req.target_agent)
    ensure_tool_access(principal=principal, metadata=req.metadata)

    job_id, run_id = queue_agent_run(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        target_agent=req.target_agent,
        prompt=req.prompt,
        metadata=req.metadata,
    )
    submit_agent_job(
        JobMessage(
            job_id=job_id,
            run_id=run_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            target_agent=req.target_agent,
            prompt=req.prompt,
            metadata=req.metadata,
        ),
    )
    return AsyncJobResponse(job_id=job_id, run_id=run_id, status="queued")


@router.get("/runs/{run_id}", response_model=AgentRunStatusResponse)
def get_run_endpoint(run_id: str, principal: Principal = Depends(get_principal)) -> AgentRunStatusResponse:
    run = get_run_status(tenant_id=principal.tenant_id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return AgentRunStatusResponse(
        run_id=run.id,
        status=run.status,
        output=run.output,
        metadata=run.metadata,
        created_at=run.created_at,
    )


@router.get("/jobs/{job_id}", response_model=AsyncJobStatusResponse)
def get_job_endpoint(job_id: str, principal: Principal = Depends(get_principal)) -> AsyncJobStatusResponse:
    job = get_job_status(tenant_id=principal.tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return AsyncJobStatusResponse(**job)
