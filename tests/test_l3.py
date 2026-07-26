"""L3 coordinator + L3B cross-cell routing tests."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestL3B:
    def test_tier_l3b1(self):
        from l3.l3b import L3B
        l3b = L3B()
        assert l3b.tier == "L3B1"

    def test_register_cell(self):
        from l3.l3b import L3B
        l3b = L3B()
        l3b.register("cell-1", ["app/routes"])
        assert "cell-1" in l3b._cells
        assert l3b._cells["cell-1"].territory == ["app/routes"]

    def test_route_to_cell(self):
        from l3.l3b import L3B
        l3b = L3B()
        l3b.register("cell-a", ["app/routes"])
        l3b.register("cell-b", ["app/services"])
        result = l3b.route("app/routes", exclude="cell-b")
        assert result == "cell-a"

    def test_route_no_match(self):
        from l3.l3b import L3B
        l3b = L3B()
        result = l3b.route("unknown")
        assert result is None

    def test_status(self):
        from l3.l3b import L3B
        l3b = L3B()
        status = l3b.status()
        assert "tier" in status
        assert "cells" in status


class TestL3Coordinator:
    def test_register_cell(self):
        from l3.l3 import L3Coordinator
        coord = L3Coordinator()
        coord.register_cell("cell-1", ["app/routes"])
        assert len(coord._cells) == 1

    def test_status(self):
        from l3.l3 import L3Coordinator
        coord = L3Coordinator()
        s = coord.status()
        assert "L3A" in s
        assert "L3B" in s
        assert "Intents" in s
