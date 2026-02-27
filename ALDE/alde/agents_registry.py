from __future__ import annotations


# Maintainer contact: see repository README.

"""Agent registry.

This module must be safe to import (no side effects). It only defines
`AGENTS_REGISTRY` (agent configs: model, system prompt, tools).
"""

try:
    from .apply_agent_prompts import SYSTEM_PROMPT  # type: ignore
except Exception:
    from apply_agent_prompts import SYSTEM_PROMPT  # type: ignore

model = "gpt-4o-mini"

# Public registry consumed by agents_factory.execute_route_to_agent.
AGENTS_REGISTRY: dict[str, dict] = {
    "_primary_assistant": {
        "model": 'gpt-4o',
        "system": SYSTEM_PROMPT.get("_primary_assistant", ""),
        "tools": ["memorydb", "route_to_agent","@doc_rw"],
    },
    "_data_dispatcher": {
        "model": model,
        "system": SYSTEM_PROMPT.get("_data_dispatcher", ""),
        "tools": ["@dispatcher", "route_to_agent"],
    },
    "_job_posting_parser": {
        "model": model,
        "system": SYSTEM_PROMPT.get("_job_posting_parser", ""),
        "tools": ["@doc_rw", "route_to_agent"],
    },
    "_cover_letter_agent": {
        "model": 'gpt-4o',
        "system": SYSTEM_PROMPT.get("_cover_letter_agent", ""),
        "tools": ["@doc_rw", "route_to_agent"],
    },
}
