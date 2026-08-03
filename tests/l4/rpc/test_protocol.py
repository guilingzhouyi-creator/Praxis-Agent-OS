"""RPC protocol tests — RpcMessage dataclass."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestRpcMessage:
    """RpcMessage — request/response message."""

    def test_create_request(self):
        from l4.rpc.protocol import RpcMessage
        msg = RpcMessage(method="ping", params={"key": "value"})
        assert msg.method == "ping"
        assert msg.params == {"key": "value"}
        assert msg.id  # auto-generated
        assert msg.error == ""

    def test_is_response(self):
        from l4.rpc.protocol import RpcMessage
        req = RpcMessage(method="build")
        rsp = RpcMessage.response(req, {"status": "ok"})
        assert rsp.is_response
        assert rsp.method == "rsp:build"

    def test_response_creates_reply(self):
        from l4.rpc.protocol import RpcMessage
        req = RpcMessage(method="deploy")
        rsp = RpcMessage.response(req, {"result": "done"}, error="")
        assert rsp.id == req.id
        assert rsp.params == {"result": "done"}
        assert rsp.error == ""

    def test_response_with_error(self):
        from l4.rpc.protocol import RpcMessage
        req = RpcMessage(method="test")
        rsp = RpcMessage.response(req, {}, error="timeout")
        assert rsp.error == "timeout"

    def test_to_dict(self):
        from l4.rpc.protocol import RpcMessage
        msg = RpcMessage(method="echo", params={"msg": "hello"})
        d = msg.to_dict()
        assert d["method"] == "echo"
        assert d["params"]["msg"] == "hello"
        assert "id" in d
