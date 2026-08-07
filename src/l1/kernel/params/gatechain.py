"""Constants: GateChain security gateway."""

from typing import Final

# ── GateChain ──

LEDGER_MAX_ENTRIES: Final[int] = 200
# Default entry cap for ledger.recent() lookups (per agent/tool)
LEDGER_RECENT_LIMIT: Final[int] = 20
# Time window (seconds) over which ledger.count() tallies entries
LEDGER_COUNT_WINDOW: Final[float] = 60.0
# Default danger level used when a tool has no registered level
GATECHAIN_DEFAULT_DANGER: Final[int] = 1
# Tool-name → danger level map used for G3/G5 risk scoring
GATECHAIN_DANGER_LEVELS: Final[dict[str, int]] = {
    "deploy": 5,
    "db_migrate": 4,
    "user_delete": 5,
    "destroy": 5,
    "rollback": 4,
    "migrate": 4,
    "exec": 4,
    "run_in_terminal": 3,
    "execute": 3,
    "delete": 3,
    "write": 2,
    "replace": 2,
    "format": 2,
}
# Territory-map key holding the known-tool set for gatechain lookup
GATECHAIN_TOOLS_KEY: Final[str] = "_tools"
# Weight multiplying recent call count in the G3 risk score
GATECHAIN_FREQ_MULTIPLIER: Final[float] = 0.5
# Risk score at/above which G3 downgrades the verdict to WARN
GATECHAIN_RISK_WARN_THRESHOLD: Final[float] = 6.0
# Danger level at/above which G4 escalates the call to L3 review
GATECHAIN_ESCALATION_DANGER: Final[int] = 4
# Sender identity used for gatechain-originated signals
GATECHAIN_SENDER: Final[str] = "gatechain"
# Target agent for gatechain escalation/review signals
GATECHAIN_L3_TARGET: Final[str] = "l3"
# Max ledger entries G5 reviews for repeat-history analysis
GATECHAIN_G5_HISTORY_LIMIT: Final[int] = 10
# Ledger history length at/above which G5 treats calls as repeated
GATECHAIN_REPEAT_THRESHOLD: Final[int] = 5
# Same-tool call count at/above which G5 flags high frequency
GATECHAIN_HIGH_FREQ_THRESHOLD: Final[int] = 3
# Weight of the tool danger level in the G5 risk score
GATECHAIN_DANGER_WEIGHT: Final[int] = 2
# Weight of the history length in the G5 risk score
GATECHAIN_HISTORY_WEIGHT: Final[float] = 0.5
# Weight of the same-tool frequency in the G5 risk score
GATECHAIN_FREQ_WEIGHT: Final[float] = 1.0
# Steps-list index holding the G1 verdict (first gate)
GATECHAIN_G1_INDEX: Final[int] = 0
# Steps-list index holding the G3 verdict (third gate)
GATECHAIN_G3_INDEX: Final[int] = 2
# Format string building the G1/G3 result pattern id
GATECHAIN_PATTERN_TEMPLATE: Final[str] = "G1-{g1}_G3-{g3}"
# Entry cap for the per-card ledger view exposed via the API
GATECHAIN_LEDGER_LIMIT: Final[int] = 100
# Reputation at/above which a G3 WARN is tolerated by G5
GATECHAIN_REP_HIGH_THRESHOLD: Final[float] = 0.9
# Reputation below which a G3 WARN becomes a G5 BLOCK
GATECHAIN_REP_LOW_THRESHOLD: Final[float] = 0.7


class GateStatus:
    """GateStatus — gate status record (PASS, WARN, BLOCK, REPORT)."""

    # Gate verdict: call cleared
    PASS: str = "PASS"
    # Gate verdict: cleared with a warning
    WARN: str = "WARN"
    # Gate verdict: call refused
    BLOCK: str = "BLOCK"
    # Gate verdict: repeated pattern detected, reported without hard block
    REPORT: str = "REPORT"


class WitnessStatus:
    """WitnessStatus — witness status record (PENDING, AWAITING, STILL_WAITING, APPROVED, REJECTED)."""

    # Witness request: submitted, awaiting a review slot
    PENDING: str = "PENDING"
    # Witness request: review assigned, waiting for the witness
    AWAITING: str = "AWAITING"
    # Witness request: reminder sent after the first wait window
    STILL_WAITING: str = "STILL_WAITING"
    # Witness request: approved by the reviewer
    APPROVED: str = "APPROVED"
    # Witness request: rejected by the reviewer
    REJECTED: str = "REJECTED"
