"""Quick health check for the local MCP stdio server.

- Reads alde/mcp_servers.json
- Starts the first stdio server entry
- Sends initialize and tools/list
- Prints basic status
"""

import json
import select
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path(__file__).with_name("mcp_servers.json")
DEFAULT_TIMEOUT = 5.0


def _load_config() -> Dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_line(proc: subprocess.Popen, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        raise TimeoutError("Timed out waiting for MCP server response")
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("MCP server closed pipe")
    return json.loads(line)


def main() -> int:
    cfg = _load_config()
    servers = cfg.get("servers", {})
    if not servers:
        print("No servers configured in mcp_servers.json")
        return 1

    name, server = next(iter(servers.items()))
    if server.get("type") != "stdio":
        print(f"Only stdio is supported in this health check (found {server.get('type')})")
        return 1

    cmd = [server.get("command", "python"), *server.get("args", [])]
    print(f"Starting MCP server '{name}' with: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        def send(payload: Dict[str, Any]) -> Dict[str, Any]:
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
            return _read_line(proc)

        init_resp = send({"method": "initialize", "params": {}})
        print("initialize ->", init_resp)

        list_resp = send({"method": "tools/list", "params": {}})
        tool_count = len(list_resp.get("result", {}).get("tools", [])) if "result" in list_resp else 0
        print(f"tools/list -> {tool_count} tools")

        ok = "result" in init_resp and "result" in list_resp
        return 0 if ok else 1

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Drain stderr for debugging if needed
        if proc.stderr:
            errs = proc.stderr.read().strip()
            if errs:
                print("[stderr]", errs)


if __name__ == "__main__":
    sys.exit(main())
