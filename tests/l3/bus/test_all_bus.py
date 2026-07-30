"""Bus — remaining module importability tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_comm_monitor_importable():
    import l3.bus.comm_monitor


def test_ipc_importable():
    import l3.bus.ipc


def test_l3b_importable():
    import l3.bus.l3b


def test_l3b_message_pool_importable():
    import l3.bus.l3b_message_pool


def test_log_importable():
    import l3.bus.log


def test_reference_channel_importable():
    import l3.bus.reference_channel


def test_task_bus_importable():
    import l3.bus.task_bus
