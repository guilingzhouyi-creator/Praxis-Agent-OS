"""Services — all remaining service module importability tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_adapter_bridge_importable():
    import l3.services.adapter_bridge


def test_assembly_importable():
    import l3.services.assembly


def test_bus_components_importable():
    import l3.services.bus_components


def test_cell_orchestrate_importable():
    import l3.services.cell_orchestrate


def test_central_plugin_importable():
    import l3.services.central_plugin


def test_central_security_importable():
    import l3.services.central_security


def test_fault_tolerance_importable():
    import l3.services.fault_tolerance


def test_fs_importable():
    import l3.services.fs


def test_global_components_importable():
    import l3.services.global_components


def test_hook_importable():
    import l3.services.hook


def test_model_strategy_importable():
    import l3.services.model_strategy


def test_package_manager_importable():
    import l3.services.package_manager


def test_process_importable():
    import l3.services.process


def test_prompt_engine_importable():
    import l3.services.prompt_engine


def test_record_center_importable():
    import l3.services.record_center


def test_service_manager_importable():
    import l3.services.service_manager


def test_stats_center_importable():
    import l3.services.stats_center


def test_template_importable():
    import l3.services.template


def test_todo_importable():
    import l3.services.todo


def test_todo_tracker_importable():
    import l3.services.todo_tracker


def test_vspace_importable():
    import l3.services.vspace


def test_workspace_importable():
    import l3.services.workspace
