"""Debug tool_use native function calling."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

with open(os.path.join(os.path.dirname(__file__),"..","portal",".env"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip("\"'")

from l1.kernel.settings import get_settings

s = get_settings()
s.set_many({"llm.provider":"openai","llm.model":"deepseek-v4-flash",
            "llm.api_url":"https://api.deepseek.com/v1/chat/completions","llm.max_tokens":4096})

from l4.llm import ToolDef, get_engine, reset_engine

reset_engine()
engine = get_engine()

def tool_read(args, agent):
    path = args.get("path", "")
    full = os.path.join(os.path.dirname(__file__), path)
    try:
        with open(full, encoding="utf-8") as f:
            return {"success": True, "data": f.read()[:2000]}
    except Exception as e:
        return {"success": False, "error": str(e)}

tools = [ToolDef("read_file", "Read file", {
    "type": "object", "properties": {"path": {"type": "string"}},
    "required": ["path"]}, tool_read)]

import time

t0 = time.time()
r = engine.tool_use(
    prompt="Read src/kernel/__init__.py and tell me how many lines it has.",
    tools=tools,
    system="You are an agent. Use the read_file tool to answer.",
    max_turns=5,
)
t = time.time() - t0
print(f"Time: {t:.1f}s | Turns: {r.get('turns',0)}", flush=True)
print(f"Error: {r.get('error','none')}", flush=True)
print(f"Content: {r.get('content','')[:200]}", flush=True)
for tc in r.get("tool_calls", []):
    print(f"  Tool: {tc.get('name','')} args={tc.get('arguments',{})}", flush=True)
