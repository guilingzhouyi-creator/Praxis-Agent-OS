"""RPC protocol data model — msgpack serializable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from l1.kernel.params.system import HASH_TRUNC_LONG


@dataclass
class RpcMessage:
    """Request/response message. method = "rsp:<method>" indicates a response."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:HASH_TRUNC_LONG])
    method: str = ""
    params: dict = field(default_factory=dict)
    error: str = ""

    @property
    def is_response(self) -> bool:
        return self.method.startswith("rsp:")

    @classmethod
    def response(cls, req: RpcMessage, data: dict,
                 error: str = "") -> RpcMessage:
        """Build a response message mirroring the request id and method."""
        return cls(id=req.id, method=f"rsp:{req.method}",
                   params=data, error=error)

    def to_dict(self) -> dict:
        """Convert the message to a plain dict for serialization."""
        return {"id": self.id, "method": self.method,
                "params": self.params, "error": self.error}
