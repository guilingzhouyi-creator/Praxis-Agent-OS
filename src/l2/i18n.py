"""I18n — port-based internationalization (backward-compatible facade).

Design:
  - Delegates to the registered ``I18nPort`` adapter (set at boot via
    ``kernel.ports.register_port("i18n", adapter)``).
  - Falls back to a default ``YamlI18nAdapter`` if no port is registered
    (backward compat for tests and minimal setups).
  - Module-level ``t()``, ``set_locale()``, ``get_locale()`` keep the
    same signatures as the original version — all existing callers work
    without changes.

Usage:
  from l2.i18n import t, set_locale

  t("shell.command.help")                    # → "Show available commands"
  set_locale("zh-CN")
  t("shell.command.help")                    # → "Show available commands"
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.ports import I18nPort, get_port, register_port
from l4.adapters.i18n_yaml import YamlI18nAdapter

logger = logging.getLogger(__name__)


# ── Default adapter (lazy init, used when no port registered) ──

_default_adapter: I18nPort | None = None


def _adapter() -> I18nPort:
    """Return the registered I18nPort adapter, or a default fallback."""
    global _default_adapter
    try:
        adapter = get_port("i18n")
        if isinstance(adapter, I18nPort):
            return adapter
    except KeyError:
        logger.debug("i18n: no port registered, using default adapter")
    if _default_adapter is None:
        _default_adapter = YamlI18nAdapter()
        register_port("i18n", _default_adapter)
        logger.info("i18n: using default YamlI18nAdapter (no port registered)")
    return _default_adapter


# ── Public API (backward-compatible) ──


def get_locale() -> str:
    """Get the current locale code (e.g. 'en', 'zh-CN')."""
    return _adapter().get_locale()


def set_locale(locale: str) -> None:
    """Switch to a different locale and load its translations."""
    _adapter().set_locale(locale)


def get_available_locales() -> list[str]:
    """List all available locale codes from the locale directory."""
    return _adapter().get_available()


def t(key: str, **kwargs: Any) -> str:
    """Translate a key to the current locale.

    Args:
        key: Dot-notation key, e.g. "shell.command.help"
        **kwargs: Variables to substitute in the translated string

    Returns:
        Translated string, or the key itself if no translation found.
    """
    return _adapter().t(key, **kwargs)


def register(locale: str, data: dict[str, str | dict]) -> None:
    """Register translation data for a locale (programmatic)."""
    _adapter().register(locale, data)


def register_file(locale: str, path: str) -> bool:
    """Load translations from a file (YAML/JSON). Returns True on success."""
    return _adapter().register_file(locale, path)
