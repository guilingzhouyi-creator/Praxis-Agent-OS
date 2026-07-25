"""Data transformation tools - 4 kinds.

transform_json, transform_yaml, validate_schema, migrate_data
"""

import json
import os
from pathlib import Path
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R


def _cmd_transform_json(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    operation = args.get("operation", "pretty")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if operation == "pretty":
            output = json.dumps(data, indent=2, ensure_ascii=False)
        elif operation == "compact":
            output = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        elif operation == "sort":
            output = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
        elif operation == "flatten":
            output = json.dumps(_flatten(data), indent=2, ensure_ascii=False)
        else:
            return {"success": False, "error": f"unknown operation: {operation}"}
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
        return {"success": True, "data": {"path": path, "operation": operation, "size": len(output)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _flatten(data: dict, prefix: str = "") -> dict:
    result = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten(v, key))
        else:
            result[key] = v
    return result


def _cmd_transform_yaml(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    operation = args.get("operation", "to_json")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        import yaml as _yaml
        with open(path, encoding="utf-8") as f:
            data = _yaml.safe_load(f)
        if operation == "to_json":
            output = json.dumps(data, indent=2, ensure_ascii=False)
            out_path = path.replace(".yaml", ".json").replace(".yml", ".json")
            if out_path == path:
                out_path = path + ".json"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
            return {"success": True, "data": {"source": path, "output": out_path, "format": "json"}}
        elif operation == "pretty":
            output = _yaml.dump(data, default_flow_style=False, allow_unicode=True, indent=2)
            with open(path, "w", encoding="utf-8") as f:
                f.write(output)
            return {"success": True, "data": {"path": path, "operation": "pretty"}}
        return {"success": False, "error": f"unknown operation: {operation}"}
    except ImportError:
        return {"success": False, "error": "PyYAML not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_validate_schema(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    schema = args.get("schema", {})
    if not path:
        return {"success": False, "error": "path is required"}
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except Exception:
            return {"success": False, "error": "invalid schema JSON"}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not schema:
            return {"success": True, "data": {"valid": True, "checks": ["syntax"], "note": "无 schema 约束，仅检查 JSON 语法"}}
        errors = _validate_against_schema(data, schema)
        return {"success": True, "data": {"valid": len(errors) == 0, "errors": errors, "error_count": len(errors)}}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"invalid JSON: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _validate_against_schema(data: Any, schema: dict, path: str = "$") -> list[str]:
    errors = []
    if "type" in schema:
        type_map = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}
        expected = type_map.get(schema["type"])
        if expected and not isinstance(data, expected):
            errors.append(f"{path}: expected {schema['type']}, got {type(data).__name__}")
    if isinstance(data, dict) and "properties" in schema:
        for key, prop in schema["properties"].items():
            if key in data:
                errors.extend(_validate_against_schema(data[key], prop, f"{path}.{key}"))
            elif prop.get("required", False):
                errors.append(f"{path}: missing required property '{key}'")
    return errors


def _cmd_migrate_data(args: dict, agent_id: str) -> dict:
    source = args.get("source", "")
    target = args.get("target", "")
    mapping = args.get("mapping", {})
    if not source or not target:
        return {"success": False, "error": "source and target are required"}
    if isinstance(mapping, str):
        try:
            mapping = json.loads(mapping)
        except Exception:
            mapping = {}
    try:
        with open(source, encoding="utf-8") as f:
            data = json.load(f)
        if mapping:
            transformed = {}
            for target_key, source_key in mapping.items():
                value = data
                for part in source_key.split("."):
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
                transformed[target_key] = value
        else:
            transformed = data
        with open(target, "w", encoding="utf-8") as f:
            json.dump(transformed, f, indent=2, ensure_ascii=False)
        return {"success": True, "data": {"source": source, "target": target, "records": 1 if isinstance(transformed, dict) else len(transformed) if isinstance(transformed, list) else 1}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    register(ToolSpec(name="transform_json", description="JSON transform (pretty/compact/sort/flatten)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("operation", "string", default="pretty")],
                      handler=_cmd_transform_json))
    register(ToolSpec(name="transform_yaml", description="YAML transform (to_json/pretty), requires PyYAML", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("operation", "string", default="to_json")],
                      handler=_cmd_transform_yaml))
    register(ToolSpec(name="validate_schema", description="JSON Schema validation", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("schema", "string", default="{}")],
                      handler=_cmd_validate_schema))
    register(ToolSpec(name="migrate_data", description="Data migration (JSON to JSON, with field mapping)", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("source", "string", required=True), ParamSpec("target", "string", required=True),
                                  ParamSpec("mapping", "string", default="{}")],
                      handler=_cmd_migrate_data))