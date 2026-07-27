"""ContentTrust — universal content provenance and trust evaluation.

Cross-platform, config-driven. Answers:
  - Where did this content come from?
  - Who created it?
  - How was it obtained?
  - Is it trustworthy?

Integrates with:
  - memory.remember() / recall() — provenance tagging + trust filtering
  - CellMessage — Ed25519 signed agent-to-agent messages
  - Card step results — per-step output attribution
  - Tool execution — tool result provenance

Trust policies are configurable via praxis.yaml -> content_trust: section.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Source types ──

class SourceType(Enum):
    TOOL = "tool"               # tool execution result (write_file, read_file, ...)
    AGENT = "agent"             # agent-generated (AgentLoop response)
    HUMAN = "human"             # direct human input (L2 Shell / API)
    SYSTEM = "system"           # system-generated (boot, config, auto-summary)
    EXTERNAL = "external"       # external origin (MCP import, web fetch, email)
    MEMORY = "memory"           # recalled from memory ring (re-stored)
    CONVENTION = "convention"   # convention deliberation result
    UNKNOWN = "unknown"


# ── Provenance: immutable origin record ──

@dataclass
class Provenance:
    """Immutable record of content origin.

    Attached to every piece of content flowing through the system:
    memory entries, cell messages, card step results, tool outputs.
    """
    source_type: SourceType = SourceType.UNKNOWN
    source_id: str = ""            # "agent-1", "write_file", "l3a", "shell"
    method: str = ""               # "execution", "direct_message", "import", "recall"
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""             # links to Card trace_id for full audit trail
    signature: str = ""            # Ed25519 hex signature (agent-to-agent)
    signer_id: str = ""            # who signed it ("agent-1")
    verified: bool = False         # was the signature verified?
    trust_score: float = 0.0       # computed by TrustPolicy, 0.0-1.0
    policy_name: str = ""          # which policy evaluated this

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "method": self.method,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "signer_id": self.signer_id,
            "verified": self.verified,
            "trust_score": round(self.trust_score, 3),
            "policy_name": self.policy_name,
        }

    @staticmethod
    def from_dict(d: dict) -> Provenance:
        st = SourceType.UNKNOWN
        try:
            st = SourceType(d.get("source_type", "unknown"))
        except ValueError:
            pass
        return Provenance(
            source_type=st,
            source_id=d.get("source_id", ""),
            method=d.get("method", ""),
            timestamp=d.get("timestamp", time.time()),
            trace_id=d.get("trace_id", ""),
            signer_id=d.get("signer_id", ""),
            verified=d.get("verified", False),
            trust_score=d.get("trust_score", 0.0),
            policy_name=d.get("policy_name", ""),
        )


# ── Source reputation store ──

_source_reputation: dict[str, list[float]] = {}
"""source_id -> list of recent trust scores for moving average."""


def record_source_performance(source_id: str, score: float) -> None:
    """Record a source's trust score after evaluation."""
    if source_id not in _source_reputation:
        _source_reputation[source_id] = []
    scores = _source_reputation[source_id]
    scores.append(score)
    if len(scores) > 100:
        scores.pop(0)


def get_source_reputation(source_id: str) -> float:
    """Get moving average trust score for a source (0.0-1.0)."""
    scores = _source_reputation.get(source_id, [])
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def reset_source_reputation() -> None:
    _source_reputation.clear()


# ── Trust policy: configurable evaluation rules ──

