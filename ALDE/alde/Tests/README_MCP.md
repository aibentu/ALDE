# MCP (TCP-first) – Quickstart

This setup ships a shared MCP request core and three transports:

- `local-tcp` (default)
- `local-http`
- `local-stdio` (fallback)

## Files
- `alde/mcp_server.py` – shared MCP request service + stdio transport.
- `alde/mcp_net_server.py` – TCP and HTTP MCP transport server.
- `alde/mcp_servers.json` – transport configs (`default_server` is `local-tcp`, `fallback_order` can route to `local-http`).
- `alde/mcp_health.py` – transport-aware health check (stdio/tcp/http) with fallback + metrics.

## Run servers
TCP (default)
```bash
python3 -m ALDE.alde.mcp_net_server --transport tcp --host 127.0.0.1 --port 8765
```

HTTP
```bash
python3 -m ALDE.alde.mcp_net_server --transport http --host 127.0.0.1 --port 8766
```

stdio fallback
```bash
python3 -m ALDE.alde.mcp_server
```

## Health check
```bash
python3 alde/mcp_health.py
```

The probe resolves `default_server` from `mcp_servers.json` (or `ALDE_MCP_DEFAULT_SERVER`) and validates `initialize` + `tools/list`.

It emits a machine-readable line for control-plane projection:

`MCP_PROBE_JSON={...}`

## Using with clients
- Prefer `local-tcp` for internal low-latency service-style integration.
- Use `local-http` for HTTP-native clients.
- Keep `local-stdio` for tooling environments that require stdio MCP.
