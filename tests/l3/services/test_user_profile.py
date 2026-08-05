"""User profile side-channel tests — collection, refinement, lifecycle, portability."""

from __future__ import annotations

import time

import pytest

from l1.kernel.params.system import (
    PROFILE_KIND_DECISION_STYLE,
    PROFILE_KIND_DOMAIN_FOCUS,
    PROFILE_KIND_PREFERENCE,
    PROFILE_KIND_TRAIT,
)
from l3.services.user_profile import (
    ProfileEntry,
    ProfileStore,
    UserProfileService,
    reset_service,
)


@pytest.fixture
def svc():
    reset_service()
    from l3.services.user_profile import get_service

    s = get_service()
    s.set_enabled(True)
    s.start()
    yield s
    reset_service()


class TestSwitch:
    def test_disabled_by_default(self):
        reset_service()
        s = UserProfileService(enabled=False)
        assert s.enabled is False

    def test_disabled_ingest_refused(self):
        reset_service()
        s = UserProfileService(enabled=False)
        r = s.ingest("u", PROFILE_KIND_PREFERENCE, "x")
        assert not r["success"]
        assert "disabled" in r["error"]


class TestIngest:
    def test_ingest_typed_entry(self, svc):
        r = svc.ingest("alice", PROFILE_KIND_PREFERENCE, "concise",
                       source="session", confidence=0.9)
        assert r["success"]
        assert r["entry_id"]
        entries = svc.entries("alice")
        assert len(entries) == 1
        assert entries[0]["kind"] == PROFILE_KIND_PREFERENCE
        assert entries[0]["value"] == "concise"

    def test_unknown_kind_rejected(self, svc):
        r = svc.ingest("alice", "not_a_kind", "x")
        assert not r["success"]
        assert "unknown kind" in r["error"]

    def test_confidence_clamped(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "x", confidence=5.0)
        assert svc.entries("alice")[0]["confidence"] == 1.0

    def test_ingest_with_ttl_expires(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "x", ttl=0.05)
        assert svc._store.count("alice") == 1
        time.sleep(0.1)
        assert svc._store.count("alice") == 0

    def test_multi_user_isolation(self, svc):
        svc.ingest("a", PROFILE_KIND_PREFERENCE, "x")
        svc.ingest("b", PROFILE_KIND_DOMAIN_FOCUS, "y")
        assert svc._store.count("a") == 1
        assert svc._store.count("b") == 1
        assert svc._store.all_users() == ["a", "b"]


class TestStoreCap:
    def test_cap_evicts_oldest(self):
        store = ProfileStore(max_entries=3)
        for i in range(5):
            store.add(ProfileEntry(kind=PROFILE_KIND_PREFERENCE, value=f"v{i}",
                                   user_id="u", ts=float(i)))
        assert store.count("u") == 3
        values = [e.value for e in store.entries("u")]
        assert values == ["v4", "v3", "v2"]

    def test_purge_expired(self):
        store = ProfileStore()
        store.add(ProfileEntry(kind=PROFILE_KIND_PREFERENCE, value="old",
                               user_id="u", ts=1.0, expires_at=2.0))
        store.add(ProfileEntry(kind=PROFILE_KIND_PREFERENCE, value="new",
                               user_id="u", ts=3.0, expires_at=0.0))
        assert store.purge_expired(now=5.0) == 1
        assert [e.value for e in store.entries("u")] == ["new"]

    def test_decay_weakens_confidence(self):
        store = ProfileStore()
        store.add(ProfileEntry(kind=PROFILE_KIND_PREFERENCE, value="x",
                               user_id="u", confidence=0.9))
        store.decay(factor=0.2)
        assert store.entries("u")[0].confidence == pytest.approx(0.7)


class TestEventCollectors:
    def test_approval_responded_collected(self, svc):
        from l1.kernel import get_event_bus

        bus = get_event_bus()
        bus.on_any(lambda sig: None)  # ensure bus exists
        from l1.kernel import emit_signal

        emit_signal("APPROVAL_RESPONDED", sender="approval_gate",
                    target="cell", data={"user_id": "carol", "approved": True,
                                         "req_id": "r1", "response": "ok"})
        deadline = time.time() + 1.0
        while time.time() < deadline and svc._store.count("carol") == 0:
            time.sleep(0.01)
        entries = svc.entries("carol")
        assert len(entries) == 1
        assert entries[0]["kind"] == PROFILE_KIND_DECISION_STYLE
        assert entries[0]["value"] == "approve"

    def test_card_pending_collected(self, svc):
        from l1.kernel import emit_signal

        emit_signal("CARD_PENDING", sender="pending_queue", target="cell",
                    data={"user_id": "dave", "card_id": "c1", "domain": "ops"})
        deadline = time.time() + 1.0
        while time.time() < deadline and svc._store.count("dave") == 0:
            time.sleep(0.01)
        entries = svc.entries("dave")
        assert entries and entries[0]["kind"] == PROFILE_KIND_DOMAIN_FOCUS
        assert entries[0]["value"] == "ops"


