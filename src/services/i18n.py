"""I18n — configuration-driven internationalization service.

Design:
  - YAML-based translation files in locales/<locale>.yaml
  - Dot-notation keys with {variable} substitution
  - Singleton with lazy loading per locale
  - Falls back to key itself when translation missing
  - Thread-safe for concurrent access

Usage:
  from services.i18n import t, set_locale, locale

  t("shell.command.help")                    # → "Show available commands"
  t("shell.error.timeout", tool="read")      # → "Tool 'read' timed out"
  set_locale("zh-CN")
  t("shell.command.help")                    # → "显示可用命令"
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


_LOCALE: str = "en"
_TRANSLATIONS: dict[str, dict[str, str]] = {}
_LOCK = threading.Lock()
_LOCALE_DIR: str = ""


def _locale_dir() -> str:
    """Get the locale directory path."""
    global _LOCALE_DIR
    if not _LOCALE_DIR:
        # Search in multiple possible locations
        candidates = [
            os.environ.get("PRAXIS_LOCALE_DIR", ""),
            os.path.join(os.path.dirname(__file__), "..", "..", "locales"),
            os.path.join(os.getcwd(), "locales"),
        ]
        for c in candidates:
            if c and os.path.isdir(c):
                _LOCALE_DIR = c
                break
        if not _LOCALE_DIR:
            _LOCALE_DIR = candidates[1] if candidates[1] else ""
    return _LOCALE_DIR


def get_locale() -> str:
    """Get the current locale code (e.g. 'en', 'zh-CN')."""
    return _LOCALE


def set_locale(locale: str) -> None:
    """Switch to a different locale and load its translations."""
    global _LOCALE
    with _LOCK:
        _LOCALE = locale
        _load(locale)


def get_available_locales() -> list[str]:
    """List all available locale codes from the locale directory."""
    d = _locale_dir()
    if not d:
        return ["en"]
    try:
        return sorted([
            f.replace(".yaml", "").replace(".yml", "")
            for f in os.listdir(d)
            if f.endswith((".yaml", ".yml"))
        ])
    except Exception:
        return ["en"]


def t(key: str, **kwargs: Any) -> str:
    """Translate a key to the current locale.

    Args:
        key: Dot-notation key, e.g. "shell.command.help"
        **kwargs: Variables to substitute in the translated string

    Returns:
        Translated string, or the key itself if no translation found.
    """
    msg = _lookup(key)
    if not msg:
        return key
    if kwargs:
        try:
            msg = msg.format(**kwargs)
        except KeyError as e:
            logger.warning("i18n: missing format key %s for '%s'", e, key)
    return msg


def _load(locale: str) -> None:
    """Load translation file for a locale into cache."""
    if locale in _TRANSLATIONS:
        return  # already loaded
    d = _locale_dir()
    if not d:
        logger.warning("i18n: locale dir not found")
        return
    for ext in (".yaml", ".yml"):
        path = os.path.join(d, f"{locale}{ext}")
        if os.path.isfile(path):
            try:
                import yaml
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    _flatten_and_store(locale, data)
                    logger.info("i18n: loaded %d keys for '%s'", len(_TRANSLATIONS.get(locale, {})), locale)
                    return
            except Exception as e:
                logger.warning("i18n: failed to load %s: %s", path, e)
    logger.info("i18n: no translation file for '%s', using key fallback", locale)


def _flatten_and_store(locale: str, data: dict, prefix: str = "") -> None:
    """Flatten nested dict into dot-notation keys and store."""
    if locale not in _TRANSLATIONS:
        _TRANSLATIONS[locale] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _flatten_and_store(locale, value, full_key)
        elif isinstance(value, str):
            _TRANSLATIONS[locale][full_key] = value


def _lookup(key: str) -> str | None:
    """Look up a key in the current locale's translations."""
    locale = _LOCALE
    with _LOCK:
        if locale not in _TRANSLATIONS:
            _load(locale)
        return _TRANSLATIONS.get(locale, {}).get(key)


# ── Bootstrap — ensure default locale is loaded ──
_load("en")
