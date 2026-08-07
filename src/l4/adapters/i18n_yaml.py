"""I18nPort adapter — YAML file backed translation store.

Loads translations from ``locales/<locale>.yaml`` (or ``.yml``).
Supports nested YAML (auto-flattened to dot-notation keys) and
``{variable}`` substitution in translated strings.

Usage:
    from l4.adapters.i18n_yaml import YamlI18nAdapter
    i18n = YamlI18nAdapter(locale_dir="./locales")
    i18n.set_locale("zh-CN")
    msg = i18n.t("shell.command.help")  # → "Show available commands"
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import l1.kernel.params.api as _api_params
from l1.kernel.params.api import I18N_FALLBACK_TO_KEY
from l1.kernel.ports import I18nPort

logger = logging.getLogger(__name__)


class YamlI18nAdapter(I18nPort):
    """I18nPort implementation — YAML file translations with lazy loading."""

    def __init__(self, locale_dir: str = "", default_locale: str | None = None) -> None:
        # Resolve default_locale at construction time (NOT an import-time
        # snapshot) so praxis.yaml `language:` overrides applied after this
        # module was imported still take effect for newly-created adapters.
        if default_locale is None:
            default_locale = _api_params.I18N_DEFAULT_LOCALE
        self._locale_dir: str = locale_dir
        self._locale: str = default_locale
        self._translations: dict[str, dict[str, str]] = {}  # locale → {key: msg}
        self._lock = threading.RLock()  # reentrant: _lookup → _ensure_loaded → register

    # ── I18nPort interface ────────────────────────────────────────────────

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate *key* in the current locale, applying {var} substitution."""
        msg = self._lookup(key)
        if msg is None:
            return key if I18N_FALLBACK_TO_KEY else key
        if kwargs:
            try:
                msg = msg.format(**kwargs)
            except KeyError as e:
                logger.warning("i18n[%s]: missing format key %s for '%s'", self._locale, e, key)
        return msg

    def set_locale(self, locale: str) -> None:
        """Switch the active locale, falling back to the default if unknown."""
        with self._lock:
            # Contract (I18nPort): unknown locale falls back to "en" so a
            # bogus /lang argument can never wedge the global adapter.
            available = self.get_available()
            if available and locale not in available:
                logger.warning("i18n_yaml: unknown locale %r, falling back to 'en'", locale)
                locale = _api_params.I18N_DEFAULT_LOCALE
            self._locale = locale
            self._ensure_loaded(locale)

    def get_locale(self) -> str:
        return self._locale

    def get_available(self) -> list[str]:
        """Return sorted locale names found in the locale directory."""
        d = self._find_dir()
        if not d:
            return ["en"]
        try:
            return sorted(
                {f.replace(".yaml", "").replace(".yml", "") for f in os.listdir(d) if f.endswith((".yaml", ".yml"))}
            )
        except Exception:
            logger.warning("i18n_yaml: list_locales failed, falling back to ['en']")
            return ["en"]

    def register(self, locale: str, data: dict[str, str | dict]) -> None:
        """Register translations programmatically (e.g. from kernel/errors.py)."""
        with self._lock:
            if locale not in self._translations:
                self._translations[locale] = {}
            self._flatten_and_store(locale, data)

    def register_file(self, locale: str, path: str) -> bool:
        """Load a single YAML file as translations for *locale*."""
        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.warning("i18n: file %s has no top-level dict", path)
                return False
            self.register(locale, data)
            logger.info("i18n: loaded %s from %s", locale, path)
            return True
        except Exception as e:
            logger.warning("i18n: failed to load %s: %s", path, e)
            return False

    # ── Internal ──────────────────────────────────────────────────────────

    def _lookup(self, key: str) -> str | None:
        locale = self._locale
        # Lock-free fast path: once a locale is loaded its translation dict is
        # append-only, so a plain read under the GIL is safe.  Only the first
        # lookup per locale takes the lock (to load the YAML file).
        if locale not in self._translations:
            with self._lock:
                self._ensure_loaded(locale)
        return self._translations.get(locale, {}).get(key)

    def _find_dir(self) -> str:
        if self._locale_dir and os.path.isdir(self._locale_dir):
            return self._locale_dir
        candidates = [
            os.environ.get("PRAXIS_LOCALE_DIR", ""),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "locales"),
            os.path.join(os.getcwd(), "locales"),
        ]
        for c in candidates:
            if c and os.path.isdir(c):
                self._locale_dir = c
                return c
        return ""

    def _ensure_loaded(self, locale: str) -> None:
        if locale in self._translations:
            return
        d = self._find_dir()
        if not d:
            logger.warning("i18n: locale dir not found")
            return
        for ext in (".yaml", ".yml"):
            path = os.path.join(d, f"{locale}{ext}")
            if os.path.isfile(path):
                self.register_file(locale, path)
                return
        logger.info("i18n: no file for '%s', key fallback", locale)

    def _flatten_and_store(self, locale: str, data: dict, prefix: str = "") -> None:
        """Flatten nested dict into dot-notation keys and store."""
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                self._flatten_and_store(locale, value, full_key)
            elif isinstance(value, str):
                self._translations[locale][full_key] = value
