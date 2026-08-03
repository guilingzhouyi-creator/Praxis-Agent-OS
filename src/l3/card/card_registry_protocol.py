"""CardRegistryProtocol — remote card registry sync protocol.

Defines how Praxis instances discover, download, and publish card type
definitions from/to remote registries or peer nodes.

Protocol:
  GET  {base}/api/v1/cards              → list available card types
  GET  {base}/api/v1/cards/{name}       → download card definition (.yaml)
  POST {base}/api/v1/cards/publish      → publish a card definition
  GET  {base}/api/v1/cards/search?q=    → search card types
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class CardRegistryProtocol:
    """Remote card registry protocol client."""

    PROTO_VERSION = "1.0"

    @staticmethod
    def list_cards(registry_url: str, query: str = "",
                   timeout: float = 15.0) -> dict:
        """List card types from remote registry.
        
        Returns:
            {"success": True, "cards": [{"name": "...", "version": "...", ...}]}
        """
        from l3.net_client import NetClient
        url = f"{registry_url.rstrip('/')}/api/v1/cards"
        if query:
            import urllib.parse
            url += f"?q={urllib.parse.quote(query)}"
        r = NetClient.get(url, timeout=timeout)
        if r.get("success"):
            cards = r.get("data", {})
            if isinstance(cards, list):
                return {"success": True, "cards": cards, "count": len(cards)}
            if isinstance(cards, dict):
                return {"success": True, "cards": cards.get("cards", cards.get("data", [])),
                        "count": len(cards.get("cards", []))}
        return r

    @staticmethod
    def get_card(registry_url: str, name: str, timeout: float = 15.0) -> dict:
        """Download a specific card definition from remote registry.
        
        Returns:
            {"success": True, "card_def": {...}}
        """
        from l3.net_client import NetClient
        url = f"{registry_url.rstrip('/')}/api/v1/cards/{name}"
        r = NetClient.download(url, timeout=timeout)
        if r.get("success"):
            import yaml
            try:
                defn = yaml.safe_load(r["content"])
                return {"success": True, "card_def": defn,
                        "source": url, "name": name}
            except Exception as e:
                return {"success": False, "error": f"YAML parse failed: {e}"}
        return r

    @staticmethod
    def publish_card(registry_url: str, card_def: dict,
                     timeout: float = 30.0) -> dict:
        """Publish a card definition to remote registry."""
        from l3.net_client import NetClient
        url = f"{registry_url.rstrip('/')}/api/v1/cards/publish"
        return NetClient.post(url, card_def, timeout=timeout)

    @staticmethod
    def search(registry_url: str, query: str, timeout: float = 15.0) -> dict:
        """Search card types across remote registry."""
        return CardRegistryProtocol.list_cards(registry_url, query=query, timeout=timeout)
