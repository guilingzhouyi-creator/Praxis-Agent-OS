"""RPC protocol data model — msgpack serializable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RpcMessage:
    """Request/response message. method = "rsp:<method>" indicates a response."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    method: str = ""
    params: dict = field(default_factory=dict)
    error: str = ""

    @property
    def is_response(self) -> bool:
        return self.method.startswith("rsp:")

    @classmethod
    def response(cls, req: RpcMessage, data: dict,
                 error: str = "") -> RpcMessage:
        return cls(id=req.id, method=f"rsp:{req.method}",
                   params=data, error=error)

    def to_dict(self) -> dict:
        return {"id": self.id, "method": self.method,
                "params": self.params, "error": self.error}
