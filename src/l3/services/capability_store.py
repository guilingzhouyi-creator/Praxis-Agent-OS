"""Capability store — typed capability records for gate-level authority.

A capability is a durable authority record, not a prompt convention:

    CapabilityRecord = ⟨subject, resource, rights, effect, issuer,
                        expiry, constraints, uses_remaining, lineage,
                        status⟩

Semantics (fail-closed by design):
  - deny dominates allow; both are typed records, never string hints;
  - resources are typed: ``path:`` subtree (boundary-safe containment) or
    ``tool:`` exact tool name — bare globals (``*``, ``""``) are rejected;
  - unknown constraint keys fail closed (record is unusable for allow, an
    unreadable deny still blocks — the conservative side);
  - one-shot authority (``uses_remaining=1``) is consumed atomically at the
    first committed check and revoked when the count reaches zero;
  - delegation attenuates rights, resource, expiry and constraint scope and
    can never mint a deny boundary or widen a parent grant;
  - expiring/revoked/spent records never apply.

Records persist via the shared JSON persistence machinery (same shape as
the approval gate) so grants survive restarts.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import HASH_TRUNC_SHORT
from l1.kernel.paths import get_paths as _gp
from l1.kernel.territory import is_within as _territory_is_within
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)

EFFECT_ALLOW = "allow"
EFFECT_DENY = "deny"
EFFECTS = (EFFECT_ALLOW, EFFECT_DENY)

STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
STATUS_SPENT = "spent"

_RIGHT_USE = "use"
_RIGHTS_USE = "use"
_RIGHTS_PUBLIC = ("use", "read", "write", "delete", "grant")
# Constraint keys the store understands; anything else fails closed.
_KNOWN_CONSTRAINTS = frozenset({"scope"})

# Resource type prefixes (typed resources, never bare wildcards)
RESOURCE_PATH = "path:"
RESOURCE_TOOL = "tool:"


@dataclass
class CapabilityRecord:
    """CapabilityRecord — durable authority record for a subject/resource pair."""

    subject: str
    resource: str
    effect: str
    issuer: str
    rights: tuple[str, ...] = (_RIGHTS_USE,)
    expiry: float = 0.0
    constraints: dict[str, Any] = field(default_factory=dict)
    uses_remaining: int = -1
    lineage: tuple[str, ...] = ()
    status: str = STATUS_ACTIVE
    cid: str = field(default_factory=lambda: f"cap-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}")

    def usable(self, now: float | None = None) -> bool:
        """Return True when the record applies right now (active, not expired/spent)."""
        if self.status != STATUS_ACTIVE:
            return False
        now = time.time() if now is None else now
        if self.expiry and now > self.expiry:
            return False
        return self.uses_remaining != 0


class CapabilityStore(PersistableMixin):
    """CapabilityStore — singleton authority record keeper with fail-closed checks."""

    persistence_kind = "capability_gate"

    def __init__(self, persist_path: str = ""):
        self._records: dict[str, CapabilityRecord] = {}
        self._lock = threading.RLock()
        self._init_persistence(persist_path or _gp().capability_gate, 30.0)
        self._restore()

    def issue(
        self,
        subject: str,
        resource: str,
        effect: str,
        rights: tuple[str, ...] = (_RIGHTS_USE,),
        issuer: str = "kernel",
        expiry: float = 0.0,
        constraints: dict[str, Any] | None = None,
        uses_remaining: int = -1,
        lineage: tuple[str, ...] = (),
    ) -> dict:
        """Issue a capability record; rejects bare globals and unknown constraint keys."""
        if not self._valid_shape(issuer, subject, resource, effect, rights, constraints, uses_remaining):
            return {"success": False, "error": "invalid capability record (fail-closed)"}
        rec = CapabilityRecord(
            subject=subject,
            resource=resource,
            effect=effect,
            issuer=issuer,
            rights=tuple(sorted(rights)),
            expiry=expiry,
            constraints=dict(constraints or {}),
            uses_remaining=uses_remaining,
            lineage=lineage,
        )
        with self._lock:
            self._records[rec.cid] = rec
        self.save()
        return {"success": True, "cid": rec.cid}

    def _serialize(self) -> dict:
        return {
            "records": {
                cid: {
                    "subject": r.subject,
                    "resource": r.resource,
                    "effect": r.effect,
                    "issuer": r.issuer,
                    "rights": list(r.rights),
                    "expiry": r.expiry,
                    "constraints": r.constraints,
                    "uses_remaining": r.uses_remaining,
                    "lineage": list(r.lineage),
                    "status": r.status,
                }
                for cid, r in self._records.items()
            },
        }

    def _deserialize(self, data: dict) -> bool:
        self._records.clear()
        for cid, d in data.get("records", {}).items():
            rec = CapabilityRecord(
                subject=d["subject"],
                resource=d["resource"],
                effect=d["effect"],
                issuer=d.get("issuer", ""),
                rights=tuple(d.get("rights", [])),
                expiry=float(d.get("expiry", 0.0)),
                constraints=dict(d.get("constraints", {}) or {}),
                uses_remaining=int(d.get("uses_remaining", -1)),
                lineage=tuple(d.get("lineage", [])),
                status=d.get("status", STATUS_ACTIVE),
            )
            rec.cid = str(cid)
            self._records[rec.cid] = rec
        return True

    def revoke(self, cid: str) -> dict:
        """Revoke a capability record (mark revoked, keep lineage)."""
        with self._lock:
            rec = self._records.get(cid)
            if rec is None:
                return {"success": False, "error": "no such capability"}
            rec.status = STATUS_REVOKED
        self.save()
        return {"success": True, "cid": cid}

    def delegate(
        self, cid: str, subject: str, rights: tuple[str, ...] | None = None, expiry: float | None = None
    ) -> dict:
        """Delegate an attenuated copy of capability *cid* to *subject*.

        The delegate never gains rights the parent lacks, never inherits a
        deny boundary and never exceeds the parent deadline.
        """
        with self._lock:
            parent = self._records.get(cid)
            if parent is None or not parent.usable() or parent.effect == EFFECT_DENY:
                return {"success": False, "error": "cannot delegate"}
            child_rights = tuple(sorted(rights)) if rights else tuple(parent.rights)
            if not set(child_rights).issubset(set(parent.rights)):
                return {"success": False, "error": "delegation cannot widen rights"}
            child_expiry = parent.expiry if expiry is None else min(parent.expiry, expiry)
            return self.issue(
                subject=subject,
                resource=parent.resource,
                effect=EFFECT_ALLOW,
                rights=child_rights,
                issuer=parent.issuer,
                expiry=child_expiry,
                constraints=dict(parent.constraints),
                uses_remaining=parent.uses_remaining if parent.uses_remaining < 0 else max(1, parent.uses_remaining),
                lineage=parent.lineage + (parent.cid,),
            )

    def check(self, subject: str, resource: str, right: str = _RIGHTS_USE) -> dict:
        """Evaluate *subject* acting on *resource* with *right*.

        Returns ``{"decision": "allow" | "deny" | "none", "records": [...]}``.
        Deny dominates allow; unknown constraints disable allow records;
        one-shot records are consumed on an allow decision.
        """
        with self._lock:
            now = time.time()
            decision = "none"
            applied: list[str] = []
            for rec in list(self._records.values()):
                if not rec.usable(now):
                    continue
                if rec.subject != subject:
                    continue
                if right not in rec.rights:
                    continue
                if not _resource_covers(rec.resource, resource):
                    continue
                unknown = set(rec.constraints) - _KNOWN_CONSTRAINTS
                if unknown and rec.effect == EFFECT_ALLOW:
                    # Fail closed: an allow record with unknown constraints
                    # is disabled; a deny record still applies (safe side).
                    continue
                if rec.effect == EFFECT_DENY:
                    decision = "deny"
                    applied.append(rec.cid)
                    break
                applied.append(rec.cid)
                decision = "allow"
                if rec.uses_remaining > 0:
                    rec.uses_remaining -= 1
                    if rec.uses_remaining == 0:
                        rec.status = STATUS_SPENT
                        self.save()
        return {"decision": decision, "records": applied}

    def _valid_shape(
        self,
        issuer: str,
        subject: str,
        resource: str,
        effect: str,
        rights: tuple[str, ...],
        constraints: dict[str, Any] | None,
        uses_remaining: int,
    ) -> bool:
        if effect not in EFFECTS:
            return False
        if not issuer or not subject or not resource:
            return False
        if not resource.startswith((RESOURCE_PATH, RESOURCE_TOOL)):
            return False
        if resource in (RESOURCE_PATH, RESOURCE_TOOL):
            return False  # bare typed-global wildcards rejected
        if "*" in resource:
            return False  # no wildcard authority anywhere in the resource
        if set(rights) - set(_RIGHTS_PUBLIC):
            return False
        if uses_remaining < -1:
            return False
        if constraints is not None and set(constraints) - _KNOWN_CONSTRAINTS:
            return False
        return not (subject in ("*", "") or issuer in ("*", ""))


def _resource_covers(grant_resource: str, asked_resource: str) -> bool:
    """Return True when *grant_resource* covers *asked_resource* (typed matching)."""
    if not asked_resource.startswith((RESOURCE_PATH, RESOURCE_TOOL)):
        return False
    if grant_resource.split(":")[0] != asked_resource.split(":")[0]:
        return False
    if grant_resource.startswith(RESOURCE_TOOL):
        return grant_resource == asked_resource
    # path resources use the boundary-safe subtree rule (no prefix collisions)
    return _territory_is_within(asked_resource[len(RESOURCE_PATH) :], [grant_resource[len(RESOURCE_PATH) :]])


_store: CapabilityStore | None = None
_store_lock = threading.Lock()


def get_capability_store() -> CapabilityStore:
    """Get the CapabilityStore singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = CapabilityStore()
    return _store


def reset_capability_store() -> None:
    """Reset the CapabilityStore singleton (tests / hot reset)."""
    global _store
    with _store_lock:
        _store = None
