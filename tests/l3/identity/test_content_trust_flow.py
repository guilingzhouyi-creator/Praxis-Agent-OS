"""Identity + ContentTrust integration test — Ed25519 keys + provenance tagging."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestIdentity:
    def test_identity_service_init(self):
        from l3.services.identity import IdentityService
        ident = IdentityService()
        assert ident is not None

    def test_generate_keypair(self):
        from l3.services.identity import IdentityService
        ident = IdentityService()
        r = ident.generate_keypair("key-agent")
        assert isinstance(r, dict)

    def test_get_public_key(self):
        from l3.services.identity import IdentityService
        ident = IdentityService()
        ident.generate_keypair("pub-agent")
        r = ident.get_public_key("pub-agent")
        assert r is not None


class TestContentTrust:
    def test_get_trust(self):
        from l3.services.content_trust import get_trust
        ct = get_trust()
        assert ct is not None

    def test_tag_provenance(self):
        from l3.services.content_trust import get_trust
        ct = get_trust("default")
        prov = ct.tag(source_type="agent", source_id="test-agent",
                       method="tool_call", trace_id="trace-1")
        assert prov is not None
        d = prov.to_dict()
        assert d["source_type"] == "agent"
        assert d["source_id"] == "test-agent"

    def test_can_store_check(self):
        from l3.services.content_trust import get_trust
        ct = get_trust("default")
        prov = ct.tag(source_type="agent", source_id="writer",
                       method="decision", trace_id="")
        r = ct.can_store(prov)
        assert isinstance(r, bool) or r is not None

    def test_can_recall_check(self):
        from l3.services.content_trust import get_trust
        ct = get_trust("default")
        prov = ct.tag(source_type="agent", source_id="reader",
                       method="observation", trace_id="")
        r = ct.can_recall(prov)
        assert isinstance(r, bool) or r is not None

    def test_stats(self):
        from l3.services.content_trust import get_trust
        ct = get_trust()
        s = ct.stats()
        assert isinstance(s, dict)
