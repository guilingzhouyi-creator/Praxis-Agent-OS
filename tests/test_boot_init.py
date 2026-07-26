"""Tests for boot_init.py — extracted service initialization module."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_init_services_import():
    from l3.boot_init import init_services
    assert callable(init_services)
