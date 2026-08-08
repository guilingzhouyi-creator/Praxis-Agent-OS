"""Config section handlers — LLM / model / tool domains.

Each ``cfg_*`` handler processes one section of praxis.yaml and applies its
values to the corresponding LLM/tool configuration. Re-exported by
``config_handlers.py``.
"""

from __future__ import annotations

from typing import Any


def cfg_llm(cfg: dict, s: Any, results: dict) -> None:
    """Apply llm: section (provider/model/cache) to L2 settings and the LLM prefix cache config."""
    for k in ("provider", "model", "api_url", "api_key", "max_tokens", "temperature", "rate_limit"):
        if k in cfg:
            s.set_l2(f"llm.{k}", cfg[k])
    cache_cfg = cfg.get("cache", {})
    if cache_cfg:
        from .cache_strategy import load_cache_config

        load_cache_config(cache_cfg)
        results["llm_cache"] = len(cache_cfg)
    results["llm"] = True


def cfg_tool_rates(cfg: dict, s: Any, results: dict) -> None:
    """Load tool rate limits from praxis.yaml tool_rates: section.

    Writes into discovery "tool_rates" (scheduler_rate.py reads it),
    params/tool.py constants, and SettingsCenter L2.
    """
    import l1.kernel.params.tool as _tool_mod
    from l1.kernel.discovery import set_config as _set_cfg

    _rate_map = {
        "ring_1": "TOOL_RATE_RING_1",
        "ring_2_5": "TOOL_RATE_RING_2_5",
        "ring_3": "TOOL_RATE_RING_3",
    }
    for yaml_key, attr in _rate_map.items():
        if yaml_key in cfg:
            setattr(_tool_mod, attr, int(cfg[yaml_key]))
            _set_cfg("tool_rates", yaml_key, int(cfg[yaml_key]))
            s.set_l2(f"tool_rates.{yaml_key}", cfg[yaml_key])
    results["tool_rates"] = True


def cfg_tool(cfg: dict, s: Any, results: dict) -> None:
    """Load tool timeout config from praxis.yaml tool: section.

    Writes into params/tool.py (via setattr), the discovery "tool" registry
    (get_tool_config reads it), and SettingsCenter L2.
    """
    import l1.kernel.params.tool as _tool_mod
    from l1.kernel.discovery import set_config as _set_cfg

    _timeout_map = {
        "web_timeout": "TOOL_WEB_TIMEOUT",
        "search_timeout": "TOOL_SEARCH_TIMEOUT",
        "terminal_timeout": "TOOL_TERMINAL_TIMEOUT",
        "git_timeout": "TOOL_GIT_TIMEOUT",
        "build_timeout": "TOOL_BUILD_TIMEOUT",
        "pip_install_timeout": "TOOL_PIP_INSTALL_TIMEOUT",
        "npm_timeout": "TOOL_NPM_TIMEOUT",
        "pyright_timeout": "TOOL_PYRIGHT_TIMEOUT",
        "compile_check_timeout": "TOOL_COMPILE_CHECK_TIMEOUT",
        "package_manager_timeout": "TOOL_PACKAGE_MANAGER_TIMEOUT",
        "handler_timeout": "TOOL_HANDLER_TIMEOUT",
    }
    for yaml_key, attr in _timeout_map.items():
        if yaml_key in cfg:
            setattr(_tool_mod, attr, cfg[yaml_key])
            _set_cfg("tool", yaml_key, cfg[yaml_key])
            s.set_l2(f"tool.{yaml_key}", cfg[yaml_key])
    # Auto-format switch: code_format.py reads get_tool_config("format_auto"),
    # so the YAML value must land in the discovery "tool" registry (not just
    # params/L2) or it silently falls back to the default.
    if "format_auto" in cfg:
        _tool_mod.TOOL_FORMAT_AUTO = bool(cfg["format_auto"])
        _set_cfg("tool", "format_auto", bool(cfg["format_auto"]))
        s.set_l2("tool.format_auto", bool(cfg["format_auto"]))
    # Build/test detectors: praxis.yaml uses list-of-lists; discovery uses
    # {name: {cmd: [...]}}. Convert for get_config("build_detectors").
    for yaml_key, params_attr in (("build_detectors", "BUILD_DETECTORS"), ("test_detectors", "TEST_DETECTORS")):
        if yaml_key in cfg and isinstance(cfg[yaml_key], list):
            cmds = [tuple(c) if isinstance(c, (list, tuple)) else (c,) for c in cfg[yaml_key]]
            setattr(_tool_mod, params_attr, cmds)
            for i, c in enumerate(cmds):
                _set_cfg(yaml_key, f"d{i}", {"cmd": list(c)})
            s.set_l2(f"tool.{yaml_key}", cmds)
    results["tool"] = True


def cfg_htn(cfg: dict, s: Any, results: dict) -> None:
    """Apply htn: section (domain prefix, default tools) to params/tool.py constants."""
    import l1.kernel.params.tool as _tool_mod

    if "domain_prefix" in cfg:
        _tool_mod.HTN_DOMAIN_PREFIX = cfg["domain_prefix"]
    if "tools" in cfg:
        _tool_mod.HTN_DEFAULT_TOOLS.clear()
        _tool_mod.HTN_DEFAULT_TOOLS.update(cfg["tools"])
    results["htn"] = True


def cfg_prompts(cfg: dict, s: Any, results: dict) -> None:
    """Load prompt template overrides from praxis.yaml prompts: section."""
    try:
        from l1.kernel.prompts import load_prompt_overrides

        load_prompt_overrides(cfg if isinstance(cfg, dict) else {})
        results["prompts"] = len(cfg) if isinstance(cfg, dict) else 0
    except Exception as e:
        results["prompts"] = f"error: {e}"


def cfg_model_spec(cfg: dict, s: Any, results: dict) -> None:
    """Load model_spec tree from praxis.yaml model_spec: section.

    Stores flat keys in SettingsCenter for ModelService retrieval:
      model_spec.subagent.defaults.{key}
      model_spec.subagent.specs.{name}.{key}
      model_spec.scout.{key}
      model_spec.r4_agent.{key}
      model_spec.convention.{key}
      model_spec.cell.{key}
    """
    _store_tree(s, "model_spec", cfg)
    results["model_spec"] = "loaded"


def _store_tree(s: Any, prefix: str, data: dict) -> None:
    """Recursively store a nested dict as flat keys in SettingsCenter."""
    for key, value in data.items():
        full_key = f"{prefix}.{key}"
        if isinstance(value, dict):
            _store_tree(s, full_key, value)
        else:
            s.set(full_key, value)
