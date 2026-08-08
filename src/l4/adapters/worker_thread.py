"""WorkerPort adapter — fixed-size thread pool with bounded queue.

Compatibility shim: the implementation lives in L1
(``l1.kernel.worker_thread``) and is re-exported here so existing
``l4.adapters.*`` import paths keep working.
"""

from __future__ import annotations

from l1.kernel.worker_thread import ThreadPoolWorker  # noqa: F401

__all__ = ["ThreadPoolWorker"]
