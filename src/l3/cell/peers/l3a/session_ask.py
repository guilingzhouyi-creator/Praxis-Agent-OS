"""SessionAskMixin — clarification (ask) state machine for L3A Session.

Extracted from session.py (P1-1 split).  ``Message`` is imported lazily from
session.py to avoid a circular import — by method-call time the session
module is fully loaded.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from . import params as _p

if TYPE_CHECKING:
    from l3.cell.peers.l3a.session import SessionHistory

logger = logging.getLogger(__name__)


class SessionAskMixin:
    """SessionAskMixin — pending-clarification state machine."""

    # ── Attributes injected by the concrete Session (see session.py) ──
    id: str
    turn_count: int
    last_active_at: float
    _ask: Any
    _loop: Any
    history: SessionHistory

    def _persist_state(self) -> None:
        """Persist session state (provided by Session)."""
        raise NotImplementedError

    def _report_stats(self) -> None:
        """Emit token/pressure/turn metrics (provided by SessionPromptMixin)."""
        raise NotImplementedError

    def _ensure_loop(self) -> None:
        """Create the AgentLoop if absent (provided by Session)."""
        raise NotImplementedError

    def _resolve_limits(self) -> dict:
        """Resolve step/time/turn limits (provided by SessionPromptMixin)."""
        raise NotImplementedError

    def _resolve_model_config(self) -> dict:
        """Resolve effective model config (provided by SessionPromptMixin)."""
        raise NotImplementedError

    def _ingest_tool_results(self, result: dict, user_text: str) -> None:
        """Ingest tool results into memory (provided by Session)."""
        raise NotImplementedError

    def ask_status(self) -> dict:
        """Public status of the pending clarification (empty when none)."""
        st = self._ask
        if not st:
            return {"success": True, "status": "none"}
        return {"success": True, "status": st.status, "ask": st.to_dict()}

    def submit_answers(self, answers: dict, free_form: str = "") -> dict:
        """Fill answers for pending questions (command/API path)."""
        from .ask import submit_answers as _submit
        r = _submit(self, answers, free_form)
        if r.get("success"):
            self._persist_state()
        return r

    def _continue_after_ask(self, text: str) -> dict:
        """Chat-window path: the next user input answers the pending questions.

        The raw text becomes the free-form answer plus a per-question fallback
        (structured ``q1=..; q2=..`` syntax is honored); the Q&A block is
        injected into history and the tool loop resumes.
        """
        from .ask import submit_answers as _submit
        answers: dict = {}
        if "=" in text:
            pairs = [part.strip() for part in text.split(";")]
            answers = {
                part.split("=", 1)[0].strip(): part.split("=", 1)[1].strip()
                for part in pairs if "=" in part
            }
        _submit(self, answers, text)
        return self.resume_after_ask()

    def resume_after_ask(self) -> dict:
        """Inject the answered Q&A block into history and resume the loop."""
        from .ask import build_answer_block
        from l3.cell.peers.l3a.session import Message as _Message
        st = self._ask
        if not st or st.status != _p.ASK_STATUS_ANSWERED:
            return {"success": False, "error": "no answered questions to resume"}
        block = build_answer_block(st)
        self.history.append(_Message(
            id=f"ask-{uuid.uuid4().hex[:4]}",
            role="user", content=block,
            metadata={"kind": "ask_answer"},
        ))
        self.last_active_at = time.time()
        try:
            self._report_stats()
        except Exception:
            logger.debug("l3a.session: stats report failed, skipped", exc_info=True)
        ctx_trail = self.history.to_context_trail()
        self._ensure_loop()
        self._loop._context_trail = ctx_trail
        self._loop.task = st.free_form or "continue after clarification"
        limits = self._resolve_limits()
        model_cfg = self._resolve_model_config()
        result = self._loop.run(
            max_steps=limits["max_steps"],
            timeout=limits["timeout"],
            model_config=model_cfg,
        )
        self.turn_count += 1
        answer = result.get("answer", "")
        tool_calls = result.get("tool_calls", [])
        answer_msg = _Message(
            id=f"asst-{uuid.uuid4().hex[:4]}",
            role="assistant", content=answer,
            tool_calls=tool_calls,
        )
        self.history.append(answer_msg)
        self._persist_state()
        self._ingest_tool_results(result, st.free_form or "clarification")
        return {
            "success": True,
            "session_id": self.id,
            "answer": answer,
            "tool_calls": tool_calls,
            "ask_resolved": True,
            "turn_count": self.turn_count,
        }
