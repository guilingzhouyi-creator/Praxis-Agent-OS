"""Card rollback — extracted from cell/__init__.py for modularity.

Contains Cell.rollback_card() logic.
"""

from __future__ import annotations

import logging
import os
import shutil

from l1.kernel.params.agent import CELL_HISTORY_RING_SIZE
from l3.cell.components.cell_buffer import CircularBuffer

logger = logging.getLogger(__name__)


def rollback_card(cell, card_id: str = "") -> dict:
    """Rollback changes from a card execution.

    Uses:
      1. fault_tolerance checkpoint (per-agent per-step)
      2. Pre-execution file snapshots (restore originals)
      3. Sandbox discard (pending changes)
      4. Terminal reset

    After rollback, stores info in _rollback_ring for the next card.
    """
    from l3.services.fault_tolerance import get_service as get_ft
    ft = get_ft()
    results = {}

    # 1. Restore checkpoints
    if card_id:
        cp_r = ft.restore_checkpoint(card_id)
        results["checkpoint_restore"] = cp_r
    else:
        with cell._lock:
            agents = list(cell._agents.keys())
        for aid in agents:
            ft.restore_checkpoint(aid)
        results["checkpoint_restore"] = {"agents": agents}

    # 2. Restore file snapshots
    snap_wrapper = cell._card_snapshots.pop(card_id, {})
    snap = snap_wrapper.get("files", snap_wrapper) if isinstance(snap_wrapper, dict) else {}
    restored_files = 0
    for original_path, tmp_path in snap.items():
        if original_path == "_ts":
            continue
        try:
            shutil.copy2(tmp_path, original_path)
            os.remove(tmp_path)
            restored_files += 1
        except Exception as e:
            logger.warning("rollback restore snapshot %s: %s", original_path, e)
    results["files_restored"] = restored_files

    # 3. Discard sandbox
    try:
        from l3.sandbox import get_cell_sandbox as _gcs
        sb = _gcs(cell.cell_id)
        discard_r = sb.discard()
        results["sandbox_discard"] = discard_r
    except Exception as e:
        results["sandbox_discard"] = {"error": str(e)}

    # 4. Reset terminals to IDLE
    from l3.agent_terminal import get_terminals
    terms = get_terminals()
    for aid in terms:
        try:
            terms[aid].pause()
            terms[aid].resume()
        except Exception as e:
            logger.warning("rollback reset terminal %s: %s", aid, e)
    results["terminals_reset"] = len(terms)

    # 5. Store rollback info in ring buffer
    rollback_msg = f"Card {card_id} was rolled back. {results.get('files_restored', 0)} files restored."
    cell._rollback_ring.push(rollback_msg)

    # 6. Remove from history ring
    if card_id:
        cell._card_history.remove(card_id)
    else:
        cell._card_history = CircularBuffer(CELL_HISTORY_RING_SIZE)

    # 7. Clean up CellCache / ICache / MMU-TLB — stale data from rolled-back execution
    try:
        if card_id:
            cell._cache.clear()
        cell._icache.remove_by_type("card")
        cell._mmu.flush_all()
    except Exception as e:
        logger.warning("rollback cache/icache/mmu cleanup: %s", e)
    results["caches_cleaned"] = True

    # 8. Trigger rollback event — notify InterruptController + EventBus
    try:
        cell._interrupt.trigger("cell.rollback", data={"card_id": card_id})
    except Exception as e:
        logger.debug("rollback interrupt: %s", e)

    logger.info("Cell %s rollback complete: %s", cell.cell_id, results)
    return {"success": True, "cell_id": cell.cell_id, "results": results,
            "rollback_context": rollback_msg}