@dataclass
class TrustPolicy:
    """Configurable policy for evaluating content trustworthiness.

    YAML example:
      content_trust:
        policies:
          default:
            initial_scores:
              tool: 0.8
              agent: 0.7
              human: 1.0
              system: 0.9
              external: 0.2
              unknown: 0.1
            decay_per_hour: 0.05
            require_provenance: true
            min_trust_for_recall: 0.3
            min_trust_for_store: 0.1
            source_reputation_weight: 0.3
    """
    name: str = "default"
    initial_scores: dict[str, float] = field(default_factory=lambda: {
        "tool": 0.8, "agent": 0.7, "human": 1.0,
        "system": 0.9, "external": 0.2, "unknown": 0.1,
    })
    decay_per_hour: float = 0.05       # trust decays over time
    require_provenance: bool = True     # reject content without provenance
    min_trust_for_recall: float = 0.3   # minimum trust to appear in recall results
    min_trust_for_store: float = 0.1    # minimum trust to be stored in memory
    source_reputation_weight: float = 0.3  # how much to weight historical reputation
    deny_if_unverified: bool = False    # for agent-to-agent: reject unsigned messages

    def evaluate(self, provenance: Provenance) -> float:
        """Compute trust score for a provenance record. Returns 0.0-1.0."""
        if self.require_provenance and not provenance.source_type:
            return 0.0

        base = self.initial_scores.get(provenance.source_type.value, 0.1)

        # Time decay: older content is less trustworthy
        age_hours = (time.time() - provenance.timestamp) / 3600
        decay = max(0.0, 1.0 - (age_hours * self.decay_per_hour))

        # Source reputation bonus/penalty
        rep = get_source_reputation(provenance.source_id)
        rep_bonus = (rep - 0.5) * self.source_reputation_weight

        # Signature verification bonus
        sig_bonus = 0.1 if provenance.verified else -0.1
        if self.deny_if_unverified and not provenance.verified and provenance.signer_id:
            return 0.0

        score = base * 0.6 + decay * 0.3 + rep_bonus + sig_bonus
        return max(0.0, min(1.0, score))


# ── Policy store (config-driven) ──

_policies: dict[str, TrustPolicy] = {
    "default": TrustPolicy(),
}


def register_policy(name: str, policy: TrustPolicy) -> None:
    _policies[name] = policy


def get_policy(name: str = "") -> TrustPolicy:
    return _policies.get(name, _policies.get("default", TrustPolicy()))


def load_policies(cfg: dict) -> None:
    """Load trust policies from praxis.yaml -> content_trust.policies section."""
    if not cfg:
        return
    for name, pcfg in cfg.items():
        initial = dict(pcfg.get("initial_scores", {}))
        policy = TrustPolicy(
            name=name,
            initial_scores=initial if initial else _policies["default"].initial_scores,
            decay_per_hour=float(pcfg.get("decay_per_hour", 0.05)),
            require_provenance=bool(pcfg.get("require_provenance", True)),
            min_trust_for_recall=float(pcfg.get("min_trust_for_recall", 0.3)),
            min_trust_for_store=float(pcfg.get("min_trust_for_store", 0.1)),
            source_reputation_weight=float(pcfg.get("source_reputation_weight", 0.3)),
            deny_if_unverified=bool(pcfg.get("deny_if_unverified", False)),
        )
        register_policy(name, policy)
    logger.info("content_trust: %d policies loaded", len(cfg))


# ── Signature helpers (Ed25519) ──

def sign_content(content: str, agent_id: str) -> str:
    """Sign content with agent's Ed25519 key. Returns hex signature."""
    try:
        from .services.identity import get_service as _id
        svc = _id()
        return svc.sign(agent_id, content.encode())
    except Exception:
        return ""


def verify_content(content: str, signature: str, signer_id: str) -> bool:
    """Verify content against a claimed signer's public key."""
    try:
        from .services.identity import get_service as _id
        svc = _id()
        return svc.verify(signer_id, content.encode(), bytes.fromhex(signature))
    except Exception:
        return False


# ── Central facade ──

