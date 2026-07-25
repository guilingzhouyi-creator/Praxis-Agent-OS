"""SubAgent Framework — @mention 调度 + 隔离执行 + 结果归并

架构:
  SubAgentFramework (services/subagent_framework.py)
  ├── SubAgentSpec         — 子代理定义（角色/工具集/模型/超时）
  ├── SubAgentTask         — 子代理任务实例（独立 session + context）
  ├── SubAgentDispatcher   — @mention 解析 + 任务调度 + 生命周期
  ├── ResultMerger         — 多子代理结果冲突检测 + 合并
  └── API Handlers

API:
  POST /api/subagent/dispatch       — 调度子代理
  GET  /api/subagent/:id/result     — 获取子代理结果
  DELETE /api/subagent/:id          — 终止子代理
  GET  /api/subagent/specs          — 列出子代理规格
  POST /api/subagent/spec           — 注册子代理规格
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 1. 子代理规格
# ══════════════════════════════════════════════════════════════════════


@dataclass
class SubAgentSpec:
    """子代理规格定义。"""
    name: str                     # @mention 名称, e.g. "security-auditor"
    description: str              # 描述（LLM 知道何时调用）
    system_prompt: str = ""       # 角色系统 prompt
    allowed_tools: list[str] = field(default_factory=lambda: ["read_file", "grep_search"])
    model: str = ""               # 留空用默认模型
    max_steps: int = 5
    timeout: float = 60.0
    read_only: bool = True        # 默认只读
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description[:100],
            "allowed_tools": self.allowed_tools,
            "model": self.model,
            "max_steps": self.max_steps,
            "timeout": self.timeout,
            "read_only": self.read_only,
            "tags": self.tags,
        }


# 内置子代理规格
BUILTIN_SUBAGENTS: dict[str, SubAgentSpec] = {
    "security-auditor": SubAgentSpec(
        name="security-auditor",
        description="Audit code for security vulnerabilities (XSS, injection, secrets)",
        system_prompt="You are a security expert. Review code for vulnerabilities. Report findings with CVE references.",
        allowed_tools=["read_file", "grep_search", "search_symbol"],
        tags=["security", "audit"],
    ),
    "debugger": SubAgentSpec(
        name="debugger",
        description="Debug errors and trace root causes",
        system_prompt="You are a debugging specialist. Analyze stack traces, find root causes, suggest fixes.",
        allowed_tools=["read_file", "grep_search", "stack_trace", "run_in_terminal"],
        max_steps=10,
        timeout=120.0,
        tags=["debug", "troubleshoot"],
    ),
    "code-reviewer": SubAgentSpec(
        name="code-reviewer",
        description="Review code quality and suggest improvements",
        system_prompt="You are a senior code reviewer. Focus on logic errors, edge cases, and maintainability.",
        allowed_tools=["read_file", "grep_search", "search_symbol"],
        tags=["review", "quality"],
    ),
    "scout": SubAgentSpec(
        name="scout",
        description="Explore codebase and gather information",
        system_prompt="You are a scout. Explore the codebase and summarize findings concisely.",
        allowed_tools=["read_file", "grep_search", "list_directory", "search_symbol"],
        max_steps=3,
        timeout=30.0,
        tags=["explore", "research"],
    ),
}


# ══════════════════════════════════════════════════════════════════════
# 2. 子代理任务
# ══════════════════════════════════════════════════════════════════════


class SubAgentTask:
    """单个子代理任务实例。"""

    def __init__(self, task_id: str, spec: SubAgentSpec,
                 prompt: str, parent_agent_id: str = "",
                 context: dict | None = None):
        self.id = task_id
        self.spec = spec
        self.prompt = prompt
        self.parent_agent_id = parent_agent_id
        self.context = context or {}
        self.status: str = "pending"   # pending | running | completed | failed | cancelled
        self.result: dict = {}
        self.started_at: float = 0
        self.completed_at: float = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._cancelled = False

    def start(self) -> dict:
        """在独立线程中执行子代理任务。"""
        with self._lock:
            self.status = "running"
            self.started_at = time.time()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return {"success": True, "task_id": self.id, "spec": self.spec.name}

    def _run(self) -> None:
        """子代理执行体 — 使用 LLM engine 的简化循环。"""
        try:
            from services.llm import get_engine
            engine = get_engine()

            # 构建简单的 system prompt
            system = self.spec.system_prompt or (
                f"You are {self.spec.name}. {self.spec.description}"
            )

            # 限制工具列表
            available_tools = None
            try:
                from services.tool_spec import TOOL_REGISTRY
                available_tools = [
                    t for name, t in TOOL_REGISTRY.items()
                    if name in self.spec.allowed_tools
                ]
            except Exception:
                pass

            if self.spec.read_only:
                system += "\n\nYou are in READ-ONLY mode. Do NOT modify any files."

            result = engine.generate(
                prompt=self.prompt,
                system=system,
                max_tokens=4096,
                user_id=self.parent_agent_id or self.id,
            )

            with self._lock:
                if self._cancelled:
                    self.status = "cancelled"
                    return
                self.status = "completed"
                self.completed_at = time.time()
                self.result = result

        except Exception as e:
            with self._lock:
                self.status = "failed"
                self.completed_at = time.time()
                self.result = {"error": str(e)}

    def cancel(self) -> dict:
        with self._lock:
            self._cancelled = True
            if self.status != "running":
                self.status = "cancelled"
                return {"success": True, "task_id": self.id, "status": "cancelled"}
            self.status = "cancelled"
        return {"success": True, "task_id": self.id, "status": "cancelled"}

    def get_result(self) -> dict:
        with self._lock:
            elapsed = 0
            if self.started_at > 0:
                elapsed = (self.completed_at or time.time()) - self.started_at

            return {
                "success": True,
                "task_id": self.id,
                "spec": self.spec.name,
                "status": self.status,
                "prompt": self.prompt[:100],
                "result": self.result,
                "elapsed_seconds": round(elapsed, 1),
                "started_at": self.started_at,
                "completed_at": self.completed_at,
            }


# ══════════════════════════════════════════════════════════════════════
# 3. 调度器
# ══════════════════════════════════════════════════════════════════════


class SubAgentDispatcher:
    """子代理调度器 — @mention 解析 + 任务调度 + 生命周期。"""

    # @mention 正则: "@agent-name rest of prompt"
    MENTION_RE = re.compile(r"@(\w[\w-]*)\s*(.*)", re.DOTALL)

    def __init__(self):
        self._specs: dict[str, SubAgentSpec] = dict(BUILTIN_SUBAGENTS)
        self._tasks: dict[str, SubAgentTask] = {}
        self._lock = threading.RLock()

    def parse_mentions(self, text: str) -> list[tuple[str, str, str]]:
        """解析文本中的 @mention。

        Returns:
            [(mention_name, full_text_before_rest, remaining_text), ...]
        """
        results = []
        remaining = text.strip()
        while remaining:
            m = self.MENTION_RE.match(remaining)
            if m:
                name = m.group(1)
                rest = m.group(2).strip()
                if name in self._specs:
                    results.append((name, remaining[:m.start()], rest))
                    remaining = rest
                    continue
            break
        return results

    def dispatch(self, spec_name: str, prompt: str,
                 parent_agent_id: str = "",
                 context: dict | None = None) -> dict:
        """调度一个子代理任务。"""
        with self._lock:
            spec = self._specs.get(spec_name)
            if not spec:
                return {"success": False, "error": f"unknown subagent: {spec_name}"}

            task_id = f"sub-{uuid.uuid4().hex[:12]}"
            task = SubAgentTask(
                task_id=task_id,
                spec=spec,
                prompt=prompt,
                parent_agent_id=parent_agent_id,
                context=context,
            )
            self._tasks[task_id] = task

        return task.start()

    def dispatch_from_text(self, text: str, parent_agent_id: str = "") -> dict:
        """从文本自动解析 @mention 并调度。"""
        mentions = self.parse_mentions(text)
        if not mentions:
            return {"success": False, "error": "no @mention found"}

        results = []
        for name, before, rest in mentions:
            r = self.dispatch(name, rest, parent_agent_id)
            results.append(r)

        return {"success": True, "dispatched": len(results), "results": results}

    def get_task(self, task_id: str) -> SubAgentTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> dict:
        task = self.get_task(task_id)
        if not task:
            return {"success": False, "error": f"task not found: {task_id}"}
        return task.cancel()

    def list_tasks(self, status: str = "") -> list[dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [t.get_result() for t in tasks]

    def register_spec(self, spec: SubAgentSpec) -> dict:
        with self._lock:
            self._specs[spec.name] = spec
        return {"success": True, "spec": spec.to_dict()}

    def list_specs(self) -> dict:
        with self._lock:
            return {
                "success": True,
                "count": len(self._specs),
                "specs": {n: s.to_dict() for n, s in self._specs.items()},
            }


# ══════════════════════════════════════════════════════════════════════
# 4. 结果归并器
# ══════════════════════════════════════════════════════════════════════


class ResultMerger:
    """多子代理结果归并 — 冲突检测 + 合并摘要。"""

    @staticmethod
    def merge(results: list[dict]) -> dict:
        """归并多个子代理的结果。"""
        completed = [r for r in results if r.get("status") == "completed"]
        failed = [r for r in results if r.get("status") == "failed"]

        contents = []
        for r in completed:
            content = r.get("result", {}).get("content", "")
            if content:
                contents.append(f"=== {r.get('spec', '?')} ===\n{content[:500]}")

        summary = "\n\n".join(contents) if contents else "(no content)"

        # 冲突检测：当多个子代理对同一主题给出不同结论
        conflicts = ResultMerger._detect_conflicts(completed)

        return {
            "success": True,
            "total": len(results),
            "completed": len(completed),
            "failed": len(failed),
            "summary": summary,
            "conflicts": conflicts,
            "has_conflicts": len(conflicts) > 0,
            "individual_results": results,
        }

    @staticmethod
    def _detect_conflicts(results: list[dict]) -> list[dict]:
        """简单的关键词级别冲突检测。"""
        if len(results) < 2:
            return []

        conflicts = []
        # 比较每对结果
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                a = results[i].get("result", {}).get("content", "")
                b = results[j].get("result", {}).get("content", "")
                if not a or not b:
                    continue

                # 检查是否一方说 "safe" 另一方说 "vulnerable"
                a_lower = a.lower()
                b_lower = b.lower()
                if ("safe" in a_lower and "vulnerable" in b_lower) or \
                   ("vulnerable" in a_lower and "safe" in b_lower):
                    conflicts.append({
                        "type": "verdict_conflict",
                        "between": [results[i].get("spec"), results[j].get("spec")],
                        "detail": "One says safe, the other says vulnerable",
                    })

        return conflicts


# ══════════════════════════════════════════════════════════════════════
# 5. 全局单例
# ══════════════════════════════════════════════════════════════════════

_dispatcher: SubAgentDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_dispatcher() -> SubAgentDispatcher:
    global _dispatcher
    if _dispatcher is None:
        with _dispatcher_lock:
            if _dispatcher is None:
                _dispatcher = SubAgentDispatcher()
    return _dispatcher


# ══════════════════════════════════════════════════════════════════════
# 6. API Handlers
# ══════════════════════════════════════════════════════════════════════


def handle_subagent_dispatch(body: dict | None = None) -> dict:
    """POST /api/subagent/dispatch — 调度子代理"""
    b = body or {}
    spec_name = b.get("spec", "")
    prompt = b.get("prompt", "")
    text = b.get("text", "")
    parent = b.get("parent_agent_id", "")

    if text:
        return get_dispatcher().dispatch_from_text(text, parent)

    if not spec_name or not prompt:
        return {"success": False, "error": "spec+prompt or text required"}
    return get_dispatcher().dispatch(spec_name, prompt, parent)


def handle_subagent_result(body: dict | None = None) -> dict:
    """POST /api/subagent/result — 获取子代理结果"""
    b = body or {}
    task_id = b.get("task_id", "")
    if not task_id:
        return {"success": False, "error": "task_id required"}
    task = get_dispatcher().get_task(task_id)
    if not task:
        return {"success": False, "error": f"task not found: {task_id}"}
    return task.get_result()


def handle_subagent_cancel(body: dict | None = None) -> dict:
    """POST /api/subagent/cancel — 终止子代理"""
    b = body or {}
    task_id = b.get("task_id", "")
    if not task_id:
        return {"success": False, "error": "task_id required"}
    return get_dispatcher().cancel_task(task_id)


def handle_subagent_list(body: dict | None = None) -> dict:
    """POST /api/subagent/tasks — 列出子代理任务"""
    b = body or {}
    status = b.get("status", "")
    return {"success": True, "tasks": get_dispatcher().list_tasks(status=status)}


def handle_subagent_specs(body: dict | None = None) -> dict:
    """GET /api/subagent/specs — 列出子代理规格"""
    return get_dispatcher().list_specs()


def handle_subagent_spec_register(body: dict | None = None) -> dict:
    """POST /api/subagent/spec — 注册子代理规格"""
    b = body or {}
    name = b.get("name", "")
    desc = b.get("description", "")
    if not name or not desc:
        return {"success": False, "error": "name and description required"}
    spec = SubAgentSpec(
        name=name,
        description=desc,
        system_prompt=b.get("system_prompt", ""),
        allowed_tools=b.get("allowed_tools", ["read_file", "grep_search"]),
        model=b.get("model", ""),
        max_steps=b.get("max_steps", 5),
        timeout=b.get("timeout", 60.0),
        read_only=b.get("read_only", True),
        tags=b.get("tags", []),
    )
    return get_dispatcher().register_spec(spec)


def handle_subagent_merge(body: dict | None = None) -> dict:
    """POST /api/subagent/merge — 归并多个子代理结果"""
    b = body or {}
    task_ids = b.get("task_ids", [])
    if not task_ids:
        return {"success": False, "error": "task_ids required"}

    results = []
    for tid in task_ids:
        task = get_dispatcher().get_task(tid)
        if task:
            results.append(task.get_result())

    return ResultMerger.merge(results)


# ── 路由注册 ──

SUBAGENT_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/subagent/dispatch", handle_subagent_dispatch, "Dispatch subagent (@mention or spec+prompt)"),
    ("POST", "/api/subagent/result", handle_subagent_result, "Get subagent task result"),
    ("POST", "/api/subagent/cancel", handle_subagent_cancel, "Cancel subagent task"),
    ("POST", "/api/subagent/tasks", handle_subagent_list, "List subagent tasks"),
    ("GET", "/api/subagent/specs", handle_subagent_specs, "List subagent specs"),
    ("POST", "/api/subagent/spec", handle_subagent_spec_register, "Register subagent spec"),
    ("POST", "/api/subagent/merge", handle_subagent_merge, "Merge multiple subagent results"),
]
