from __future__ import annotations

"""Compatibility shim for legacy imports.

Historically, callers imported symbols from `agents_configurator`.
The canonical implementation now lives in `agents_config`.
"""

from .agents_config import *  # noqa: F401,F403
