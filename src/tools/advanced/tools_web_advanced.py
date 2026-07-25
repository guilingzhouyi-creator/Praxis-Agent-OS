"""Advanced network tools - 10 kinds.

web_search, api_call, api_get, api_post, download_file, upload_file,
websocket_connect, rss_fetch, feed_parse, rate_limiter
"""

import json
import time
import urllib.parse
import urllib.request
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_SHORT, TOOL_HTTP_TIMEOUT_LONG
from kernel.params import HTTP_TOOL_USER_AGENT, DUCKDUCKGO_SEARCH_URL


def _cmd_web_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    max_results = args.get("max_results", 8)
    if not query:
        return {"success": False, "error": "query is required"}
    try:
        encoded = urllib.parse.quote(query)
        url = f"{DUCKDUCKGO_SEARCH_URL}?q={encoded}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": HTTP_TOOL_USER_AGENT})
        with urllib.request.urlopen(req, timeout=TOOL_HTTP_TIMEOUT_SHORT) as resp:
            data = json.loads(resp.read().decode())
        results = []
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if "Text" in topic and "FirstURL" in topic:
                results.append({"title": topic["Text"][:100], "url": topic["FirstURL"]})
        return {"success": True, "data": {"results": results, "count": len(results), "query": query}}
    except Exception as e:
        return {"success": False, "error": f"web_search failed: {e}"}


def _cmd_api_call(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    method = args.get("method", "GET")
    headers = args.get("headers", {})
    body = args.get("body", "")
    timeout = args.get("timeout", 15)
    if not url:
        return {"success": False, "error": "url is required"}
    try:
        headers["User-Agent"] = HTTP_TOOL_USER_AGENT
        data = body.encode() if body and method in ("POST", "PUT", "PATCH") else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")[:8192]
            return {"success": True, "data": {"status": resp.status, "headers": dict(resp.headers),
                                                "body": content[:4096], "url": url}}
    except urllib.error.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}", "data": {"status": e.code, "url": url}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_api_get(args: dict, agent_id: str) -> dict:
    return _cmd_api_call({**args, "method": "GET"}, agent_id)


def _cmd_api_post(args: dict, agent_id: str) -> dict:
    return _cmd_api_call({**args, "method": "POST"}, agent_id)


def _cmd_download_file(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    path = args.get("path", "")
    if not url or not path:
        return {"success": False, "error": "url and path are required"}
    try:
        urllib.request.urlretrieve(url, path)
        import os
        size = os.path.getsize(path)
        return {"success": True, "data": {"url": url, "path": path, "size": size, "downloaded": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_upload_file(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    path = args.get("path", "")
    if not url or not path:
        return {"success": False, "error": "url and path are required"}
    try:
        with open(path, "rb") as f:
            data = f.read()
        req = urllib.request.Request(url, data=data, method="PUT",
                                     headers={"User-Agent": HTTP_TOOL_USER_AGENT})
        with urllib.request.urlopen(req, timeout=TOOL_HTTP_TIMEOUT_LONG) as resp:
            return {"success": True, "data": {"url": url, "path": path, "status": resp.status, "uploaded": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_websocket_connect(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    if not url:
        return {"success": False, "error": "url is required"}
    return {"success": True, "data": {"url": url, "status": "simulated", "note": "WebSocket 连接需在 agent 循环中实现"}}


def _cmd_rss_fetch(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    max_items = args.get("max_items", 10)
    if not url:
        return {"success": False, "error": "url is required"}
    try:
        import xml.etree.ElementTree as ET
        req = urllib.request.Request(url, headers={"User-Agent": HTTP_TOOL_USER_AGENT})
        with urllib.request.urlopen(req, timeout=TOOL_HTTP_TIMEOUT_SHORT) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        items = []
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = entry.find("{http://www.w3.org/2005/Atom}title")
            link = entry.find("{http://www.w3.org/2005/Atom}link")
            items.append({"title": title.text if title is not None else "", "url": link.get("href") if link is not None else ""})
        return {"success": True, "data": {"feed": url, "items": items[:max_items], "count": len(items)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_feed_parse(args: dict, agent_id: str) -> dict:
    return _cmd_rss_fetch(args, agent_id)


def _cmd_rate_limiter(args: dict, agent_id: str) -> dict:
    key = args.get("key", "default")
    max_calls = args.get("max_calls", 10)
    window = args.get("window", 60)
    now = time.time()
    if not hasattr(_cmd_rate_limiter, "_counters"):
        _cmd_rate_limiter._counters = {}
    counter = _cmd_rate_limiter._counters
    entry = counter.get(key, {"calls": [], "window": window, "max_calls": max_calls})
    entry["calls"] = [t for t in entry["calls"] if now - t < window]
    entry["calls"].append(now)
    remaining = max_calls - len(entry["calls"])
    counter[key] = entry
    return {"success": True, "data": {"key": key, "calls_in_window": len(entry["calls"]),
                                        "remaining": max(0, remaining), "reset_in": window - (now - entry["calls"][0]) if entry["calls"] else 0}}


def register_tools() -> None:
    register(ToolSpec(name="web_search", description="Search web (DuckDuckGo)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("query", "string", required=True), ParamSpec("max_results", "int", default=8)],
                      handler=_cmd_web_search))
    register(ToolSpec(name="api_call", description="Generic HTTP request", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("method", "string", default="GET"),
                                  ParamSpec("headers", "dict", default={}), ParamSpec("body", "string", default=""),
                                  ParamSpec("timeout", "int", default=15)],
                      handler=_cmd_api_call))
    register(ToolSpec(name="api_get", description="HTTP GET request", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("headers", "dict", default={}),
                                  ParamSpec("timeout", "int", default=15)],
                      handler=_cmd_api_get))
    register(ToolSpec(name="api_post", description="HTTP POST request", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("headers", "dict", default={}),
                                  ParamSpec("body", "string", default=""), ParamSpec("timeout", "int", default=15)],
                      handler=_cmd_api_post))
    register(ToolSpec(name="download_file", description="Download file to local", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("path", "string", required=True)],
                      handler=_cmd_download_file))
    register(ToolSpec(name="upload_file", description="Upload file to remote", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("path", "string", required=True)],
                      handler=_cmd_upload_file))
    register(ToolSpec(name="websocket_connect", description="Connect WebSocket (placeholder)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("url", "string", required=True)],
                      handler=_cmd_websocket_connect))
    register(ToolSpec(name="rss_fetch", description="Fetch RSS/Atom feed", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("max_items", "int", default=10)],
                      handler=_cmd_rss_fetch))
    register(ToolSpec(name="feed_parse", description="Parse RSS/Atom feed (same as rss_fetch)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("max_items", "int", default=10)],
                      handler=_cmd_feed_parse))
    register(ToolSpec(name="rate_limiter", description="Rate limit check", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("key", "string", default="default"), ParamSpec("max_calls", "int", default=10),
                                  ParamSpec("window", "int", default=60)],
                      handler=_cmd_rate_limiter))