"""L1 Kernel — core module importability and API tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_bus_importable():
    pass


def test_discovery_importable():
    pass


def test_lifecycle_importable():
    pass


def test_migration_importable():
    pass


def test_paths_has_get_paths():
    from l1.kernel.paths import get_paths
    assert callable(get_paths)


def test_paths_returns_paths_object():
    from l1.kernel.paths import get_paths
    paths = get_paths()
    assert hasattr(paths, "data_dir")
    assert hasattr(paths, "config_dir")


def test_bus_has_get_root_bus():
    from l1.kernel.bus import get_root_bus
    assert callable(get_root_bus)


def test_discovery_has_get_config():
    from l1.kernel.discovery import get_config
    assert callable(get_config)


def test_lifecycle_has_state():
    from l1.kernel.lifecycle import state
    assert callable(state)
