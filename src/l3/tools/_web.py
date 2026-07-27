"""Web tool handlers."""

try:
    import urllib.request as req
    import urllib.error
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

from l1.kernel.params.tool import TOOL_WEB_TIMEOUT


def web_fetch(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    if not url:
        return {"success": False, "error": "url is required"}
    if not HAS_URLLIB:
        return {"success": False, "error": "urllib not available"}
    try:
        r = req.urlopen(url, timeout=TOOL_WEB_TIMEOUT)
        content = r.read().decode("utf-8", errors="replace")
        return {"success": True, "data": content[:10000], "url": url, "truncated": len(content) > 10000}
    except Exception as e:
        return {"success": False, "error": str(e)}


def web_search(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "query is required"}
    if not HAS_URLLIB:
        return {"success": False, "error": "urllib not available"}
    try:
        # Delegate to web_fetch instead of inline DuckDuckGo HTML parsing
        fetch = web_fetch({"url": "https://duckduckgo.com/html/?q=" + req.quote(query)}, agent_id)
        if not fetch.get("success"):
            return fetch
        content = fetch.get("data", "")
        import re
        results = re.findall(r'<a rel="nofollow" href="([^"]+)"[^>]*>([^<]+)</a>', content)
        items = [{"title": t, "url": u} for u, t in results[:10]]
        return {"success": True, "results": items, "query": query}
    except Exception as e:
        return {"success": False, "error": str(e)}
