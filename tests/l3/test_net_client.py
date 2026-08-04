"""NetClient behavior tests — canonical implementation lives at l3.net_client.

Covers GET/POST/download success and failure paths via mocked urllib so no
external network is required.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from l3.net_client import NetClient  # noqa: E402


class _FakeResp:
    """Minimal urllib response stand-in (context manager)."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestNetClientGet:
    def test_get_success(self):
        payload = json.dumps({"ok": True}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(payload)):
            result = NetClient.get("http://example.test/api")
        assert result == {"success": True, "data": {"ok": True}, "status": 200}

    def test_get_empty_body_yields_empty_dict(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(b"")):
            result = NetClient.get("http://example.test/api")
        assert result["success"] is True
        assert result["data"] == {}

    def test_get_invalid_json_reports_error(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(b"not-json")):
            result = NetClient.get("http://example.test/api")
        assert result["success"] is False
        assert "invalid JSON" in result["error"]

    def test_get_http_error_preserves_status(self):
        err = urllib.error.HTTPError("http://example.test/api", 404, "Not Found", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = NetClient.get("http://example.test/api")
        assert result == {"success": False, "error": "HTTP 404: Not Found", "status": 404}

    def test_get_url_error_reports_connection_failure(self):
        err = urllib.error.URLError("boom")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = NetClient.get("http://example.test/api")
        assert result["success"] is False
        assert "connection failed" in result["error"]

    def test_get_generic_error_is_caught(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("net down")):
            result = NetClient.get("http://example.test/api")
        assert result == {"success": False, "error": "net down"}

    def test_get_passes_custom_headers(self):
        payload = json.dumps({"ok": True}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(payload)) as m:
            NetClient.get("http://example.test/api", headers={"X-Token": "abc"})
        sent: urllib.request.Request = m.call_args.args[0]
        assert sent.headers.get("X-token") == "abc"
        assert sent.headers.get("User-agent") == "Praxis-NetClient/1.0"


class TestNetClientPost:
    def test_post_success(self):
        payload = json.dumps({"id": 1}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(payload)) as m:
            result = NetClient.post("http://example.test/api", {"a": 1})
        assert result == {"success": True, "data": {"id": 1}, "status": 200}
        sent: urllib.request.Request = m.call_args.args[0]
        assert sent.headers.get("Content-type") == "application/json"
        assert json.loads(sent.data.decode("utf-8")) == {"a": 1}

    def test_post_failure_returns_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("net down")):
            result = NetClient.post("http://example.test/api", {"a": 1})
        assert result == {"success": False, "error": "net down"}


class TestNetClientDownload:
    def test_download_success(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(b"raw-card-yaml")):
            result = NetClient.download("http://example.test/card.yaml")
        assert result == {
            "success": True,
            "content": "raw-card-yaml",
            "status": 200,
            "url": "http://example.test/card.yaml",
        }

    def test_download_failure_returns_url(self):
        err = urllib.error.HTTPError("http://example.test/card.yaml", 500, "Internal", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = NetClient.download("http://example.test/card.yaml")
        assert result["success"] is False
        assert result["url"] == "http://example.test/card.yaml"
