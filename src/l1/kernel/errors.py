"""Centralized error system — structured error codes, i18n via I18nPort.

Three-layer architecture:
  1. Error definition: PraxisError class with code + message + optional cause
  2. Error catalog: registry of all known error codes with descriptions
  3. Error response: to_dict() → {"success": false, "error": str, "error_code": str}

i18n:
  All localized messages are served by the registered ``I18nPort`` adapter.
  Built-in zh-CN translations are registered into the port at module load.
  The old private ``_translations`` dict is removed — no dual state.

Usage:
  from l1.kernel.errors import (
      PraxisError, error, E_INTERNAL,
      register_error, catalog,
  )

  # Return a structured error
  return error("E_TIMEOUT", tool=tool, timeout=60)

  # Raise (for exceptional conditions)
  raise PraxisError("E_RESOURCE_EXHAUSTED", "Out of memory")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Locale helpers (delegate to I18nPort, backward-compatible) ──


def set_locale(locale: str) -> None:
    """Set the active locale. Delegates to registered I18nPort."""
    try:
        from l1.kernel.ports import get_port as _gp
        adapter = _gp("i18n")
        adapter.set_locale(locale)
    except Exception:
        pass


def get_locale() -> str:
    """Return the current locale code."""
    try:
        from l1.kernel.ports import get_port as _gp
        return _gp("i18n").get_locale()
    except Exception:
        return "en"


# ── Error definition ──


class PraxisError(Exception):
    """Structured error with error_code for programmatic handling.

    Args:
        code: machine-readable error code (e.g. "E_TIMEOUT")
        message: human-readable description (English default)
        cause: original exception (for chaining)
        **context: additional key-value pairs for the error context
    """

    def __init__(self, code: str, message: str = "",
                 cause: Exception | None = None, **context: Any):
        self.code = code
        self.message = message or _default_message(code)
        self.cause = cause
        self.context = context
        super().__init__(self.message)

    def to_dict(self, locale: str = "") -> dict:
        """Return a structured error response dict.

        If locale is set and I18nPort has a translation, uses localized message.
        """
        msg = self.message
        loc = locale or get_locale()
        if loc != "en":
            try:
                from l1.kernel.ports import get_port as _gp
                localized = _gp("i18n").t(f"error.{self.code}")
                if localized != f"error.{self.code}":
                    msg = localized
            except Exception:
                pass
        result: dict = {"success": False, "error": msg, "error_code": self.code}
        if self.context:
            result["context"] = self.context
        if self.cause:
            result["cause"] = str(self.cause)[:200]
        return result

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def error(code: str, message: str = "", cause: Exception | None = None,
          **context: Any) -> dict:
    """Convenience: create and return a PraxisError as a dict.

    This is the preferred way to return errors from tool handlers
    and service methods that return dicts (rather than raising).
    """
    return PraxisError(code, message, cause=cause, **context).to_dict()


# ── Error catalog ──

_error_catalog: dict[str, str] = {}


def register_error(code: str, default_message: str) -> None:
    """Register an error code with its default English message."""
    _error_catalog[code] = default_message


def _default_message(code: str) -> str:
    return _error_catalog.get(code, f"Unknown error: {code}")


def catalog() -> dict[str, str]:
    """Return all registered error codes with their default messages."""
    return dict(_error_catalog)


# ── Built-in error codes ──

E_INTERNAL = "E_INTERNAL"
E_TIMEOUT = "E_TIMEOUT"
E_INVALID_PARAMS = "E_INVALID_PARAMS"
E_NOT_FOUND = "E_NOT_FOUND"
E_CONSTITUTION_BLOCKED = "E_CONSTITUTION_BLOCKED"
E_GATECHAIN_BLOCKED = "E_GATECHAIN_BLOCKED"
E_TOOL_MUTED = "E_TOOL_MUTED"
E_TOOL_NOT_FOUND = "E_TOOL_NOT_FOUND"
E_RESOURCE_EXHAUSTED = "E_RESOURCE_EXHAUSTED"
E_PERMISSION_DENIED = "E_PERMISSION_DENIED"
E_CELL_EMERGENCY = "E_CELL_EMERGENCY"
E_CHECKPOINT_RESTORE = "E_CHECKPOINT_RESTORE"
E_AGENT_CRASHED = "E_AGENT_CRASHED"
E_HUMAN_REJECTED = "E_HUMAN_REJECTED"
E_APPROVAL_TIMEOUT = "E_APPROVAL_TIMEOUT"
E_MCP_FAILED = "E_MCP_FAILED"
E_UNKNOWN_TOOL = "E_UNKNOWN_TOOL"
E_HANDLER_ERROR = "E_HANDLER_ERROR"
E_MEMORY_REJECTED = "E_MEMORY_REJECTED"
E_SANDBOX_ERROR = "E_SANDBOX_ERROR"

# Register built-in codes
for _code, _msg in [
    (E_INTERNAL, "Internal error"),
    (E_TIMEOUT, "Operation timed out"),
    (E_INVALID_PARAMS, "Invalid parameters"),
    (E_NOT_FOUND, "Resource not found"),
    (E_CONSTITUTION_BLOCKED, "Blocked by constitution"),
    (E_GATECHAIN_BLOCKED, "Blocked by gate chain"),
    (E_TOOL_MUTED, "Tool is muted"),
    (E_TOOL_NOT_FOUND, "Tool not found in registry"),
    (E_RESOURCE_EXHAUSTED, "Resource exhausted"),
    (E_PERMISSION_DENIED, "Permission denied"),
    (E_CELL_EMERGENCY, "Cell is in emergency stop mode"),
    (E_CHECKPOINT_RESTORE, "Failed to restore checkpoint"),
    (E_AGENT_CRASHED, "Agent has crashed"),
    (E_HUMAN_REJECTED, "Rejected by human approval"),
    (E_APPROVAL_TIMEOUT, "Approval request timed out"),
    (E_MCP_FAILED, "MCP call failed"),
    (E_UNKNOWN_TOOL, "Unknown tool"),
    (E_HANDLER_ERROR, "Tool handler error"),
    (E_MEMORY_REJECTED, "Memory rejected by quality filter"),
    (E_SANDBOX_ERROR, "Sandbox operation failed"),
]:
    register_error(_code, _msg)

# ── Register zh-CN translations into I18nPort (not a private dict) ──

try:
    from l1.kernel.ports import get_port as _gp_err
    _i18n = _gp_err("i18n")
    _i18n.register("zh-CN", {
        f"error.{E_INTERNAL}": "内部错误",
        f"error.{E_TIMEOUT}": "操作超时",
        f"error.{E_INVALID_PARAMS}": "参数错误",
        f"error.{E_NOT_FOUND}": "资源不存在",
        f"error.{E_CONSTITUTION_BLOCKED}": "被Constitution阻止",
        f"error.{E_GATECHAIN_BLOCKED}": "被Gate链阻止",
        f"error.{E_TOOL_MUTED}": "工具已被禁用",
        f"error.{E_TOOL_NOT_FOUND}": "工具未注册",
        f"error.{E_RESOURCE_EXHAUSTED}": "资源耗尽",
        f"error.{E_PERMISSION_DENIED}": "权限不足",
        f"error.{E_CELL_EMERGENCY}": "Cell 处于紧急停止状态",
        f"error.{E_CHECKPOINT_RESTORE}": "还原点恢复失败",
        f"error.{E_AGENT_CRASHED}": "Agent 已崩溃",
        f"error.{E_HUMAN_REJECTED}": "已被人类拒绝",
        f"error.{E_APPROVAL_TIMEOUT}": "审批超时",
        f"error.{E_MCP_FAILED}": "MCP 调用失败",
        f"error.{E_UNKNOWN_TOOL}": "未知工具",
        f"error.{E_HANDLER_ERROR}": "工具处理器错误",
        f"error.{E_MEMORY_REJECTED}": "memory rejected by quality filter",
        f"error.{E_SANDBOX_ERROR}": "Sandbox操作失败",
    })
except Exception:
    pass  # I18nPort may not be registered yet — translations loaded later
