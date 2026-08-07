"""CLI tests — main.py commands."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_cmd_health_returns_dict():
    from l5.cli import cmd_health

    result = cmd_health([])
    assert isinstance(result, dict)
    assert "status" in result


def test_cmd_ps_exists():
    from l5.cli import cmd_ps

    assert callable(cmd_ps)


def test_cmd_status_exists():
    from l5.cli import cmd_status

    assert callable(cmd_status)


def test_cmd_boot_exists():
    from l5.cli import cmd_boot

    assert callable(cmd_boot)


def test_cmd_shutdown_exists():
    from l5.cli import cmd_shutdown

    assert callable(cmd_shutdown)


def test_cmd_card_exists():
    from l5.cli import cmd_card

    assert callable(cmd_card)


def test_cmd_tools_exists():
    from l5.cli import cmd_tools

    assert callable(cmd_tools)


def test_cmd_audit_exists():
    from l5.cli import cmd_audit

    assert callable(cmd_audit)


def test_cmd_chain_exists():
    from l5.cli import cmd_chain

    assert callable(cmd_chain)


def test_cmd_interrupts_exists():
    from l5.cli import cmd_interrupts

    assert callable(cmd_interrupts)


def test_cmd_devices_exists():
    from l5.cli import cmd_devices

    assert callable(cmd_devices)


def test_cmd_dev_exists():
    from l5.cli import cmd_dev

    assert callable(cmd_dev)


def test_cmd_sys_exists():
    from l5.cli import cmd_sys

    assert callable(cmd_sys)


def test_cmd_setting_exists():
    from l5.cli import cmd_setting

    assert callable(cmd_setting)


def test_cmd_card_list_exists():
    from l5.cli import cmd_card_list

    assert callable(cmd_card_list)


def test_cmd_card_submit_exists():
    from l5.cli import cmd_card_submit

    assert callable(cmd_card_submit)


def test_cmd_card_cancel_exists():
    from l5.cli import cmd_card_cancel

    assert callable(cmd_card_cancel)
