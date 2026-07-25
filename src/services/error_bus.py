"""ErrorBus — 统一错误日志总线

合流全项目 ~190 个异常捕获点，对外暴露 REST API 供前端消费。

三层架构:
  1. ErrorLogEntry — 带指纹去重的结构化错误记录（比 LogEntry 丰富）
  2. ErrorBus — 合流引擎，去重 + 写入 LogService + 推 EventBus + SSE
  3. API Handlers — 通过 ApiGateway 暴露 REST 端点

用法 — 一行替换所有 except 点:
    try:
        ...
    except Exception as e:
        capture("memory compact failed", exc=e, component="services")
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services._base import BaseService
from kernel.params import (
    ERROR_BUS_BUFFER,
    ERROR_BUS_DEDUP_WINDOW,
    ERROR_BUS_EXPORT_LIMIT,
)
from kernel.platform import get_config_dir

logger = logging.getLogger(__name__)

_LOG_DIR = Path(get_config_dir()) / "logs"


# ══════════════════════════════════════════════════════════════════════
# 1. Core data model
# ══════════════════════════════════════════════════════════════════════


@dataclass
class ErrorLogEntry:
    """结构化的错误日志条目 — 比通用 LogEntry 更丰富。

    相比 services/log.py 的 LogEntry 增加了:
      - error_code: 统一错误码（与 kernel/errors.py 联动）
      - component:  组件分层 (kernel / services / tools / api / cli)
      - source:     源码位置 (file:line)
      - stack_trace:异常堆栈
      - context:    附加键值对
      - fingerprint:去重指纹
      - count:      同一指纹累计出现次数
    """

    # ── 基础字段 ──
    level: str  # "ERROR" | "CRITICAL" | "WARN"
    service: str  # e.g. "kernel/allocator", "services/agent_loop"
    message: str
    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""
    task_id: str = ""

    # ── 错误专用字段 ──
    error_code: str = "E_INTERNAL"
    component: str = "kernel"  # kernel / services / tools / api / cli
    source: str = ""  # e.g. "kernel/allocator.py:77"
    stack_trace: str = ""
    context: dict = field(default_factory=dict)

    # ── 去重字段 ──
    fingerprint: str = ""
    count: int = 1

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = _compute_fingerprint(
                self.level, self.error_code, self.source, self.message,
            )

    def to_dict(self) -> dict:
        return {
            "id": self.fingerprint[:12],
            "level": self.level,
            "error_code": self.error_code,
            "component": self.component,
            "service": self.service,
            "message": self.message[:500],
            "source": self.source,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(
                self.timestamp, tz=timezone.utc
            ).isoformat(),
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "stack_trace": (self.stack_trace or "")[:1000],
            "context": self.context,
            "count": self.count,
        }


def _compute_fingerprint(
    level: str, error_code: str, source: str, message: str,
) -> str:
    """计算去重指纹 — sha256(level + error_code + source + message[:100]) → hex[:16]"""
    raw = f"{level}|{error_code}|{source}|{message[:100]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _caller_source(depth: int = 2) -> str:
    """自动推断调用位置 — 返回 'file.py:line'"""
    import inspect
    try:
        frame = inspect.currentframe()
        # 往上跳 depth 层: capture() → error() → caller()
        for _ in range(depth):
            if frame and frame.f_back:
                frame = frame.f_back
        if frame:
            return f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"
    except Exception:
        pass
    return "unknown"


def _format_exc(exc: Exception | None) -> str:
    """格式化异常堆栈，截断前 1000 字符"""
    if not exc:
        return ""
    lines = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return lines[:1000]


# ══════════════════════════════════════════════════════════════════════
# 2. ErrorBus — 合流引擎
# ══════════════════════════════════════════════════════════════════════


class ErrorBus(BaseService):
    """统一错误日志总线 — 合流入口、去重、查询、SSE。

    职责:
      1. ingest() 接收所有来源的错误 → 去重 → 写入 LogService + EventBus
      2. 维护环形缓冲区供快速查询
      3. 对外暴露 REST API 查询/统计接口
    """

    def __init__(self, max_entries: int = ERROR_BUS_BUFFER):
        super().__init__("error_bus")
        self._max_entries = max_entries
        self._buffer: deque[ErrorLogEntry] = deque(maxlen=max_entries)
        self._fingerprint_index: dict[str, ErrorLogEntry] = {}
        self._lock = threading.RLock()

        # SSE 客户端
        self._sse_clients: list[queue.Queue] = []
        self._sse_lock = threading.RLock()

        # 统计缓存
        self._stats_cache: dict = {}
        self._stats_ts: float = 0.0

    # ── Lifecycle ──

    def _on_start(self) -> dict:
        """启动时订阅 EventBus 错误事件"""
        try:
            from kernel import get_event_bus
            bus = get_event_bus()
            bus.on_event("error_log", self._on_error_event)
        except Exception as e:
            logger.warning("error_bus: event bus subscribe failed: %s", e)
        logger.info("error_bus started (max_entries=%d)", self._max_entries)
        return {"success": True, "max_entries": self._max_entries}

    def _on_stop(self) -> dict:
        # 关闭所有 SSE 连接
        with self._sse_lock:
            for q in self._sse_clients:
                q.put(None)  # 哨兵通知断开
            self._sse_clients.clear()
        return {"success": True}

    # ── 合流入口 ──

    def error(
        self,
        message: str,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """记录一条 ERROR 级别错误。

        自动合流到 LogService + EventBus + SSE。
        """
        return self._ingest(
            level="ERROR",
            message=message,
            error_code=error_code,
            component=component,
            service=service or component,
            source=source,
            stack_trace=stack_trace,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    def critical(
        self,
        message: str,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """记录一条 CRITICAL 级别错误。"""
        return self._ingest(
            level="CRITICAL",
            message=message,
            error_code=error_code,
            component=component,
            service=service or component,
            source=source,
            stack_trace=stack_trace,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    def warn(
        self,
        message: str,
        error_code: str = "",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """记录一条 WARN 级别警告。"""
        return self._ingest(
            level="WARN",
            message=message,
            error_code=error_code or "E_WARN",
            component=component,
            service=service or component,
            source=source,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    def exception(
        self,
        exc: Exception,
        message: str = "",
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """从 Exception 对象提取信息并记录。

        自动提取 stack_trace；若 source 为空则自动推断调用位置。
        """
        stack_trace = _format_exc(exc)
        _source = source or _caller_source(depth=3)
        _message = message or str(exc)[:200]
        return self.error(
            message=_message,
            error_code=error_code,
            component=component,
            service=service,
            source=_source,
            stack_trace=stack_trace,
            agent_id=agent_id,
            task_id=task_id,
            context=context or {},
        )

    # ── 内部合流逻辑 ──

    def _ingest(
        self,
        level: str,
        message: str,
        error_code: str,
        component: str,
        service: str,
        source: str,
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        entry = ErrorLogEntry(
            level=level,
            service=service,
            message=message,
            timestamp=time.time(),
            agent_id=agent_id,
            task_id=task_id,
            error_code=error_code,
            component=component,
            source=source,
            stack_trace=stack_trace,
            context=context or {},
        )

        with self._lock:
            # 去重
            existing = self._fingerprint_index.get(entry.fingerprint)
            if existing:
                existing.count += 1
                existing.timestamp = entry.timestamp  # 更新时间
                result_entry = existing
            else:
                self._buffer.append(entry)
                self._fingerprint_index[entry.fingerprint] = entry
                result_entry = entry
                # 淘汰旧的指纹（buffer 满时 deque 自动淘汰）
                if len(self._buffer) == self._max_entries:
                    # 清理被淘汰的指纹
                    oldest = self._buffer[0]
                    if oldest.fingerprint in self._fingerprint_index:
                        del self._fingerprint_index[oldest.fingerprint]

        # ── 推送到 LogService ──
        try:
            from services.log import get_service as get_log_service
            log_svc = get_log_service()
            log_svc._log(
                level=level,
                message=f"[{error_code}] {message[:200]}",
                service=service,
                agent_id=agent_id,
                task_id=task_id,
            )
        except Exception as e:
            logger.warning("error_bus: log push failed: %s", e)

        # ── 推送到 EventBus ──
        try:
            from kernel import emit_event
            emit_event("error_log", result_entry.to_dict(), source=component)
        except Exception as e:
            logger.warning("error_bus: event push failed: %s", e)

        # 使统计缓存过期
        self._stats_ts = 0.0

        return {"success": True, "entry": result_entry.to_dict()}

    # ── EventBus 回调 ──

    def _on_error_event(self, signal: Any) -> None:
        """收到 EventBus 的错误事件 → 推送给所有 SSE 客户端"""
        data = signal.data if hasattr(signal, "data") else signal
        with self._sse_lock:
            dead: list[queue.Queue] = []
            for q in self._sse_clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._sse_clients.remove(q)

    # ── SSE ──

    def subscribe_sse(self) -> queue.Queue:
        """为 SSE 客户端创建一个订阅队列。"""
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._sse_lock:
            self._sse_clients.append(q)
        return q

    def unsubscribe_sse(self, q: queue.Queue) -> None:
        """移除 SSE 客户端队列。"""
        with self._sse_lock:
            if q in self._sse_clients:
                self._sse_clients.remove(q)

    # ── 查询 ──

    def query(
        self,
        level: str | None = None,
        error_code: str | None = None,
        component: str | None = None,
        service: str | None = None,
        agent_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """按条件查询错误日志（分页，按时间倒序）。"""
        with self._lock:
            results = list(self._buffer)

        # 过滤
        if level:
            results = [e for e in results if e.level == level.upper()]
        if error_code:
            results = [e for e in results if e.error_code == error_code]
        if component:
            results = [e for e in results if e.component == component]
        if service:
            results = [e for e in results if e.service == service]
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]

        # 按时间倒序
        results.sort(key=lambda e: e.timestamp, reverse=True)

        total = len(results)
        page = results[offset:offset + limit]

        return {
            "success": True,
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": [e.to_dict() for e in page],
        }

    def get_by_fingerprint(self, fingerprint: str) -> dict | None:
        """按指纹获取单条错误详情。"""
        with self._lock:
            entry = self._fingerprint_index.get(fingerprint)
            if entry:
                # 收集所有同指纹出现的时间点
                return entry.to_dict()
            return None

    def stats(self) -> dict:
        """错误统计：按 level / error_code / component 聚合，带缓存。"""
        now = time.time()
        if now - self._stats_ts < 2.0 and self._stats_cache:
            return self._stats_cache

        with self._lock:
            entries = list(self._buffer)

        by_level: dict[str, int] = {}
        by_error_code: dict[str, int] = {}
        by_component: dict[str, int] = {}
        top_sources: dict[str, int] = {}
        agents: set[str] = set()

        for e in entries:
            by_level[e.level] = by_level.get(e.level, 0) + 1
            by_error_code[e.error_code] = by_error_code.get(e.error_code, 0) + 1
            by_component[e.component] = by_component.get(e.component, 0) + 1
            src = f"{e.source}" if e.source else "unknown"
            top_sources[src] = top_sources.get(src, 0) + 1
            if e.agent_id:
                agents.add(e.agent_id)

        # top_sources 排序取前 10
        sorted_sources = sorted(top_sources.items(), key=lambda x: -x[1])[:10]

        result = {
            "success": True,
            "total": len(entries),
            "by_level": by_level,
            "by_error_code": by_error_code,
            "by_component": by_component,
            "top_sources": [
                {"source": s, "count": c} for s, c in sorted_sources
            ],
            "agents": len(agents),
        }

        # 磁盘文件数
        try:
            log_dir = _LOG_DIR
            if log_dir.exists():
                result["disk_files"] = len(list(log_dir.glob("log_*.json")))
                result["log_dir"] = str(log_dir)
        except Exception:
            pass

        self._stats_cache = result
        self._stats_ts = now
        return result

    def trend(self, window_minutes: int = 60, bucket_minutes: int = 10) -> dict:
        """错误趋势：按时间窗口分桶统计。

        Args:
            window_minutes: 回顾窗口（默认 60 分钟）
            bucket_minutes: 桶大小（默认 10 分钟）

        Returns:
            {"buckets": [{"bucket": "ISO8601", "count": int}, ...]}
        """
        now = time.time()
        since = now - window_minutes * 60

        with self._lock:
            entries = [e for e in self._buffer if e.timestamp >= since]

        # 分桶
        bucket_size = bucket_minutes * 60
        buckets: dict[int, int] = defaultdict(int)

        for e in entries:
            bucket_ts = int(e.timestamp // bucket_size) * bucket_size
            buckets[bucket_ts] += 1

        result = [
            {
                "bucket": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "count": count,
            }
            for ts, count in sorted(buckets.items())
        ]

        return {"success": True, "window_minutes": window_minutes, "buckets": result}

    def recent(self, limit: int = 50) -> dict:
        """取最近 N 条错误（快速）。"""
        with self._lock:
            entries = list(self._buffer)[-limit:]
        entries.reverse()
        return {
            "success": True,
            "entries": [e.to_dict() for e in entries],
            "count": len(entries),
        }

    def clear(self, before: float | None = None) -> dict:
        """清空错误缓冲区（可指定 before 时间之前）。"""
        with self._lock:
            if before is None:
                removed = len(self._buffer)
                self._buffer.clear()
                self._fingerprint_index.clear()
            else:
                remaining = [e for e in self._buffer if e.timestamp >= before]
                removed = len(self._buffer) - len(remaining)
                self._buffer = deque(remaining, maxlen=self._max_entries)
                self._fingerprint_index = {e.fingerprint: e for e in remaining}
        self._stats_ts = 0.0
        return {"success": True, "removed": removed}

    def export(self, path: str = "") -> dict:
        """导出错误日志到 JSON 文件。"""
        with self._lock:
            entries = [e.to_dict() for e in self._buffer]

        out_path = path or str(_LOG_DIR / f"error_export_{int(time.time())}.json")
        try:
            Path(out_path).write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return {"success": True, "path": out_path, "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# 3. 全局快捷入口
# ══════════════════════════════════════════════════════════════════════

_bus: ErrorBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> ErrorBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = ErrorBus()
    return _bus


def reset_bus() -> None:
    global _bus
    if _bus:
        _bus.stop()
    _bus = None


def capture(
    message: str,
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    exc: Exception | None = None,
    agent_id: str = "",
    task_id: str = "",
    context: dict | None = None,
) -> dict:
    """最简错误捕获入口 — 一行替换所有 except 点。

    用法:
        try:
            ...
        except Exception as e:
            capture("memory compact failed", exc=e, component="services")

    自动提取:
      - source: 调用栈 caller 的文件:行号
      - stack_trace: exc 的 traceback
      - service: 沿用 component 值

    Returns:
        {"success": True, "entry": {...}}
    """
    bus = get_bus()
    source = _caller_source(depth=2)
    stack_trace = _format_exc(exc) if exc else ""
    return bus.error(
        message=message,
        error_code=error_code,
        component=component,
        service=component,
        source=source,
        stack_trace=stack_trace,
        agent_id=agent_id,
        task_id=task_id,
        context=context or {},
    )


def capture_exception(
    exc: Exception,
    message: str = "",
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    agent_id: str = "",
    task_id: str = "",
    context: dict | None = None,
) -> dict:
    """直接从 Exception 对象捕获。

    用法:
        except Exception as e:
            capture_exception(e, "XXX failed", component="services")
    """
    bus = get_bus()
    return bus.exception(
        exc=exc,
        message=message,
        error_code=error_code,
        component=component,
        agent_id=agent_id,
        task_id=task_id,
        context=context or {},
    )


# ══════════════════════════════════════════════════════════════════════
# 4. API Handlers — 挂载到 ApiGateway
# ══════════════════════════════════════════════════════════════════════

# 这些 handler 会被混入到 api_handlers.py 的 ApiHandlers 类


def _parse_float(body: dict, key: str) -> float | None:
    v = body.get(key)
    if v is not None:
        try:
            return float(v)
        except (ValueError, TypeError):
            pass
    return None


def _parse_int(body: dict, key: str, default: int = 0) -> int:
    v = body.get(key)
    if v is not None:
        try:
            return int(v)
        except (ValueError, TypeError):
            pass
    return default


# ── /api/logs/errors ──


def handle_log_errors(body: dict | None = None) -> dict:
    """GET /api/logs/errors — 分页查询错误列表（前端错误列表页）"""
    b = body or {}
    bus = get_bus()
    return bus.query(
        level=b.get("level"),
        error_code=b.get("error_code"),
        component=b.get("component"),
        service=b.get("service"),
        agent_id=b.get("agent_id"),
        since=_parse_float(b, "since"),
        until=_parse_float(b, "until"),
        offset=_parse_int(b, "offset", 0),
        limit=_parse_int(b, "limit", 50),
    )


def handle_log_errors_detail(body: dict | None = None) -> dict:
    """POST /api/logs/errors/detail — 按指纹查单条错误详情"""
    b = body or {}
    fingerprint = b.get("fingerprint", "")
    if not fingerprint:
        return {"success": False, "error": "fingerprint is required"}
    entry = get_bus().get_by_fingerprint(fingerprint)
    if entry is None:
        return {"success": False, "error": "not found"}
    return {"success": True, "entry": entry}


def handle_log_errors_stats(body: dict | None = None) -> dict:
    """GET /api/logs/errors/stats — 错误统计总览（前端仪表盘）"""
    return get_bus().stats()


def handle_log_errors_trend(body: dict | None = None) -> dict:
    """POST /api/logs/errors/trend — 错误趋势（前端趋势图）"""
    b = body or {}
    window = _parse_int(b, "window", 60)
    bucket = _parse_int(b, "bucket", 10)
    return get_bus().trend(window_minutes=window, bucket_minutes=bucket)


def handle_log_errors_clear(body: dict | None = None) -> dict:
    """POST /api/logs/errors/clear — 清除错误（维护操作）"""
    b = body or {}
    before = _parse_float(b, "before")
    return get_bus().clear(before=before)


def handle_log_errors_export(body: dict | None = None) -> dict:
    """POST /api/logs/errors/export — 导出错误日志 JSON"""
    b = body or {}
    path = b.get("path", "")
    return get_bus().export(path=path)


# ── 注册到 API Gateway ──

LOG_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/logs/errors", handle_log_errors, "Query error logs (paginated)"),
    ("POST", "/api/logs/errors/detail", handle_log_errors_detail, "Error detail by fingerprint"),
    ("GET", "/api/logs/errors/stats", handle_log_errors_stats, "Error statistics overview"),
    ("POST", "/api/logs/errors/trend", handle_log_errors_trend, "Error trend (time buckets)"),
    ("POST", "/api/logs/errors/clear", handle_log_errors_clear, "Clear error buffer"),
    ("POST", "/api/logs/errors/export", handle_log_errors_export, "Export errors to JSON"),
]
