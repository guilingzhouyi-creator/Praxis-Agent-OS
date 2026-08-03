"""Install — first-run and upgrade lifecycle phase.

Called from boot.py when should_install() returns True.
Performs schema migrations, seeds defaults, and marks version.
"""

from __future__ import annotations

import json
import logging
import time

from l1.kernel.lifecycle import LifecycleState, get_lifecycle
from l1.kernel.migration import SCHEMA_VERSION, run_pending

logger = logging.getLogger(__name__)


def install() -> dict:
    lifecycle = get_lifecycle()
    lifecycle.load()

    if not lifecycle.transition(LifecycleState.INSTALLING):
        return {"success": False, "error": "cannot enter INSTALLING state"}

    results: dict = {}

    # 1. Schema migrations
    try:
        mig = run_pending(
            current=lifecycle._record.schema_version,
            target=SCHEMA_VERSION,
        )
        results["migrations"] = mig
    except Exception as e:
        results["migrations"] = {"error": str(e)}

    # 2. Ensure archive DB (idempotent)
    try:
        from l3.tools._archive import init_archive
        arch = init_archive()
        results["archive_init"] = arch.get("success", False)
    except Exception as e:
        results["archive_init"] = str(e)

    # 3. Seed archive defaults (first install only)
    try:
        if lifecycle._record.install_version == 0:
            from l3.tools._archive import _cmd_archive_store
            _cmd_archive_store(
                fonds="SYSTEM",
                series="lifecycle",
                content=json.dumps({
                    "event": "first_install",
                    "timestamp": time.time(),
                }),
                tags="system,lifecycle,first_install",
            )
            results["archive_seed"] = True
    except Exception as e:
        results["archive_seed"] = str(e)

    # 4. Seed card types if registry empty
    try:
        from l3.card.card_unified import list_card_types
        if not list_card_types():
            from l3.card.card_unified import register_card_type
            for name, defn in _CARD_TYPE_DEFAULTS.items():
                register_card_type(name, defn)
            results["card_types_seeded"] = list(_CARD_TYPE_DEFAULTS.keys())
    except Exception as e:
        results["card_types_seeded"] = str(e)

    # 5. Mark version
    lifecycle._record.install_version += 1
    lifecycle._record.schema_version = SCHEMA_VERSION
    lifecycle.save()

    lifecycle.transition(LifecycleState.BOOTING)

    logger.info("install complete: version=%d schema=%s",
                lifecycle._record.install_version,
                lifecycle._record.schema_version)
    return {"success": True, "results": results,
            "install_version": lifecycle._record.install_version,
            "schema_version": lifecycle._record.schema_version}


_CARD_TYPE_DEFAULTS: dict = {
    "execution": {
        "display": "Execution",
        "phases": ["plan", "implement", "verify"],
        "max_phases": 5,
        "concurrent_phases": False,
        "allow_fail": False,
        "timeline": 3600,
        "metadata_schema": {},
    },
    "review": {
        "display": "Review",
        "phases": ["review"],
        "max_phases": 1,
        "concurrent_phases": False,
        "allow_fail": True,
        "timeline": 1800,
        "metadata_schema": {},
    },
    "issue": {
        "display": "Issue",
        "phases": ["triage", "resolve", "verify"],
        "max_phases": 5,
        "concurrent_phases": False,
        "allow_fail": True,
        "timeline": 86400,
        "metadata_schema": {},
    },
    "inspection": {
        "display": "Inspection",
        "phases": ["audit", "report"],
        "max_phases": 3,
        "concurrent_phases": False,
        "allow_fail": True,
        "timeline": 3600,
        "metadata_schema": {},
    },
}
