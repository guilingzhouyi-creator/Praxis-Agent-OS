"""Shared helpers — cardwrite handler, prompt builder, etc."""

from __future__ import annotations

import logging

from l3.card.card_unified import CardSummary, CardUnified, PhaseMode, list_card_types
from l3.error_bus import capture
from l3.services.assembly import AssemblyMode

logger = logging.getLogger(__name__)


def _inject_enabled(domain: str) -> bool:
    """Whether the ``prompt.inject.<domain>`` system-prompt injection is on."""
    from l1.kernel.settings import inject_enabled as _ie

    return _ie(domain)


def build_l3a_prompt(user_id: str = "") -> str:
    """Build the L3A agent-loop system prompt.

    When the user profile side-channel is enabled and a user_id is given,
    a condensed profile reference (preferences + traits) is appended so the
    central layer knows the user's established style — best-effort, never
    raises, zero impact when disabled.
    """
    from l1.kernel.prompts import get_prompt as _gp
    types = list_card_types()
    types_block = "\n".join(
        f"  - {t['name']}: {t['display']} (phases: {', '.join(t.get('phases', []))})"
        for t in types
    )
    prompt = _gp("l3a.agentloop_system").format(card_types=types_block)
    if user_id and _inject_enabled("profile"):
        try:
            from l3.services.user_profile import get_service as _prof

            prof = _prof()
            if prof.enabled:
                snap = prof.get_profile(user_id, kinds=("preference", "trait"))
                entries = snap.get("entries") or []
                if entries:
                    block = "\n".join(
                        f"  - [{e['kind']}] {e['value']}" for e in entries[:10])
                    prompt += f"\n\n[User Profile Reference]\n{block}"
        except Exception:
            pass
    return prompt


def cardwrite_handler(args: dict, agent_id: str = "") -> dict:
    from l3.card.card_registry import get_registry
    nature = args.get("nature", "execution")
    title = args.get("title", args.get("intent", ""))
    description = args.get("description", "")
    columns = args.get("columns", {})
    priority = args.get("priority", 5)
    phases_data = args.get("phases", [])
    domain = columns.get("domain", "")

    # User profile reference (side-channel): attach a condensed profile to the
    # card columns when the profile service is enabled — downstream intent
    # parsing and agent context can consult it without blocking the submit.
    # Gated by the prompt.inject.profile setting (user-configurable).
    user_id = str(args.get("user_id") or "").strip()
    if user_id and _inject_enabled("profile"):
        try:
            from l3.services.user_profile import get_service as _prof

            prof = _prof()
            if prof.enabled:
                snap = prof.get_profile(
                    user_id, kinds=("preference", "domain_focus", "trait"))
                if snap.get("entries"):
                    columns["_profile_summary"] = snap
        except Exception:
            pass

    card = CardUnified(nature=nature, priority=priority)
    card.summary = CardSummary(title=title, description=description, columns=columns)
    for pd in phases_data:
        mode_str = pd.get("mode", "single")
        mode = PhaseMode.MULTI if mode_str == "multi" else PhaseMode.SINGLE
        phase = card.add_phase(name=pd.get("name", ""), mode=mode,
                               agents=pd.get("agents", []),
                               review_prompt=pd.get("review_prompt", ""),
                               strategy=pd.get("strategy", ""))
        for td in pd.get("tasks", []):
            card.add_task(phase_name=phase.name, action=td.get("action", ""),
                          target=td.get("target", ""), params=td.get("params", {}),
                          agent=td.get("agent", ""))
    card.submit()

    try:
        reg = get_registry()
        cid = reg.submit(intent=title, domain=domain, priority=priority, card_id=card.id)
        with reg._lock:
            reg._cards[cid] = card
        mode = _route_to_assembly(card)
        card.summary.columns["_assembly_mode"] = mode.value
        return {"success": True, "card_id": card.id, "nature": nature,
                "phases": len(phases_data), "message": f"Card {card.id} submitted"}
    except Exception as e:
        return {"success": False, "error": str(e), "card_id": card.id}


def wrapped_cardwrite(args: dict, agent_id: str = "") -> dict:
    return cardwrite_handler(args, agent_id)


