"""Network diagnostic tools - 4 kinds.

ping, dns_lookup, port_check, http_test
"""

import json
import socket
import subprocess
import sys
import urllib.request
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM, TOOL_COMPILE_CHECK_TIMEOUT
from kernel.params import HTTP_TOOL_USER_AGENT
from kernel.platform import IS_NT, IS_WINDOWS


def _cmd_ping(args: dict, agent_id: str) -> dict:
    host = args.get("host", "")
    count = args.get("count", 4)
    if not host:
        return {"success": False, "error": "host is required"}
    try:
        param = "-n" if IS_WINDOWS else "-c"
        r = subprocess.run(["ping", param, str(count), host], capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        return {"success": r.returncode == 0, "data": {"output": r.stdout[-2048:], "host": host, "reachable": r.returncode == 0}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_dns_lookup(args: dict, agent_id: str) -> dict:
    host = args.get("host", "")
    if not host:
        return {"success": False, "error": "host is required"}
    try:
        addrs = socket.getaddrinfo(host, 80)
        ips = list(set(a[4][0] for a in addrs))
        return {"success": True, "data": {"host": host, "ips": ips, "count": len(ips)}}
    except socket.gaierror as e:
        return {"success": False, "error": f"DNS lookup failed: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_port_check(args: dict, agent_id: str) -> dict:
    host = args.get("host", "127.0.0.1")
    port = args.get("port", 80)
    timeout = args.get("timeout", 3)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        open_port = result == 0
        return {"success": True, "data": {"host": host, "port": port, "open": open_port, "service": _guess_service(port) if open_port else None}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _guess_service(port: int) -> str:
    services = {22: "SSH", 80: "HTTP", 443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis", 8080: "HTTP-Alt", 5000: "Flask", 5007: "Praxis"}
    return services.get(port, "unknown")


def _cmd_http_test(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    method = args.get("method", "GET")
    if not url:
        return {"success": False, "error": "url is required"}
    try:
        req = urllib.request.Request(url, method=method, headers={"User-Agent": HTTP_TOOL_USER_AGENT})
        with urllib.request.urlopen(req, timeout=TOOL_COMPILE_CHECK_TIMEOUT) as resp:
            content = resp.read().decode("utf-8", errors="replace")[:2048]
            return {"success": True, "data": {"url": url, "status": resp.status, "headers": dict(resp.headers), "body_preview": content[:500]}}
    except urllib.error.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}", "data": {"url": url, "status": e.code}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    register(ToolSpec(name="ping", description="Ping test network connectivity", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("host", "string", required=True), ParamSpec("count", "int", default=4)],
                      handler=_cmd_ping))
    register(ToolSpec(name="dns_lookup", description="DNS resolve domain to IP", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("host", "string", required=True)],
                      handler=_cmd_dns_lookup))
    register(ToolSpec(name="port_check", description="Check if port is open", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("host", "string", default="127.0.0.1"), ParamSpec("port", "int", default=80),
                                  ParamSpec("timeout", "int", default=3)],
                      handler=_cmd_port_check))
    register(ToolSpec(name="http_test", description="Send HTTP request to test endpoint", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("method", "string", default="GET")],
                      handler=_cmd_http_test))