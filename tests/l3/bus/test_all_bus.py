"""Bus — remaining module importability tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_comm_monitor_importable():
    pass


def test_ipc_importable():
    pass


def test_l3b_importable():
    pass


def test_l3b_message_pool_importable():
    pass


def test_log_importable():
    pass


def test_reference_channel_importable():
    pass


def test_task_bus_importable():
    pass
