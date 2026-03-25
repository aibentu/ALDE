from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: datetime
    queue_backend: str | None = None
    queue_ok: bool | None = None


class TenantRegisterRequest(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    admin_email: str
    admin_display_name: str = Field(min_length=2, max_length=128)


class TenantResponse(BaseModel):
    id: str
    slug: str
    name: str
    created_at: datetime


class UserResponse(BaseModel):
    id: str
    tenant_id: str
    subject: str
    email: str
    display_name: str
    role: str
    created_at: datetime


class SSOLoginRequest(BaseModel):
    tenant_slug: str
    provider: str = Field(default="keycloak")
    subject: str = Field(min_length=3, max_length=256)
    email: str
    display_name: str = Field(min_length=2, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int
    tenant_id: str
    user_id: str
    refresh_token: str | None = None
    refresh_expires_at: int | None = None


class OIDCStartRequest(BaseModel):
    tenant_slug: str


class OIDCStartResponse(BaseModel):
    authorization_url: str
    state: str


class OIDCCallbackRequest(BaseModel):
    tenant_slug: str | None = None
    state: str
    code: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class AgentRunRequest(BaseModel):
    target_agent: str = Field(default="_primary_assistant", description="Target runtime agent label. Defaults to the planner/router entrypoint.")
    prompt: str = Field(min_length=1, description="User request or task payload forwarded into the selected runtime agent.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Tenant-side execution metadata used for RBAC, tracing, or pipeline context.")


class AgentRunResponse(BaseModel):
    run_id: str
    target_agent: str
    status: str
    output: str
    metadata: dict[str, Any]
    created_at: datetime


class AsyncJobResponse(BaseModel):
    job_id: str
    run_id: str
    status: str


class AsyncJobStatusResponse(BaseModel):
    job_id: str
    run_id: str | None
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class AgentRunStatusResponse(BaseModel):
    run_id: str
    status: str
    output: str
    metadata: dict[str, Any]
    created_at: datetime


class WorkflowValidationItem(BaseModel):
    name: str
    valid: bool
    errors: list[str]
    warnings: list[str]
    stats: dict[str, Any]


class WorkflowValidationResponse(BaseModel):
    valid: bool
    workflow_count: int
    valid_count: int
    invalid_count: int
    mapping_errors: list[str] = Field(default_factory=list)
    workflows: list[WorkflowValidationItem] = Field(default_factory=list)


class WorkflowStatusEntry(BaseModel):
    message_id: int | None = None
    role: str
    assistant_name: str | None = None
    thread_id: int | None = None
    thread_name: str | None = None
    time: str | None = None
    workflow: dict[str, Any]


class WorkflowStatusResponse(BaseModel):
    latest: WorkflowStatusEntry | None = None
    items: list[WorkflowStatusEntry] = Field(default_factory=list)
    validation: WorkflowValidationResponse
    error: str | None = None


class AuditEventResponse(BaseModel):
    id: int
    tenant_id: str
    user_id: str | None
    event_type: str
    detail: dict[str, Any]
    created_at: datetime
