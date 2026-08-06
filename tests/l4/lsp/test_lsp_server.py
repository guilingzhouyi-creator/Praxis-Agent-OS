"""LanguageServer — JSON-RPC over stdio integration tests.

A tiny fake LSP server script runs in a real subprocess, so the handshake,
id-matched responses, notification skipping and graceful shutdown are all
exercised against the real transport.
"""

from __future__ import annotations

import sys

import pytest

from l4.lsp.lsp_manager import LSP_SERVER_COMMANDS, LanguageServer

FAKE_LSP_SCRIPT = r"""
import json
import sys


def read_msg():
    header = sys.stdin.readline()
    if not header:
        return None
    length = 0
    while header and header.strip():
        line = header.strip()
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
        header = sys.stdin.readline()
    if length <= 0:
        return None
    return json.loads(sys.stdin.read(length))


def write_msg(msg):
    body = json.dumps(msg)
    sys.stdout.write(f"Content-Length: {len(body)}\r\n\r\n{body}")
    sys.stdout.flush()


while True:
    msg = read_msg()
    if msg is None:
        break
    if "id" not in msg:
        continue  # notification (initialized, exit) — no response expected
    method = msg.get("method")
    if method == "initialize":
        write_msg({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"message": "hello"}})
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})
    elif method == "textDocument/definition":
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": [{"uri": "file:///def.py", "range": {}}]})
    elif method == "textDocument/references":
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": [{"uri": "file:///ref.py", "range": {}}]})
    elif method == "textDocument/hover":
        pass  # never respond — exercised by the timeout test
    elif method == "shutdown":
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": None})
    elif method == "exit":
        sys.exit(0)
    else:
        write_msg({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
"""


@pytest.fixture
def fake_lsp_server(monkeypatch, tmp_path):
    """Point the python LSP command at the fake server script."""
    monkeypatch.setitem(LSP_SERVER_COMMANDS, "python", [sys.executable, "-c", FAKE_LSP_SCRIPT])
    monkeypatch.setattr(LanguageServer, "_find_executable", lambda self, name: True)
    return tmp_path


def test_start_handshake_succeeds(fake_lsp_server):
    ls = LanguageServer("python", str(fake_lsp_server))
    result = ls.start()
    assert result.get("success"), f"start failed: {result}"
    assert ls.is_alive()
    ls.stop()


def test_definition_roundtrip(fake_lsp_server):
    ls = LanguageServer("python", str(fake_lsp_server))
    assert ls.start().get("success")
    result = ls.send_request(
        "textDocument/definition", {"textDocument": {"uri": "file:///x.py"}, "position": {"line": 0, "character": 0}}
    )
    assert result.get("success"), f"request failed: {result}"
    assert result["result"][0]["uri"] == "file:///def.py"
    ls.stop()


def test_notifications_are_skipped_until_matching_id(fake_lsp_server):
    """Server pushes a window/logMessage before the initialize response."""
    ls = LanguageServer("python", str(fake_lsp_server))
    result = ls.start()
    assert result.get("success"), f"handshake swallowed notification: {result}"
    ls.stop()


def test_response_timeout(monkeypatch, fake_lsp_server):
    import l4.lsp.lsp_manager as lsp_mod

    monkeypatch.setattr(lsp_mod, "LSP_RESPONSE_TIMEOUT", 0.5)
    ls = LanguageServer("python", str(fake_lsp_server))
    assert ls.start().get("success")
    result = ls.send_request(
        "textDocument/hover", {"textDocument": {"uri": "file:///x.py"}, "position": {"line": 0, "character": 0}}
    )
    assert not result.get("success")
    assert "timeout" in result.get("error", "")
    ls.stop()


def test_start_unknown_command(monkeypatch, fake_lsp_server):
    monkeypatch.setitem(LSP_SERVER_COMMANDS, "python", ["no-such-lsp-binary-xyz"])
    monkeypatch.setattr(LanguageServer, "_find_executable", lambda self, name: False)
    ls = LanguageServer("python", str(fake_lsp_server))
    result = ls.start()
    assert not result.get("success")
    assert "not found" in result.get("error", "")


def test_stop_idempotent(fake_lsp_server):
    ls = LanguageServer("python", str(fake_lsp_server))
    assert ls.start().get("success")
    assert ls.stop().get("success")
    assert ls.stop().get("status") == "not_running"
    assert not ls.is_alive()
