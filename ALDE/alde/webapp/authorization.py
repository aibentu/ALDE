from __future__ import annotations

from fastapi import HTTPException, status

from .config import settings
from .security import Principal


def _parse_csv(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def ensure_agent_access(*, principal: Principal, target_agent: str) -> None:
    if principal.role == "tenant_admin":
        return

    if principal.role != "member":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role not allowed")

    allowed = _parse_csv(settings.rbac_member_agents)
    if target_agent not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Agent '{target_agent}' not allowed for role '{principal.role}'",
        )


def ensure_tool_access(*, principal: Principal, metadata: dict) -> None:
    requested_tools = metadata.get("requested_tools") if isinstance(metadata, dict) else None
    if not isinstance(requested_tools, list):
        return

    requested = {str(t).strip() for t in requested_tools if str(t).strip()}
    if not requested:
        return

    if principal.role == "tenant_admin":
        return

    allowed = _parse_csv(settings.rbac_member_tools)
    if not requested.issubset(allowed):
        denied = sorted(requested - allowed)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tools not allowed for role '{principal.role}': {', '.join(denied)}",
        )
