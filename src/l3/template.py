"""Template service — Jinja2 template rendering.

Used for: code generation, report generation, document templates.
"""

from __future__ import annotations

import logging
from typing import Any

from l3._base import BaseService

logger = logging.getLogger(__name__)


class TemplateService(BaseService):
    """Template rendering service."""

    def __init__(self):
        super().__init__("template")

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        return {"success": True}

    def render(self, template: str, variables: dict | None = None) -> dict:
        try:
            from jinja2 import Environment, BaseLoader, TemplateNotFound
            env = Environment(loader=BaseLoader(), autoescape=False)
            tpl = env.from_string(template)
            output = tpl.render(**(variables or {}))
            return {"success": True, "output": output, "length": len(output)}
        except ImportError:
            return {"success": False, "error": "jinja2 not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def render_file(self, template_path: str, variables: dict | None = None, output_path: str = "") -> dict:
        from pathlib import Path
        p = Path(template_path)
        if not p.exists():
            return {"success": False, "error": "template not found"}
        try:
            from jinja2 import Environment, FileSystemLoader
            env = Environment(loader=FileSystemLoader(str(p.parent)))
            tpl = env.get_template(p.name)
            output = tpl.render(**(variables or {}))
            if output_path:
                Path(output_path).write_text(output, encoding="utf-8")
                return {"success": True, "output_path": output_path, "length": len(output)}
            return {"success": True, "output": output, "length": len(output)}
        except ImportError:
            return {"success": False, "error": "jinja2 not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_variables(self, template: str) -> dict:
        try:
            from jinja2 import Environment, BaseLoader, meta
            env = Environment(loader=BaseLoader())
            ast = env.parse(template)
            variables = meta.find_undeclared_variables(ast)
            return {"success": True, "variables": sorted(variables), "count": len(variables)}
        except ImportError:
            return {"success": False, "error": "jinja2 not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}


_service: TemplateService | None = None


def get_service() -> TemplateService:
    global _service
    if _service is None:
        _service = TemplateService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None