"""Constants: GateChain security gateway."""

from typing import Final


# ── GateChain ──

LEDGER_MAX_ENTRIES: Final[int] = 200
LEDGER_RECENT_LIMIT: Final[int] = 20
LEDGER_COUNT_WINDOW: Final[float] = 60.0
GATECHAIN_DEFAULT_DANGER: Final[int] = 1
GATECHAIN_DANGER_LEVELS: Final[dict[str, int]] = {
    "deploy": 5, "db_migrate": 4, "user_delete": 5,
    "destroy": 5, "rollback": 4, "migrate": 4,
    "exec": 4, "run_in_terminal": 3, "execute": 3,
    "delete": 3, "write": 2, "replace": 2, "format": 2,
}
GATECHAIN_TOOLS_KEY: Final[str] = "_tools"
GATECHAIN_FREQ_MULTIPLIER: Final[float] = 0.5
GATECHAIN_RISK_WARN_THRESHOLD: Final[float] = 6.0
GATECHAIN_ESCALATION_DANGER: Final[int] = 4
GATECHAIN_SENDER: Final[str] = "gatechain"
GATECHAIN_L3_TARGET: Final[str] = "l3"
GATECHAIN_G5_HISTORY_LIMIT: Final[int] = 10
GATECHAIN_REPEAT_THRESHOLD: Final[int] = 5
GATECHAIN_HIGH_FREQ_THRESHOLD: Final[int] = 3
GATECHAIN_DANGER_WEIGHT: Final[int] = 2
GATECHAIN_HISTORY_WEIGHT: Final[float] = 0.5
GATECHAIN_FREQ_WEIGHT: Final[float] = 1.0
GATECHAIN_G1_INDEX: Final[int] = 0
GATECHAIN_G3_INDEX: Final[int] = 2
GATECHAIN_PATTERN_TEMPLATE: Final[str] = "G1-{g1}_G3-{g3}"
GATECHAIN_LEDGER_LIMIT: Final[int] = 100
GATECHAIN_REP_HIGH_THRESHOLD: Final[float] = 0.9
GATECHAIN_REP_LOW_THRESHOLD: Final[float] = 0.7


class GateStatus:
    PASS: str = "PASS"
    WARN: str = "WARN"
    BLOCK: str = "BLOCK"
    REPORT: str = "REPORT"


class WitnessStatus:
    PENDING: str = "PENDING"
    AWAITING: str = "AWAITING"
    STILL_WAITING: str = "STILL_WAITING"
    APPROVED: str = "APPROVED"
    REJECTED: str = "REJECTED"
