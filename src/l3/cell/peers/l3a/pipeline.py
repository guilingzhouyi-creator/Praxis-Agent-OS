"""ManagedToolOutput — bound oversized tool results with file spill."""

from __future__ import annotations

import json
import logging
import os
import uuid

from l3.error_bus import capture

from . import params as _p

logger = logging.getLogger(__name__)


def _output_dir() -> str:
    from l1.kernel.paths import get_paths
    return os.path.join(get_paths().data_dir, _p.MANAGED_OUTPUT_DIR)


def _ensure_dir() -> str:
    d = _output_dir()
    os.makedirs(d, exist_ok=True)
    return d


def bound(result: dict, max_bytes: int = _p.MANAGED_OUTPUT_MAX_BYTES) -> dict:
    """Bound a tool result to max_bytes, spilling the full JSON to disk when oversized; return the result or a truncation marker dict."""
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) <= max_bytes:
        return result
    head = text[:max_bytes // _p.OUTPUT_SPILL_HEAD_DIVISOR]
    tail = text[-(max_bytes // _p.OUTPUT_SPILL_TAIL_DIVISOR):]
    spill_path = spill(text)
    return {
        "_truncated": True,
        "_preview": head + f"\n... ({len(text)} chars elided) ...\n" + tail,
        "_spill": spill_path,
    }


def spill(content: str) -> str:
    """Write content to a managed spill file and return its path."""
    name = f"{uuid.uuid4().hex}.json"
    path = os.path.join(_ensure_dir(), name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        capture("l3a pipeline: spill failed", error_code="E_L3A_PIPELINE", component="l3a", context={"path": path, "error": str(e)})
        logger.warning("l3a pipeline: spill failed: %s", e)
    return path


def read(path: str) -> str | None:
    """Read a spill file's content, or None when the read fails."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, FileNotFoundError) as e:
        logger.warning("l3a pipeline: read spill failed: %s", e)
        return None
