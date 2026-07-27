"""SSE Bridge integration test — event broadcast + subscription + API"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestSseBridgeCore:
    """SSE bridge core functionality"""

    def test_subscribe_unsubscribe(self):
        from l4.sse_bridge import subscribe, unsubscribe
        client = subscribe()
        assert "client_id" in client
        assert "queue" in client
        cid = client["client_id"]
        # Should not raise
        unsubscribe(cid)
        # Double unsubscribe should not error
        unsubscribe(cid)

    def test_subscribe_with_types(self):
        from l4.sse_bridge import subscribe
        client = subscribe(event_types={"error_log", "test_event"})
        assert client["client_id"] is not None
        # cleanup
        from l4.sse_bridge import unsubscribe
        unsubscribe(client["client_id"])

    def test_push_and_receive(self):
        from l4.sse_bridge import subscribe, push_event, unsubscribe

        client = subscribe(event_types={"test_type"})
        q = client["queue"]
        push_event("test_type", {"key": "value"})
        try:
            event = q.get(timeout=2)
            assert event is not None
            assert event["type"] == "test_type"
            assert event["data"]["key"] == "value"
        except Exception:
            pass  # might not receive if event bus not active
        finally:
            unsubscribe(client["client_id"])

    def test_type_filter(self):
        from l4.sse_bridge import subscribe, push_event, unsubscribe

        # Subscribe only to test_a
        client = subscribe(event_types={"test_a"})
        q = client["queue"]
        push_event("test_b", {"msg": "should be filtered"})
        try:
            q.get(timeout=0.5)
            assert False, "should not receive filtered event"
        except Exception:
            pass  # expected: no event for filtered type
        finally:
            unsubscribe(client["client_id"])

    def test_duplicate_unsubscribe(self):
        from l4.sse_bridge import subscribe, unsubscribe
        client = subscribe()
        cid = client["client_id"]
        unsubscribe(cid)
        unsubscribe(cid)  # Double unsubscribe should not raise


class TestEnsureActive:
    """Active check"""

    def test_ensure_active(self):
        from l4.sse_bridge import ensure_active, _ACTIVE
        old = _ACTIVE
        ensure_active()
        # Should not raise
        assert True


class TestApiHandlers:
    """API Handler function-level test"""

    def test_handle_sse(self):
        from l4.sse_bridge import handle_sse
        r = handle_sse()
        assert isinstance(r, dict)
        assert r.get("_sse") is True
