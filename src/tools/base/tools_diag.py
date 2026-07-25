"""Diagnostic tools - 6 kinds.

exception_info, error_lookup, log_tail, log_search, log_level, performance_profile
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM
from kernel.platform import IS_NT, IS_WINDOWS, grep_cmd, tail_file


def _cmd_exception_info(args: dict, agent_id: str) -> dict:
    exception = args.get("exception", "")
    if not exception:
        return {"success": False, "error": "exception is required"}
    # Return error info and common solutions
    common = {
        "ImportError": "模块未安装或不在 sys.path 中。检查 requirements.txt 或 pip list",
        "ModuleNotFoundError": "同上，检查包名是否正确",
        "FileNotFoundError": "文件路径不存在。检查路径是否正确，使用 os.path.exists() 验证",
        "KeyError": "字典键不存在。使用 dict.get() 替代 dict[]",
        "IndexError": "列表索引越界。检查 len(list) 和索引范围",
        "TypeError": "类型不匹配。检查参数类型是否与函数签名一致",
        "ValueError": "值不合法。检查输入值是否在预期范围内",
        "AttributeError": "对象没有该属性。检查对象类型和属性名",
        "ZeroDivisionError": "除以零。除数不能为 0",
        "SyntaxError": "语法错误。检查括号、引号、缩进是否匹配",
    }
    solution = common.get(exception, "查阅官方文档或搜索类似错误")
    return {"success": True, "data": {"exception": exception, "solution": solution, "common": True}}


def _cmd_error_lookup(args: dict, agent_id: str) -> dict:
    code = args.get("code", "")
    if not code:
        return {"success": False, "error": "code is required"}
    return {"success": True, "data": {"code": code, "description": f"Error code {code} lookup", "source": "built-in"}}


def _cmd_log_tail(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    lines = args.get("lines", 50)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        result_lines = tail_file(path, lines)
        return {"success": True, "data": {"lines": result_lines, "count": len(result_lines), "file": path}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_log_search(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    pattern = args.get("pattern", "")
    max_results = args.get("max_results", 50)
    if not path or not pattern:
        return {"success": False, "error": "path and pattern are required"}
    try:
        cmd = grep_cmd(pattern, path, max_count=max_results)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:max_results]
        return {"success": True, "data": {"results": lines, "count": len(lines), "pattern": pattern}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_log_level(args: dict, agent_id: str) -> dict:
    level = args.get("level", "")
    logger_name = args.get("logger", "root")
    if not level:
        return {"success": False, "error": "level is required"}
    import logging
    levels = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}
    if level.upper() not in levels:
        return {"success": False, "error": f"invalid level: {level}, use DEBUG/INFO/WARNING/ERROR"}
    log = logging.getLogger(logger_name)
    log.setLevel(levels[level.upper()])
    return {"success": True, "data": {"logger": logger_name, "level": level.upper(), "set": True}}


def _cmd_performance_profile(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        import cProfile, pstats
        from io import StringIO
        pr = cProfile.Profile()
        pr.enable()
        with open(path, "r", encoding="utf-8") as f:
            _ = f.read()
        pr.disable()
        s = StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats("cumtime")
        ps.print_stats(20)
        return {"success": True, "data": {"profile": s.getvalue(), "file": path}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    register(ToolSpec(name="exception_info", description="Query exception info and common solutions", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("exception", "string", required=True)],
                      handler=_cmd_exception_info))
    register(ToolSpec(name="error_lookup", description="Look up error code meaning", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("code", "string", required=True)],
                      handler=_cmd_error_lookup))
    register(ToolSpec(name="log_tail", description="View log file tail", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("lines", "int", default=50)],
                      handler=_cmd_log_tail))
    register(ToolSpec(name="log_search", description="Search log file for pattern", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("pattern", "string", required=True),
                                  ParamSpec("max_results", "int", default=50)],
                      handler=_cmd_log_search))
    register(ToolSpec(name="log_level", description="Set log level", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("level", "string", required=True), ParamSpec("logger", "string", default="root")],
                      handler=_cmd_log_level))
    register(ToolSpec(name="performance_profile", description="Profile file read performance", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True)],
                      handler=_cmd_performance_profile))