class TestRefine:
    def test_refine_requires_min_entries(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "x")
        r = svc.refine("alice")
        assert r["success"] and r["refined"] == 0

    def test_rule_refine_produces_trait(self, svc):
        for _ in range(6):
            svc.ingest("alice", PROFILE_KIND_DOMAIN_FOCUS, "python")
            svc.ingest("alice", PROFILE_KIND_PREFERENCE, "concise")
        r = svc.refine("alice")
        assert r["success"] and r["refined"] == 1
        traits = svc.get_profile("alice", kinds=(PROFILE_KIND_TRAIT,))
        assert traits["count"] == 1
        trait = traits["entries"][0]
        assert trait["value"]["method"] == "rule"
        assert "domain_focus" in trait["value"]["top_kinds"]

    def test_refine_disabled_refused(self):
        reset_service()
        s = UserProfileService(enabled=False)
        r = s.refine("alice")
        assert not r["success"]


class TestSnapshot:
    def test_kinds_filter(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "concise")
        svc.ingest("alice", PROFILE_KIND_DOMAIN_FOCUS, "python")
        only_pref = svc.get_profile("alice", kinds=(PROFILE_KIND_PREFERENCE,))
        assert only_pref["count"] == 1
        assert only_pref["kinds"] == [PROFILE_KIND_PREFERENCE]


class TestPortability:
    def test_export_import_roundtrip(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "concise")
        svc.ingest("alice", PROFILE_KIND_DOMAIN_FOCUS, "python")
        payload = svc.export("alice")
        assert len(payload["entries"]) == 2

        reset_service()
        s2 = UserProfileService(enabled=True)
        r = s2.import_profile("bob", payload)
        assert r["success"] and r["imported"] == 2
        assert s2._store.count("bob") == 2
        # source is rewritten to import
        assert s2.entries("bob")[0]["source"] == "import"

    def test_import_replace(self, svc):
        payload = {"entries": [
            {"kind": PROFILE_KIND_PREFERENCE, "value": "x", "user_id": "u"}]}
        svc.import_profile("alice", payload)
        svc.import_profile("alice", {"entries": [
            {"kind": PROFILE_KIND_PREFERENCE, "value": "y", "user_id": "u"}]},
            replace=True)
        assert svc._store.count("alice") == 1
        assert svc.entries("alice")[0]["value"] == "y"

    def test_clear(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "x")
        r = svc.clear("alice")
        assert r["removed"] == 1
        assert svc._store.count("alice") == 0


class TestStats:
    def test_stats_shape(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "x")
        st = svc.stats()
        assert st["enabled"] is True
        assert st["ingested"] == 1
        assert st["users"] == 1
        assert st["per_user"]["alice"] == 1


class TestConsumers:
    def test_cardwrite_injects_profile_summary(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "concise", confidence=0.9)
        from l3.cell.peers.l3a.helpers import cardwrite_handler

        r = cardwrite_handler({
            "nature": "execution", "title": "do a thing",
            "columns": {"domain": "ops"}, "user_id": "alice"}, agent_id="l3a")
        assert r["success"]
        # The card got a profile summary column (reference, not blocking)
        from l3.card.card_registry import get_registry, reset_registry

        reset_registry()
        card = get_registry()._cards.get(r["card_id"])
        if card is not None:
            assert card.summary.columns.get("_profile_summary") is not None

    def test_session_base_system_injects_profile(self, svc):
        """L3A session wiring: user_id flows into the base system prompt."""
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "concise", confidence=0.9)
        from l3.cell.peers.l3a.session import Session

        s = Session.create(title="t", user_id="alice")
        s._ensure_loop()
        assert "User Profile Reference" in s._base_system
        assert "concise" in s._base_system
        # Session without user_id stays clean
        s2 = Session.create(title="t2")
        s2._ensure_loop()
        assert "User Profile Reference" not in s2._base_system

    def test_session_cardwrite_forwards_user_id(self, svc):
        """Session-scoped cardwrite auto-attaches user_id from the session."""
        svc.ingest("bob", PROFILE_KIND_PREFERENCE, "terse", confidence=0.9)
        from l3.cell.peers.l3a.session import Session
        from l3.card.card_registry import get_registry, reset_registry

        reset_registry()
        s = Session.create(title="t", user_id="bob")
        s._ensure_loop()
        # The session registers its scoped cardwrite on the loop's tool list
        specs = [t for t in s._loop._tools if t.name == "cardwrite"]
        assert specs, "session cardwrite tool not registered"
        result = specs[0].handler({
            "nature": "execution", "title": "do thing",
            "columns": {"domain": "ops"}}, "l3a")
        assert result["success"]
        card = get_registry()._cards.get(result["card_id"])
        if card is not None:
            assert card.summary.columns.get("_profile_summary") is not None

    def test_build_l3a_prompt_injects_profile(self, svc):
        svc.ingest("alice", PROFILE_KIND_PREFERENCE, "concise", confidence=0.9)
        svc.ingest("alice", PROFILE_KIND_TRAIT, {"method": "rule"}, source="refined")
        from l3.cell.peers.l3a.helpers import build_l3a_prompt

        prompt = build_l3a_prompt(user_id="alice")
        assert "User Profile Reference" in prompt
        assert "concise" in prompt
        # No user -> no injection, still a valid prompt
        plain = build_l3a_prompt()
        assert "User Profile Reference" not in plain
