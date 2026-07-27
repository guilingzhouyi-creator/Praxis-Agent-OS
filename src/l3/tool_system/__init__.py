"""Tool system — tool pipeline, registry, policy, and configuration."""


def _lazy_import(name: str):
    import importlib
    return importlib.import_module(f"l3.tool_system.{name}")


def get_tool_spec():
    return _lazy_import("tool_spec").ToolSpec


def get_tool_ring():
    return _lazy_import("tool_spec").ToolRing


def get_tool_registry():
    return _lazy_import("tool_registry").TOOL_REGISTRY


def get_register():
    return _lazy_import("tool_registry").register


def get_tool_pipeline():
    return _lazy_import("tool_pipeline").ToolPipeline


def get_pipeline():
    return _lazy_import("tool_pipeline").get_pipeline


def get_tool_config():
    return _lazy_import("tool_config").ToolConfig
