# MCP (Local stdio) – Quickstart

This folder ships a minimal MCP stdio server wired to the unified tool registry.

## Files
- `alde/mcp_server.py` – stdio server exposing `initialize`, `tools/list`, `tools/call` and delegating to `execute_tool`.
- `alde/mcp_servers.json` – config for MCP clients; points to the local stdio server.
- `alde/mcp_health.py` – simple health check that starts the stdio server and runs `initialize` + `tools/list`.

## Run server
```bash
python alde/mcp_server.py
```
The server reads one JSON object per line on stdin and writes one JSON object per line on stdout.

## Health check
```bash
python alde/mcp_health.py
```
Expected: an `initialize` response with `serverInfo` and a `tools/list` response showing the available tools.

## Using with clients
- Point your MCP-aware client to `mcp_servers.json` and pick the `local-stdio` entry (transport: stdio).
- Each tool call must follow `{"method":"tools/call","params":{"name":"...","arguments":{...}}}`.

## Notes
- Tool schemas come from `agenszie_factory`’s unified tool registry; changes there are reflected automatically.
- The health script currently supports stdio only; extend if you add HTTP transports.
