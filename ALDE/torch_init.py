from __future__ import annotations

"""Proxy to the alde torch initialization helpers."""

from alde.torch_init import init_torch_cuda, summarize_torch_environment, select_device  # noqa: E402

__all__ = ["init_torch_cuda", "summarize_torch_environment", "select_device"]
