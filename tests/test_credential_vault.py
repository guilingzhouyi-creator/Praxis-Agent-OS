"""Tests for CredentialVault — encrypted credential storage."""
from __future__ import annotations

import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCredentialVault:
    def test_list_providers(self):
        from l4.credential_vault import list_providers
        providers = list_providers()
        assert isinstance(providers, list)

    def test_export(self):
        from l4.credential_vault import export_vault_status
        r = export_vault_status()
        assert isinstance(r, dict)
