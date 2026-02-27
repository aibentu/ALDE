from __future__ import annotations

import json
from typing import Any


class MCPLambdaHandler:
    def __init__(self, name: str | None = None, version: str | None = None) -> None:
        self.name = name
        self.version = version
        self.tools: dict[str, dict[str, Any]] = {}
        self.tool_implementations: dict[str, Any] = {}

    def tool(self):
        def decorator(func):
            tool_name = func.__name__.upper()
            self.tools[tool_name] = {
                "name": tool_name,
                "description": func.__doc__ or "",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
            self.tool_implementations[tool_name] = func
            return func
        return decorator

    def handle_request(self, event: dict[str, Any], context: Any) -> dict[str, Any]:
        body = event.get("body") or "{}"

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}

        method = payload.get("method")
        params = payload.get("params", {})

        if method == "initialize":
            return self._response({"result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": self.name}}})
        if method == "tools/list":
            return self._response({"result": {"tools": list(self.tools.values())}})
        if method == "tools/call":
            name = params.get("name")
            if not name:
                return self._response({"error": "Missing tool name"}, status=400)
            tool = self.tool_implementations.get(name)
            if not tool:
                return self._response({"error": f"Unknown tool {name}"}, status=404)
            args = params.get("arguments", {})
            result = tool(**args)
            return self._response({"result": {"content": result}})

        return self._response({"error": "method_not_implemented"}, status=501)
    def _response(self, payload: dict[str, Any], status: int = 200) -> dict[str, Any]:
        return {"statusCode": status, "body": json.dumps(payload)}
