from __future__ import annotations

"""Expose the server lambda entry point at the repository root for tests."""

from alpha_vantage_mcp.server.lambda_function import lambda_handler  # noqa: E402

__all__ = ["lambda_handler"]
