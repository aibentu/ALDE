"""
Minimal MCP stdio server exposing the unified tool registry.

Methods handled:
- initialize
- tools/list
- tools/call

Transport: stdio (one JSON object per line).
"""

import json
import sys
from typing import Any, Dict

try:
    from .agents_factory import tool_registry, execute_tool  # type: ignore
except Exception:
    from alde.agents_factory import tool_registry, execute_tool  # type: ignore


def _safe_serialize(obj: Any) -> Any:
    """Best-effort serialization; fallback to string for non-serializable objects."""
    try:
        json.dumps(obj)
        return obj
    except Exception:
        try:
            return str(obj)
        except Exception:
            return "<unserializable>"


def _response(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _handle_initialize(params: Dict[str, Any]) -> None:
    _response({"result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": "alde-local-mcp"}}})


def _handle_tools_list(params: Dict[str, Any]) -> None:
    tools = []
    for name, spec in tool_registry.items():
        tools.append(_safe_serialize(spec))
    _response({"result": {"tools": tools}})


def _handle_tools_call(params: Dict[str, Any]) -> None:
    name = params.get("name")
    if not name:
        _response({"error": "Missing tool name"})
        return

    args = params.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}

    try:
        result, route_req = execute_tool(name, args, params.get("id"))
        payload: Dict[str, Any] = {"content": _safe_serialize(result)}
        if route_req:
            payload["route_request"] = _safe_serialize(route_req)
        _response({"result": payload})
    except Exception as exc:  # noqa: BLE001
        _response({"error": f"tool_error: {exc}"})


def main() -> None:
    handlers = {
        "initialize": _handle_initialize,
        "tools/list": _handle_tools_list,
        "tools/call": _handle_tools_call,
    }

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            _response({"error": "invalid_json"})
            continue

        method = payload.get("method")
        params = payload.get("params", {})

        handler = handlers.get(method)
        if not handler:
            _response({"error": "method_not_implemented"})
            continue

        handler(params)


if __name__ == "__main__":
    main()