def _route_to_assembly(card: CardUnified) -> AssemblyMode:
    from .types import AssemblyMode
    try:
        from l3.card.card_gate import evaluate as _gate_evaluate
        r = _gate_evaluate(card_id=card.id,
                           intent=card.summary.title if card.summary else "",
                           domain=getattr(card, "domain", ""),
                           file_count=0, estimated_lines=0, has_conflict=False)
        size = r.get("size", "small")
        if r.get("auto_approve", False):
            return AssemblyMode.AUTO_APPROVE
        if size == "disputed":
            return AssemblyMode.CONFERENCE
        if size in ("large", "medium"):
            return AssemblyMode.DEFAULT
        return AssemblyMode.DEFAULT
    except Exception:
        capture("l3a helpers: card gate evaluate failed", error_code="E_L3A_HELPERS", component="l3a")
        # Fail-safe: when the gate itself errors, do NOT auto-approve — park for review.
        return AssemblyMode.DEFAULT


def get_convergence_queue(cell_id: str) -> list[dict]:
    try:
        from l3.cell import get_cell
        from l3.discussion.cell_answer_repo import CellAnswerRepo
        cell = get_cell(cell_id)
        if not cell:
            return []
        repo = CellAnswerRepo(cell_id, "")
        answers = repo.get_all()
        return [{"agent_id": a.agent_id, "phase": a.phase, "type": a.answer_type,
                 "fingerprint": a.fingerprint, "created_at": a.created_at}
                for a in answers]
    except Exception:
        capture("l3a helpers: convergence queue load failed", error_code="E_L3A_HELPERS", component="l3a", context={"cell_id": cell_id})
        return []


def l3a_convention_handler(args: dict, agent_id: str = "") -> dict:
    """Read a converged convention document on demand.

    Three navigation modes (issue_id always required):
      action=index   → structured index: issues [I-N] with status/assignee,
                       decisions [D-M], participants, round count
      anchor=I-2     → that issue block only (question + answer + meta)
      anchor=D-1     → that decision block only
      agent=agent-b  → all transcript lines where agent-b spoke or was addressed
      (none)         → bounded full read (max_chars; 0 = full)

    The full .md lives on disk under data_dir/conventions/ — sessions carry
    only a summary + reference, this tool fetches details when needed.
    """
    issue_id = args.get("issue_id", "")
    if not issue_id:
        return {"success": False, "error": "issue_id required"}
    action = args.get("action", "")
    anchor = args.get("anchor", "")
    agent_filter = args.get("agent", "")
    max_chars = int(args.get("max_chars", 0))

    content = _read_convention_doc(issue_id)
    if content is None:
        return {"success": False,
                "error": f"convention doc not found: {issue_id}"}
    size = len(content)

    if action == "index":
        return {"success": True, "issue_id": issue_id, "action": "index",
                "index": _build_index(content)}

    if anchor:
        block = _extract_block(content, anchor)
        if block is None:
            return {"success": False, "error": f"anchor not found: {anchor}",
                    "valid_anchors": _list_anchors(content)}
        return {"success": True, "issue_id": issue_id, "anchor": anchor,
                "content": block, "size": len(block)}

    if agent_filter:
        block = _extract_agent_lines(content, agent_filter)
        return {"success": True, "issue_id": issue_id, "agent": agent_filter,
                "content": block, "lines": block.count("\n- ["),
                "size": len(block)}

    if max_chars > 0 and size > max_chars:
        content = content[:max_chars] + f"\n... ({size - max_chars} chars elided, use action=index / anchor= to navigate)"
    return {"success": True, "issue_id": issue_id, "size": size,
            "content": content}


def _read_convention_doc(issue_id: str) -> str | None:
    try:
        import os as _os

        from l1.kernel.params.agent import CONVENTION_DOC_DIR
        from l1.kernel.paths import get_paths as _gp
        path = _os.path.join(_gp().data_dir, CONVENTION_DOC_DIR, f"{issue_id}.md")
        if _os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    except Exception:
        capture("l3a helpers: spill read failed", error_code="E_L3A_HELPERS", component="l3a")
        pass
    # fall back to R4 archive
    try:
        from l3.tools._archive import _get_db
        conn = _get_db()
        row = conn.execute(
            "SELECT content FROM archive WHERE fonds = ? ORDER BY id DESC LIMIT 1",
            (f"CONVENTION:{issue_id}",),
        ).fetchone()
        return row[0] if row else None
    except Exception:
        capture("l3a helpers: convention doc fetch failed", error_code="E_L3A_HELPERS", component="l3a", context={"issue_id": issue_id})
        return None


