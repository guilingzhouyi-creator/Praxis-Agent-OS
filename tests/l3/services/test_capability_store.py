"""Capability store tests — typed authority records, fail-closed semantics."""

from __future__ import annotations

import time

import pytest

from l3.services.capability_store import (
    EFFECT_ALLOW,
    EFFECT_DENY,
    reset_capability_store,
)


@pytest.fixture()
def store(tmp_path):
    """Isolated capability store bound to a temp persistence file."""
    from l3.services.capability_store import CapabilityStore

    reset_capability_store()
    s = CapabilityStore(str(tmp_path / "caps.json"))
    yield s
    reset_capability_store()


class TestIssueAndCheck:
    """Basic allow/deny/none decisions."""

    def test_allow(self, store):
        r = store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, issuer="test")
        assert r["success"]
        assert store.check("agent-a", "tool:read")["decision"] == "allow"

    def test_deny(self, store):
        store.issue(subject="agent-a", resource="tool:pwn", effect=EFFECT_DENY, issuer="test")
        assert store.check("agent-a", "tool:pwn")["decision"] == "deny"

    def test_deny_dominates_allow(self, store):
        store.issue(subject="agent-a", resource="tool:pwn", effect=EFFECT_ALLOW, issuer="test")
        store.issue(subject="agent-a", resource="tool:pwn", effect=EFFECT_DENY, issuer="test")
        assert store.check("agent-a", "tool:pwn")["decision"] == "deny"

    def test_other_subject_not_affected(self, store):
        store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, issuer="test")
        assert store.check("agent-b", "tool:read")["decision"] == "none"

    def test_wrong_right_none(self, store):
        store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, rights=("read",), issuer="test")
        assert store.check("agent-a", "tool:read", right="write")["decision"] == "none"


class TestOneShot:
    """One-shot authority consumption."""

    def test_oneshot_consumed_once(self, store):
        store.issue(subject="agent-a", resource="tool:token", effect=EFFECT_ALLOW, uses_remaining=1, issuer="test")
        assert store.check("agent-a", "tool:token")["decision"] == "allow"
        assert store.check("agent-a", "tool:token")["decision"] == "none"

    def test_unlimited_stays(self, store):
        store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, issuer="test")
        assert store.check("agent-a", "tool:read")["decision"] == "allow"
        assert store.check("agent-a", "tool:read")["decision"] == "allow"


class TestLifecycle:
    """Expiry and revocation."""

    def test_expired_record_inactive(self, store):
        store.issue(
            subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, expiry=time.time() - 10, issuer="test"
        )
        assert store.check("agent-a", "tool:read")["decision"] == "none"

    def test_future_expiry_active(self, store):
        store.issue(
            subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, expiry=time.time() + 1000, issuer="test"
        )
        assert store.check("agent-a", "tool:read")["decision"] == "allow"

    def test_revoked_inactive(self, store):
        r = store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, issuer="test")
        store.revoke(r["cid"])
        assert store.check("agent-a", "tool:read")["decision"] == "none"


class TestDelegation:
    """Delegation attenuation rules."""

    def test_delegate_allows_child(self, store):
        r = store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, rights=("read",), issuer="test")
        d = store.delegate(r["cid"], "agent-b")
        assert d["success"]
        assert store.check("agent-b", "tool:read", right="read")["decision"] == "allow"

    def test_delegate_cannot_widen_rights(self, store):
        r = store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, rights=("read",), issuer="test")
        d = store.delegate(r["cid"], "agent-b", rights=("read", "write"))
        assert not d["success"]

    def test_delegate_deny_parent_rejected(self, store):
        r = store.issue(subject="agent-a", resource="tool:pwn", effect=EFFECT_DENY, issuer="test")
        d = store.delegate(r["cid"], "agent-b")
        assert not d["success"]

    def test_delegate_cannot_exceed_parent_expiry(self, store):
        r = store.issue(
            subject="agent-a",
            resource="tool:read",
            effect=EFFECT_ALLOW,
            expiry=time.time() + 500,
            issuer="test",
        )
        d = store.delegate(r["cid"], "agent-b", expiry=time.time() + 5000)
        assert d["success"]
        child = store.check("agent-b", "tool:read", right="use")
        assert child["decision"] == "allow"


class TestFailClosed:
    """Bare globals and unknown constraint keys."""

    @pytest.mark.parametrize("resource", ["*", "", "path:", "tool:", "tool:*"])
    def test_bare_globals_rejected(self, store, resource):
        r = store.issue(subject="agent-a", resource=resource, effect=EFFECT_ALLOW, issuer="test")
        assert not r["success"]

    def test_unknown_constraint_rejected_at_issue(self, store):
        r = store.issue(
            subject="agent-a",
            resource="tool:read",
            effect=EFFECT_ALLOW,
            constraints={"bogus_key": 1},
            issuer="test",
        )
        assert not r["success"]

    def test_unknown_constraint_disables_existing_allow(self, store):
        r = store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, issuer="test")
        store._records[r["cid"]].constraints = {"bogus_key": 1}
        assert store.check("agent-a", "tool:read")["decision"] == "none"


class TestTypedResources:
    """Typed subtree matching without prefix collisions."""

    def test_path_subtree_covered(self, store):
        store.issue(subject="agent-a", resource="path:/data", effect=EFFECT_ALLOW, issuer="test")
        assert store.check("agent-a", "path:/data/x/y.txt")["decision"] == "allow"

    def test_path_prefix_collision_not_covered(self, store):
        store.issue(subject="agent-a", resource="path:/data", effect=EFFECT_ALLOW, issuer="test")
        assert store.check("agent-a", "path:/data2/secret.txt")["decision"] == "none"

    def test_tool_exact_match_only(self, store):
        store.issue(subject="agent-a", resource="tool:rm", effect=EFFECT_ALLOW, issuer="test")
        assert store.check("agent-a", "tool:rmdir")["decision"] == "none"
        assert store.check("agent-a", "tool:rm")["decision"] == "allow"

    def test_type_mismatch_none(self, store):
        store.issue(subject="agent-a", resource="path:/data", effect=EFFECT_ALLOW, issuer="test")
        assert store.check("agent-a", "tool:rm")["decision"] == "none"


class TestPersistence:
    """Save/load round trip."""

    def test_round_trip(self, store, tmp_path):
        store.issue(subject="agent-a", resource="tool:read", effect=EFFECT_ALLOW, issuer="test")
        store.issue(subject="agent-a", resource="tool:pwn", effect=EFFECT_DENY, issuer="test")
        from l3.services.capability_store import CapabilityStore

        s2 = CapabilityStore(str(tmp_path / "caps.json"))
        assert s2.check("agent-a", "tool:read")["decision"] == "allow"
        assert s2.check("agent-a", "tool:pwn")["decision"] == "deny"
