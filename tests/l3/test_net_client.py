"""NetClient behavior + connection-pool tests (http.client, thread-local reuse)."""

from __future__ import annotations

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from l3 import net_client as nc  # noqa: E402
from l3.net_client import NetClient  # noqa: E402


def _ok(payload: dict, status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps(payload).encode("utf-8")


class TestNetClientGet:
    def test_get_success(self):
        with mock.patch.object(nc, "_request", return_value=_ok({"ok": True})) as m:
            result = NetClient.get("http://example.test/api")
        assert result == {"success": True, "data": {"ok": True}, "status": 200}
        assert m.call_args.args[0] == "GET"

    def test_get_empty_body(self):
        with mock.patch.object(nc, "_request", return_value=(200, b"")):
            result = NetClient.get("http://example.test/api")
        assert result["success"] is True
        assert result["data"] == {}

    def test_get_invalid_json(self):
        with mock.patch.object(nc, "_request", return_value=(200, b"not-json")):
            result = NetClient.get("http://example.test/api")
        assert result["success"] is False
        assert "invalid JSON" in result["error"]

    def test_get_connection_failure(self):
        with mock.patch.object(nc, "_request",
                               side_effect=ConnectionError("boom")):
            result = NetClient.get("http://example.test/api")
        assert result["success"] is False
        assert "connection failed" in result["error"]

    def test_get_generic_error(self):
        with mock.patch.object(nc, "_request", side_effect=RuntimeError("x")):
            result = NetClient.get("http://example.test/api")
        assert result == {"success": False, "error": "x"}

    def test_get_passes_headers(self):
        with mock.patch.object(nc, "_request", return_value=_ok({"ok": True})) as m:
            NetClient.get("http://example.test/api", headers={"X-Token": "abc"})
        headers = m.call_args.args[3]
        assert headers["X-Token"] == "abc"
        assert headers["User-Agent"] == "Praxis-NetClient/1.0"


class TestNetClientPost:
    def test_post_success(self):
        with mock.patch.object(nc, "_request", return_value=_ok({"id": 1})) as m:
            result = NetClient.post("http://example.test/api", {"a": 1})
        assert result == {"success": True, "data": {"id": 1}, "status": 200}
        assert m.call_args.args[0] == "POST"
        body = json.loads(m.call_args.kwargs["body"].decode("utf-8"))
        assert body == {"a": 1}
        assert m.call_args.args[3]["Content-Type"] == "application/json"

    def test_post_failure(self):
        with mock.patch.object(nc, "_request", side_effect=OSError("net down")):
            result = NetClient.post("http://example.test/api", {"a": 1})
        assert result["success"] is False


class TestNetClientDownload:
    def test_download_success(self):
        with mock.patch.object(nc, "_request", return_value=(200, b"raw-yaml")):
            result = NetClient.download("http://example.test/card.yaml")
        assert result == {"success": True, "content": "raw-yaml",
                          "status": 200, "url": "http://example.test/card.yaml"}

    def test_download_failure(self):
        with mock.patch.object(nc, "_request", side_effect=ConnectionError("x")):
            result = NetClient.download("http://example.test/card.yaml")
        assert result["success"] is False
        assert result["url"] == "http://example.test/card.yaml"


class TestConnectionPool:
    def test_same_thread_same_host_reuses_connection(self):
        nc._pool_local.pool = None
        created = []

        class FakeConn:
            def __init__(self, *a, **k):
                created.append(a)

            def request(self, *a, **k):
                self._resp = (200, b"{}")

            def getresponse(self):
                return _FakeResp(*self._resp)

            def close(self):
                pass

        class _FakeResp:
            def __init__(self, status, body):
                self.status = status
                self._body = body

            def read(self):
                return self._body

        with mock.patch.object(nc.http.client, "HTTPConnection", FakeConn):
            r1 = NetClient.get("http://example.test/a")
            r2 = NetClient.get("http://example.test/b")
        assert r1["success"] is True and r2["success"] is True
        assert len(created) == 1  # one connection reused across both calls

    def test_different_hosts_get_separate_connections(self):
        nc._pool_local.pool = None
        created = []

        class FakeConn:
            def __init__(self, *a, **k):
                created.append(a)

            def request(self, *a, **k):
                self._resp = (200, b"{}")

            def getresponse(self):
                class _F:
                    status = 200

                    def read(self):
                        return b"{}"

                return _F()

            def close(self):
                pass

        with mock.patch.object(nc.http.client, "HTTPConnection", FakeConn):
            NetClient.get("http://a.example.test/x")
            NetClient.get("http://b.example.test/y")
        assert len(created) == 2

    def test_stale_connection_retried_once(self):
        nc._pool_local.pool = None
        calls = {"n": 0}

        class FlakyConn:
            def __init__(self, *a, **k):
                pass

            def request(self, *a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise ConnectionError("stale")

            def getresponse(self):
                class _F:
                    status = 200

                    def read(self):
                        return b"{}"

                return _F()

            def close(self):
                pass

        with mock.patch.object(nc.http.client, "HTTPConnection", FlakyConn):
            result = NetClient.get("http://example.test/api")
        assert result["success"] is True
        assert calls["n"] == 2  # first failed, second succeeded

    def test_pool_isolated_per_thread(self):
        nc._pool_local.pool = None

        class FakeConn:
            def __init__(self, *a, **k):
                pass

            def request(self, *a, **k):
                self._resp = (200, b"{}")

            def getresponse(self):
                class _F:
                    status = 200

                    def read(self):
                        return b"{}"

                return _F()

            def close(self):
                pass

        import threading as _t

        with mock.patch.object(nc.http.client, "HTTPConnection", FakeConn):
            results = []

            def worker():
                results.append(NetClient.get("http://example.test/api"))

            t1 = _t.Thread(target=worker)
            t2 = _t.Thread(target=worker)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        assert all(r["success"] for r in results)