def _build_index(content: str) -> dict:
    issues, decisions, participants, rounds = [], [], [], 0
    for line in content.splitlines():
        if line.startswith("### [I-"):
            issues.append({"anchor": f"I-{len(issues) + 1}",
                           "title": line.split("]", 1)[1].strip()})
        elif line.startswith("### [D-"):
            decisions.append({"anchor": f"D-{len(decisions) + 1}"})
        elif line.startswith("<!-- issue-id:"):
            if issues:
                m = _kv(line)
                issues[-1].update({"status": m.get("status", ""),
                                   "assigned_to": m.get("assigned_to", ""),
                                   "domain": m.get("domain", ""),
                                   "proposed_by": m.get("proposed_by", "")})
        elif line.startswith("### Round "):
            rounds += 1
        elif line.startswith("- [") and " → " in line:
            speaker = line.split("[", 1)[1].split("]", 1)[0].split(" ", 1)[-1]
            # speaker is the second word after msg_type: "[cross_examine] agent-a"
            parts = line.lstrip("- ").split("]", 1)
            if len(parts) == 2:
                speaker = parts[1].split(" → ")[0].strip()
            if speaker and speaker not in participants:
                participants.append(speaker)
    # meta line for agents
    for line in content.splitlines():
        if line.startswith("<!-- meta:"):
            m = _kv(line)
            agents = m.get("agents", "")
            if agents:
                participants = [a for a in agents.split(",") if a]
            rounds = int(m.get("rounds", rounds))
            break
    return {"issues": issues, "decisions": decisions,
            "participants": participants, "rounds": rounds}


def _extract_block(content: str, anchor: str) -> str | None:
    lines = content.splitlines()
    start = None
    marker = f"### [{anchor}]" if anchor.startswith(("I-", "D-")) else None
    for i, ln in enumerate(lines):
        if marker and ln.startswith(marker):
            start = i
            break
    if start is None:
        return None
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.startswith("### [") or ln.startswith("## "):
            break
        block.append(ln)
    return "\n".join(block).strip()


def _extract_agent_lines(content: str, agent: str) -> str:
    out = [f"# Agent {agent} — convention transcript"]
    for line in content.splitlines():
        if line.startswith("- [") and agent in line or f"({agent})" in line and "**Answer**" in line:
            out.append(line)
    return "\n".join(out)


def _list_anchors(content: str) -> list[str]:
    anchors = []
    for line in content.splitlines():
        if line.startswith("### [I-"):
            anchors.append("I-" + line.split("[I-", 1)[1].split("]", 1)[0])
        elif line.startswith("### [D-"):
            anchors.append("D-" + line.split("[D-", 1)[1].split("]", 1)[0])
    return anchors


def _kv(comment_line: str) -> dict:
    """Parse '<!-- k: v | k2: v2 -->' into dict."""
    inner = comment_line.strip()
    inner = inner.removeprefix("<!--").removesuffix("-->").strip()
    result = {}
    for part in inner.split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def l3a_summary_handler(args: dict, agent_id: str = "") -> dict:
    """Query L3A's dedicated deliberation-memory store (bypass memory).

    action=latest [domain] [limit]  → recent distilled summaries
    action=search <query> [limit]   → keyword search across summaries
    action=get <issue_id>           → one full summary (incl. overlap notes)
    (default)                       → store stats
    """
    from .summaries import get_store
    store = get_store()
    action = args.get("action", "stats")
    if action == "get":
        issue_id = args.get("issue_id", "")
        s = store.get(issue_id)
        if not s:
            return {"success": False,
                    "error": f"summary not found: {issue_id}"}
        return {"success": True, "data": s.to_dict()}
    if action == "search":
        query = args.get("query", "")
        if not query:
            return {"success": False, "error": "query required"}
        limit = int(args.get("limit", 5))
        hits = store.search(query, limit=limit)
        return {"success": True, "data": [s.to_dict() for s in hits],
                "count": len(hits)}
    if action == "latest":
        domain = args.get("domain", "")
        limit = int(args.get("limit", 5))
        hits = store.latest(domain=domain, limit=limit)
        return {"success": True, "data": [s.to_dict() for s in hits],
                "count": len(hits)}
    return {"success": True, "data": {
        "total": store.count(),
        "recent": [s.to_dict() for s in store.latest(limit=3)],
    }}
