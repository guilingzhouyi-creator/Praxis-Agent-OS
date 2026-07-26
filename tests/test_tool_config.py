"""ToolConfig 单测 — YAML 加载 / ring 映射 / danger 默认 (M5 修复点)。"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from services.tool_config import ToolConfig
from services.tool_spec import TOOL_REGISTRY, ToolRing


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty TOOL_REGISTRY."""
    saved = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()
    ToolConfig._loaded = False
    yield
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(saved)


def _write_yaml(tmp_obj, content: str) -> str:
    base = getattr(tmp_obj, "name", tmp_obj)
    path = os.path.join(base, "tools.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


_SAMPLE_YAML = """\
layer_1:
  files:
    read_file:
      description: Read a file
      handler: tools._files._cmd_read_file
      params:
        - name: path
          type: string
          required: true
    list_dir:
      description: List directory
      handler: tools._files._cmd_list_dir
layer_2:
  terminal:
    run_command:
      description: Execute shell command
      handler: tools._comm._cmd_run
layer_3:
  network:
    curl:
      description: HTTP request
      handler: tools._network._cmd_curl
"""


class TestLoadYaml:
    """ToolConfig.load() — YAML → TOOL_REGISTRY."""

    def test_load_registers_all_tools(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            count = ToolConfig.load(path)
        assert count == 4
        assert ToolConfig._loaded is True

    def test_load_missing_file_returns_zero(self):
        count = ToolConfig.load("/nonexistent/tools.yaml")
        assert count == 0

    def test_load_invalid_root_returns_zero(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, "- this\n- is\n- a list\n")
            assert ToolConfig.load(path) == 0

    def test_load_skips_underscore_prefixed(self):
        yaml_content = """\
layer_1:
  files:
    _internal_tool:
      description: should be skipped
      handler: tools._files._cmd_read_file
    read_file:
      description: keep this
      handler: tools._files._cmd_read_file
_layer_x:
  domain:
    tool:
      description: skipped layer
      handler: tools._files._cmd_read_file
"""
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, yaml_content)
            assert ToolConfig.load(path) == 1
            assert "read_file" in TOOL_REGISTRY
            assert "_internal_tool" not in TOOL_REGISTRY


class TestLayerRingMapping:
    """layer_X → ToolRing mapping."""

    def test_layer_1_maps_to_ring_1(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        assert TOOL_REGISTRY["read_file"].ring == ToolRing.RING_1

    def test_layer_2_maps_to_ring_2_5(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        assert TOOL_REGISTRY["run_command"].ring == ToolRing.RING_2_5

    def test_layer_3_maps_to_ring_3(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        assert TOOL_REGISTRY["curl"].ring == ToolRing.RING_3


class TestDangerDefaultM5:
    """M5 fix: explicit danger:0 must be preserved."""

    def test_explicit_danger_zero_preserved(self):
        yaml_content = """\
layer_3:
  network:
    safe_curl:
      description: HTTP request with danger=0
      handler: tools._network._cmd_curl
      danger: 0
"""
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, yaml_content)
            ToolConfig.load(path)
        spec = TOOL_REGISTRY.get("safe_curl")
        assert spec is not None
        assert spec.danger == 0, "explicit danger:0 must be preserved (M5 fix)"

    def test_no_danger_layer_1_defaults_zero(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        assert TOOL_REGISTRY["read_file"].danger == 0

    def test_no_danger_layer_2_defaults_one(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        assert TOOL_REGISTRY["run_command"].danger == 1

    def test_no_danger_layer_3_defaults_four(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        assert TOOL_REGISTRY["curl"].danger == 4


class TestQueryFilters:
    """by_ring / by_category / by_danger / has / get."""

    def test_by_ring_filters_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        ring1 = ToolConfig.by_ring(ToolRing.RING_1)
        ring3 = ToolConfig.by_ring(ToolRing.RING_3)
        assert all(t.ring == ToolRing.RING_1 for t in ring1)
        assert all(t.ring == ToolRing.RING_3 for t in ring3)

    def test_by_ring_accepts_int(self):
        """RING_NAME_MAP int→str conversion."""
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        ring1 = ToolConfig.by_ring(1)
        assert all(t.ring == ToolRing.RING_1 for t in ring1)

    def test_by_category_filter(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        files = ToolConfig.by_category("files")
        assert all(t.category == "files" for t in files)
        assert len(files) == 2

    def test_get_and_has(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        assert ToolConfig.has("read_file")
        assert not ToolConfig.has("nonexistent_tool")
        assert ToolConfig.get("read_file") is not None
        assert ToolConfig.get("nonexistent_tool") is None


class TestReload:
    """reload() clears registry and reloads."""

    def test_reload_clears_and_reloads(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
            assert len(TOOL_REGISTRY) == 4
            ToolConfig.reload(path)
            assert len(TOOL_REGISTRY) == 4
            assert ToolConfig._loaded is True


class TestDerivativeSets:
    """write_tool_names / terminal_tool_names / file_tool_names."""

    def test_write_tool_names_includes_dangerous(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        writes = ToolConfig.write_tool_names()
        # ring_2_5 (run_command, danger=1) and ring_3 (curl, danger=4) are writes
        assert "run_command" in writes
        assert "curl" in writes
        # read_file is danger=0, ring_1 — only included if danger>=1 or ring!=RING_1
        # per write_tool_names: danger>=1 OR ring!=RING_1
        assert "read_file" not in writes  # danger=0, ring=RING_1

    def test_terminal_tool_names(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, _SAMPLE_YAML)
            ToolConfig.load(path)
        terms = ToolConfig.terminal_tool_names()
        assert "run_command" in terms