class ContentTrust:
    """Universal content provenance and trust evaluation.

    Usage:
      ct = ContentTrust()
      prov = ct.tag(source_type="agent", source_id="agent-1",
                    method="direct_message", trace_id="trc-xxx")
      score = ct.evaluate(prov)     # 0.0-1.0
      ct.record(prov)               # store for reputation tracking
    """

    def __init__(self, policy_name: str = "default"):
        self._policy = get_policy(policy_name)
        self._stats = {"tagged": 0, "evaluated": 0, "accepted": 0, "rejected": 0}

    def tag(self, source_type: SourceType | str, source_id: str = "",
            method: str = "", trace_id: str = "", sign: bool = False,
            signer_id: str = "") -> Provenance:
        """Create a provenance record with initial metadata."""
        if isinstance(source_type, str):
            try:
                source_type = SourceType(source_type)
            except ValueError:
                source_type = SourceType.UNKNOWN
        prov = Provenance(
            source_type=source_type,
            source_id=source_id,
            method=method,
            trace_id=trace_id,
            signer_id=signer_id or source_id,
        )
        if sign and source_id:
            prov.signature = sign_content(
                f"{prov.source_type.value}:{prov.source_id}:{prov.timestamp}",
                signer_id or source_id,
            )
            prov.verified = bool(prov.signature)
        prov.trust_score = self._policy.evaluate(prov)
        prov.policy_name = self._policy.name
        self._stats["tagged"] += 1
        return prov

    def evaluate(self, provenance: Provenance) -> float:
        """Compute and cache trust score."""
        self._stats["evaluated"] += 1
        provenance.trust_score = self._policy.evaluate(provenance)
        provenance.policy_name = self._policy.name
        if provenance.trust_score >= self._policy.min_trust_for_store:
            self._stats["accepted"] += 1
        else:
            self._stats["rejected"] += 1
        return provenance.trust_score

    def record(self, provenance: Provenance) -> None:
        """Record provenance for source reputation tracking."""
        record_source_performance(provenance.source_id, provenance.trust_score)

    def can_recall(self, provenance: Provenance) -> bool:
        """Check if content meets minimum trust for recall."""
        return provenance.trust_score >= self._policy.min_trust_for_recall

    def can_store(self, provenance: Provenance) -> bool:
        """Check if content meets minimum trust for storage."""
        return provenance.trust_score >= self._policy.min_trust_for_store

    def check_message(self, sender: str, content: str,
                      signature: str = "", signer_id: str = "") -> dict:
        """Verify and evaluate a signed agent-to-agent message."""
        if signature and signer_id:
            verified = verify_content(content, signature, signer_id)
        else:
            verified = False
        prov = self.tag(SourceType.AGENT, source_id=sender,
                        method="message", signer_id=signer_id or sender)
        prov.signature = signature
        prov.verified = verified
        score = self.evaluate(prov)
        return {
            "sender": sender,
            "verified": verified,
            "trust_score": round(score, 3),
            "allowed": score >= self._policy.min_trust_for_store,
            "policy": self._policy.name,
        }

    def wrap(self, data: dict, source_type: SourceType | str,
             source_id: str = "", method: str = "",
             trace_id: str = "") -> dict:
        """Attach provenance to a data dict (for memory/message/card storage)."""
        prov = self.tag(source_type, source_id, method, trace_id)
        return {
            "data": data,
            "provenance": prov.to_dict(),
        }

    def unwrap(self, wrapped: dict) -> tuple[dict, Provenance | None]:
        """Extract data and provenance from a wrapped dict."""
        data = wrapped.get("data", wrapped)
        pd = wrapped.get("provenance", {})
        prov = Provenance.from_dict(pd) if pd else None
        return data, prov

    def stats(self) -> dict:
        return dict(self._stats)

    def reset_stats(self) -> None:
        self._stats = {"tagged": 0, "evaluated": 0, "accepted": 0, "rejected": 0}


# ── Singleton ──

_trust: ContentTrust | None = None


def get_trust(policy_name: str = "") -> ContentTrust:
    global _trust
    if _trust is None:
        _trust = ContentTrust(policy_name)
    return _trust


def reset_trust() -> None:
    global _trust
    _trust = None
    reset_source_reputation()
