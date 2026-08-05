"""Registration contract tests — config-declared extensions must resolve.

Verifies the registration-driven extension model so new capabilities
cannot silently drift from their YAML declarations:

  1. Every ``handler:`` path in config/tools.yaml resolves to a real
     callable — a tool with a broken handler is silently skipped at boot
     (tool_config logs a warning and drops it).
  2. Every top-level command in config/commands.yaml is known to the
     command registry after ``load_defaults()`` — no orphan metadata keys.
  3. Every name in ``kernel/__init__.py`` ``__all__`` resolves at runtime,
     and every ``from .<module>`` import in it points to an existing
     kernel module (new kernel modules must be exported per convention).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _load_yaml(rel: str) -> dict:
    """Load a config YAML file, asserting it exists and is a dict."""
    path = ROOT / rel
    assert path.exists(), f"missing config: {path}"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"{rel} root must be a dict"
    return data


def _iter_tool_handlers(data: dict):
    """Yield (layer_key, domain, tool_name, handler_path) for every tool."""
    for layer_key, domains in data.items():
        if layer_key.startswith("_") or not isinstance(domains, dict):
            continue
        for domain, tools in domains.items():
            if not isinstance(tools, dict):
                continue
            for name, defn in tools.items():
                if name.startswith("_") or not isinstance(defn, dict):
                    continue
                handler = defn.get("handler", "")
                if handler:
                    yield layer_key, domain, name, handler


class TestToolsYamlContract:
    """tools.yaml — every declared handler must resolve to a callable."""

    def test_all_tool_handlers_resolve(self):
        """A broken handler path means the tool is skipped silently at boot."""
        data = _load_yaml("config/tools.yaml")
        broken: list[str] = []
        for _layer, _domain, name, handler_path in _iter_tool_handlers(data):
            parts = handler_path.split(".")
            try:
                mod = importlib.import_module(".".join(parts[:-1]))
                fn = getattr(mod, parts[-1])
                if not callable(fn):
                    broken.append(f"{name} ({handler_path}): not callable")
            except (ImportError, AttributeError) as e:
                broken.append(f"{name} ({handler_path}): {e}")
        assert not broken, (
            "Broken tool handlers (tool would be skipped at boot):\n" + "\n".join(broken)
        )

    def test_tool_catalog_non_trivial(self):
        """Sanity guard — a truncated tools.yaml must fail loudly."""
        data = _load_yaml("config/tools.yaml")
        count = sum(1 for _ in _iter_tool_handlers(data))
        assert count >= 50, f"unexpectedly small tool catalog: {count}"


_COMMAND_FEATURES = ("help", "examples", "args", "category", "aliases")


class TestCommandsYamlContract:
    """commands.yaml — every top-level command must be known post-load."""

    def test_all_command_keys_loadable(self):
        """Orphan keys in commands.yaml indicate a registration gap.

        Non-command config blocks (e.g. ``subagent_specs``, consumed by
        subagent_spec.py rather than the command registry) are skipped —
        they have no command metadata (help/examples/args/category).
        """
        from l1.kernel.commands import get_command, load_command_defs

        data = _load_yaml("config/commands.yaml")
        load_command_defs()
        missing = [
            k for k, v in data.items()
            if isinstance(v, dict) and any(f in v for f in _COMMAND_FEATURES)
            and get_command(k) is None
        ]
        assert not missing, (
            "commands.yaml keys unknown to registry:\n" + "\n".join(missing)
        )

    def test_command_catalog_non_trivial(self):
        """Sanity guard — a truncated commands.yaml must fail loudly."""
        data = _load_yaml("config/commands.yaml")
        assert len(data) >= 30, f"unexpectedly small command catalog: {len(data)}"


class TestKernelExportsContract:
    """kernel/__init__.py — __all__ and module imports must be consistent."""

    def test_all_symbols_in_all_resolve(self):
        """Every name in __all__ must exist on the kernel package."""
        import l1.kernel as kernel

        missing = [name for name in kernel.__all__ if not hasattr(kernel, name)]
        assert not missing, "kernel __all__ entries missing:\n" + "\n".join(missing)

    def test_kernel_module_imports_exist(self):
        """Every 'from .<module>' import in __init__.py must point to a module."""
        init_path = SRC / "l1" / "kernel" / "__init__.py"
        init_src = init_path.read_text(encoding="utf-8")
        mods = set(re.findall(r"from \.(\w+) import", init_src))
        mods |= set(re.findall(r"from \. import (\w+)", init_src))
        kernel_dir = SRC / "l1" / "kernel"
        missing = []
        for m in sorted(mods):
            if not (kernel_dir / f"{m}.py").exists() and not (kernel_dir / m / "__init__.py").exists():
                missing.append(m)
        assert not missing, "kernel __init__ imports missing modules:\n" + "\n".join(missing)
