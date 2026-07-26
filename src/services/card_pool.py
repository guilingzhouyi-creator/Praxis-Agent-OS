"""CardPool — pre-registered card type pool with external import support.

Architecture:
  Built-in types  ← praxis.yaml card_types: section
  API registered  ← register_card_type() via central_plugin
  Remote import   ← install_from_url() / install_from_file()
  Peer sync       ← sync_from_peers() via kernel.net

All card types are stored in card_unified._card_type_registry.
CardPool adds import, export, search, and sync capabilities.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class CardPool:
    """Card type pool — import, export, search, and sync card definitions."""

    def __init__(self):
        self._registries: list[dict] = []
        self._load_registries_from_config()

    def _load_registries_from_config(self) -> None:
        """Load remote registry URLs from praxis.yaml card_pool.registries."""
        try:
            from kernel.params import PRAXIS_CONFIG_DIR
            import yaml
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "praxis.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                registries = (cfg or {}).get("card_pool", {}).get("registries", [])
                self._registries = list(registries)
        except Exception as e:
            logger.warning("card_pool: load registries failed: %s", e)

    # ── Install ──

    def install_from_url(self, url: str) -> dict:
        """Download and register a card definition from URL."""
        from .net_client import NetClient
        r = NetClient.download(url)
        if not r.get("success"):
            return r
        import yaml
        try:
            defn = yaml.safe_load(r["content"])
        except Exception as e:
            return {"success": False, "error": f"YAML parse: {e}"}
        return self._install_def(defn, source=url)

    def install_from_file(self, path: str) -> dict:
        """Register a card definition from a local .yaml file."""
        if not os.path.exists(path):
            return {"success": False, "error": f"file not found: {path}"}
        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                defn = yaml.safe_load(f)
        except Exception as e:
            return {"success": False, "error": f"YAML parse: {e}"}
        return self._install_def(defn, source=path)

    def _install_def(self, defn: dict, source: str = "") -> dict:
        """Validate and register a card type definition."""
        name = defn.get("name", defn.get("_cif_name", ""))
        if not name:
            return {"success": False, "error": "card definition missing 'name'"}
        protocol = defn.get("protocol", "universal")
        display = defn.get("display", name)
        phases = defn.get("phases", [])
        metadata_schema = defn.get("metadata_schema", {})

        from .card_unified import register_card_type
        register_card_type(name, {
            "display": display,
            "has_review": defn.get("has_review", False),
            "phases": [p["name"] for p in phases] if isinstance(phases, list) else phases,
            "default_prompts": defn.get("default_prompts", {}),
            "metadata_schema": metadata_schema,
        })
        logger.info("card_pool: installed '%s' from %s (protocol=%s)", name, source, protocol)
        return {"success": True, "name": name, "display": display,
                "protocol": protocol, "source": source}

    # ── Export ──

    def export_to_file(self, name: str, path: str = "") -> dict:
        """Export a registered card type definition to YAML file."""
        from .card_unified import get_card_type
        defn = get_card_type(name)
        if not defn:
            return {"success": False, "error": f"unknown card type: {name}"}
        import yaml
        export = {
            "_cif_version": "1.0",
            "name": name,
            "protocol": "universal",
            "display": defn.get("display", name),
            "has_review": defn.get("has_review", False),
            "phases": [{"name": p, "mode": "single", "tasks": []}
                       for p in defn.get("phases", [])],
            "metadata_schema": defn.get("metadata_schema", {}),
        }
        out = path or f"{name}.card.yaml"
        try:
            with open(out, "w", encoding="utf-8") as f:
                yaml.dump(export, f, default_flow_style=False, allow_unicode=True)
            return {"success": True, "path": out, "name": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Remote search & sync ──

    def search_remote(self, query: str, registry_url: str = "") -> dict:
        """Search card types across all configured remote registries."""
        from .card_registry_protocol import CardRegistryProtocol
        urls = [registry_url] if registry_url else [r["url"] for r in self._registries]
        all_results = []
        for url in urls:
            r = CardRegistryProtocol.search(url, query)
            if r.get("success"):
                all_results.extend(r.get("cards", []))
        return {"success": True, "cards": all_results, "count": len(all_results),
                "registries": len(urls)}

    def sync_from_peers(self) -> dict:
        """Sync card types from peer Praxis instances via network."""
        from kernel.net import get_net
        net = get_net()
        peers = net.list_peers()
        imported = 0
        for p in peers:
            if not p.get("alive"):
                continue
            r = net.send_remote(p["id"], {"type": "card_registry_sync"})
            if r.get("success") and r.get("cards"):
                for cdef in r["cards"]:
                    self._install_def(cdef, source=f"peer:{p['id']}")
                    imported += 1
        return {"success": True, "peers": len(peers), "imported": imported}

    # ── Query ──

    def list_pool(self, category: str = "") -> dict:
        """List all registered card types."""
        from .card_unified import list_card_types
        types = list_card_types()
        if category:
            types = [t for t in types if t.get("name", "").startswith(category)]
        return {"success": True, "types": types, "count": len(types)}

    def remove(self, name: str) -> dict:
        """Remove a card type from the registry."""
        from .card_unified import _card_type_registry, _registry_lock
        if name not in _card_type_registry:
            return {"success": False, "error": f"unknown card type: {name}"}
        with _registry_lock:
            _card_type_registry.pop(name, None)
        return {"success": True, "name": name}


# ── Singleton ──

_pool: CardPool | None = None


def get_pool() -> CardPool:
    global _pool
    if _pool is None:
        _pool = CardPool()
    return _pool


def reset_pool() -> None:
    global _pool
    _pool = None
