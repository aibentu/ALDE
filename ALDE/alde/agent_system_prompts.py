from __future__ import annotations

"""Legacy prompt compatibility shim.

This module used to carry duplicated prompt definitions. The canonical prompt
source now lives in agents_config.py. Keep this module import-safe for older
callers and documentation examples that still import it.
"""

try:
    from .agents_config import (  # type: ignore
        SYSTEM_PROMPT,
        _SYSTEM_PROMPT,
        get_specialized_system_prompt,
        get_system_prompt,
    )
except Exception:
    from ALDE_Projekt.ALDE.alde.agents_configurator import (  # type: ignore
        SYSTEM_PROMPT,
        _SYSTEM_PROMPT,
        get_specialized_system_prompt,
        get_system_prompt,
    )


class AgentPromptService:
    """Compatibility service for resolving prompt objects by name."""

    def load_object(self, object_name: str) -> str:
        return get_system_prompt(object_name)

    def load_specialized_object(self, object_name: str, task_name: str) -> str:
        return get_specialized_system_prompt(object_name, task_name)


PROMPT_SERVICE = AgentPromptService()


def get_prompt(agent_name: str) -> str:
    return PROMPT_SERVICE.load_object(agent_name)


def get_specialized_prompt(agent_type: str, task_name: str) -> str:
    return PROMPT_SERVICE.load_specialized_object(agent_type, task_name)


__all__ = [
    "AgentPromptService",
    "PROMPT_SERVICE",
    "SYSTEM_PROMPT",
    "_SYSTEM_PROMPT",
    "get_prompt",
    "get_specialized_prompt",
    "get_specialized_system_prompt",
    "get_system_prompt",
]
