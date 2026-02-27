from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(slots=True)
class Tenant:
    slug: str
    name: str
    id: str = field(default_factory=lambda: _new_id("ten"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class User:
    tenant_id: str
    subject: str
    email: str
    display_name: str
    role: str
    id: str = field(default_factory=lambda: _new_id("usr"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class AgentRun:
    tenant_id: str
    user_id: str
    target_agent: str
    prompt: str
    status: str
    output: str
    metadata: dict[str, Any]
    id: str = field(default_factory=lambda: _new_id("run"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
