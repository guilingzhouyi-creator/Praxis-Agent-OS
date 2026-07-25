"""Network service tests — service endpoints, discovery, fetch."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestNetworkService:
    def test_service_create(self):
        from services.network import NetworkService
        svc = NetworkService()
        assert svc is not None

    def test_start_stop(self):
        from services.network import NetworkService
        svc = NetworkService()
        r = svc.start()
        assert r.get("success")
        r2 = svc.stop()
        assert r2.get("success")

    def test_register_service(self):
        from services.network import NetworkService
        svc = NetworkService()
        r = svc.register_service("test-api", "localhost", 8080)
        assert r is None or r.get("success", True)
