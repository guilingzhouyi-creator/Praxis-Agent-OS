"""LLM integration tools - 4 kinds.

llm_chat, llm_complete, llm_embed, llm_classify
"""

import json
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R


def _cmd_llm_chat(args: dict, agent_id: str) -> dict:
    prompt = args.get("prompt", "")
    model = args.get("model", "deepseek-v4")
    if not prompt:
        return {"success": False, "error": "prompt is required"}
    return {
        "success": True,
        "data": {
            "model": model,
            "response": f"[LLM chat] 模型 {model} 收到提示: {prompt[:50]}... (需要 LLM API 密钥配置)",
            "tokens": len(prompt.split()),
            "note": "LLM API 调用需要在 Praxis 配置中设置 API key",
        },
    }


def _cmd_llm_complete(args: dict, agent_id: str) -> dict:
    code = args.get("code", "")
    language = args.get("language", "python")
    if not code:
        return {"success": False, "error": "code is required"}
    return {
        "success": True,
        "data": {
            "language": language,
            "completion": f"# 代码补全 ({language})\n{code}\n# 需要 LLM API 集成完成实际补全",
            "note": "LLM API 调用需要在 Praxis 配置中设置 API key",
        },
    }


def _cmd_llm_embed(args: dict, agent_id: str) -> dict:
    text = args.get("text", "")
    if not text:
        return {"success": False, "error": "text is required"}
    return {
        "success": True,
        "data": {
            "dimension": 1536,
            "vector_preview": [0.0] * 5,
            "note": "需要 embedding API 集成完成实际向量化",
        },
    }


def _cmd_llm_classify(args: dict, agent_id: str) -> dict:
    text = args.get("text", "")
    categories = args.get("categories", ["bug", "feature", "docs", "refactor"])
    if not text:
        return {"success": False, "error": "text is required"}
    return {
        "success": True,
        "data": {
            "text": text[:100],
            "categories": categories,
            "classification": "uncategorized",
            "confidence": 0.0,
            "note": "需要 LLM API 集成完成实际分类",
        },
    }


def register_tools() -> None:
    register(ToolSpec(name="llm_chat", description="LLM chat (requires API key)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("prompt", "string", required=True), ParamSpec("model", "string", default="deepseek-v4")],
                      handler=_cmd_llm_chat))
    register(ToolSpec(name="llm_complete", description="LLM code completion (requires API key)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("code", "string", required=True), ParamSpec("language", "string", default="python")],
                      handler=_cmd_llm_complete))
    register(ToolSpec(name="llm_embed", description="LLM text embedding (requires API key)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("text", "string", required=True)],
                      handler=_cmd_llm_embed))
    register(ToolSpec(name="llm_classify", description="LLM text classification (requires API key)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("text", "string", required=True), ParamSpec("categories", "list", default=["bug", "feature", "docs", "refactor"])],
                      handler=_cmd_llm_classify))