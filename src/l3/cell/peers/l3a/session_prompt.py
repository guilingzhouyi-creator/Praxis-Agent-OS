"""SessionPromptMixin — prompt construction + context accounting for L3A Session.

Extracted from session.py (P1-1 split).  ``Message`` / ``_est_tokens`` are
imported lazily from session.py to avoid a circular import — by method-call
time the session module is fully loaded.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from l3.error_bus import capture

from . import params as _p

if TYPE_CHECKING:
    from l3.cell.peers.l3a.context import ContextEpoch, ContextRegistry
    from l3.cell.peers.l3a.inbox import PromptInbox
    from l3.cell.peers.l3a.model import L3AModelConfig
    from l3.cell.peers.l3a.session import SessionHistory

logger = logging.getLogger(__name__)


class SessionPromptMixin:
    """SessionPromptMixin — prompt building and context-window accounting."""

    # ── Attributes injected by the concrete Session (see session.py) ──
    id: str
    _cell_id: str
    turn_count: int
    last_active_at: float
    _ask: Any
    inbox: PromptInbox
    epoch: ContextEpoch | None
    registry: ContextRegistry | None
    history: SessionHistory
    model_config: L3AModelConfig
    _pmu: Any
    _loop: Any
    _ctx_window_cache: int
    _model_spec_cache: dict | None

    def _continue_after_ask(self, text: str) -> dict:
        """Resume the loop after clarification answers (provided by SessionAskMixin)."""
        raise NotImplementedError

    def _ensure_epoch(self) -> None:
        """Create the context epoch if absent (provided by Session)."""
        raise NotImplementedError

    def _ensure_loop(self) -> None:
        """Create the AgentLoop if absent (provided by Session)."""
        raise NotImplementedError

    def _persist_state(self) -> None:
        """Persist session state (provided by Session)."""
        raise NotImplementedError

    def _ingest_tool_results(self, result: dict, user_text: str) -> None:
        """Ingest tool results into memory (provided by Session)."""
        raise NotImplementedError

    def _ingest_reasoning(self, result: dict, user_text: str) -> None:
        """Ingest reasoning into memory (provided by Session)."""
        raise NotImplementedError

    def prompt(self, text: str, mode: str = "steer") -> dict:
        """Run one turn: admit the prompt, build context, execute the tool loop."""
        from l3.cell.peers.l3a.session import Message as _Message
        limits = self._resolve_limits()
        if limits["max_turns"] > 0 and self.turn_count >= limits["max_turns"]:
            return {"success": False, "error": f"max turns reached ({limits['max_turns']})"}
        # ASK awaiting: the chat input is treated as answers to the pending
        # clarification questions (chat-window semantics), then the loop resumes.
        if self._ask and self._ask.status == _p.ASK_STATUS_AWAITING:
            return self._continue_after_ask(text)
        self.inbox.admit(text, mode=mode)
        self.last_active_at = time.time()
        self._ensure_epoch()
        changes = self.epoch.sync(self.registry) if self.registry and self.epoch else []
        for c in changes:
            self.history.append(_Message(
                id=f"sys-{uuid.uuid4().hex[:4]}",
                role="system", content=c.text,
                metadata={"context_key": c.key},
            ))
        admitted = self.inbox.promote()
        if not admitted:
            return {"success": False, "error": "no pending prompt"}
        self.history.append(_Message(
            id=admitted.id, role="user", content=admitted.text,
        ))

        try:
            self._report_stats()
        except Exception:
            capture("l3a session: stats report failed", error_code="E_L3A_STATS", component="l3a")
            logger.warning("l3a session: stats report failed")
        ctx_trail = self.history.to_context_trail()
        # Task-aware injection: prompt keywords pick the dimension (execute→summary, decide→Mer, resume→layered)
        try:
            from l3.memory.memory_inject import build_context as _inject
            inject_block = _inject(_p.AGENT_ID, prompt=admitted.text,
                                   max_tokens=1024)
            if inject_block:
                ctx_trail.insert(0, {
                    "role": "system",
                    "content": f"[Task-Aware Memory]\n{inject_block}",
                })
        except Exception:
            logger.debug("l3a session: task-aware injection failed")
        self._ensure_loop()
        self._loop._context_trail = ctx_trail
        self._loop.task = admitted.text
        model_cfg = self._resolve_model_config()
        # Capture pre-call projected tokens for savings tracking
        pre_tokens = self.context_stats()["projected_tokens"]
        result = self._loop.run(
            max_steps=limits["max_steps"],
            timeout=limits["timeout"],
            model_config=model_cfg,
        )
        self.turn_count += 1
        answer = result.get("answer", "")
        tool_calls = result.get("tool_calls", [])
        reasoning = ""
        try:
            trail = getattr(self._loop, "_context_trail", None) or []
            for m in reversed(trail):
                if m.get("role") == "assistant":
                    reasoning = m.get("reasoning_content", "") or ""
                    break
        except Exception:
            logger.debug("l3a.session: reasoning extraction failed, proceeding without it", exc_info=True)
        answer_msg = _Message(
            id=f"asst-{uuid.uuid4().hex[:4]}",
            role="assistant", content=answer,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
        )
        self.history.append(answer_msg)
        self._persist_state()
        self._ingest_tool_results(result, admitted.text)
        self._ingest_reasoning(result, admitted.text)
        rtok = int(result.get("reasoning_tokens", 0) or 0)
        if rtok > 0:
            try:
                from l3.services.stats_center import MetricPoint as _Mp
                from l3.services.stats_center import get_center
                ts = time.time()
                get_center().ingest(_Mp(
                    name="l3a.tokens.reasoning", value=float(rtok),
                    tags={"session": self.id, "agent": _p.AGENT_ID},
                    timestamp=ts, metric_type="counter"))
            except Exception:
                logger.debug("l3a session: reasoning token stats failed")
        if rtok > 0:
            try:
                from l3.bus.monitor_bus import MonitorEvent as _ME4
                from l3.bus.monitor_bus import get_bus as _MB4
                _MB4().emit(_ME4(
                    type="stats.l3a.reasoning", source="l3a",
                    severity="info",
                    message=f"{self.id} turn {self.turn_count}: {rtok} thinking tokens",
                    agent_id=_p.AGENT_ID, cell_id=self._cell_id,
                    data={"session": self.id, "turn": self.turn_count,
                          "reasoning_tokens": rtok}))
            except Exception:
                logger.debug("l3a session: reasoning monitor emit failed")
        result["session_id"] = self.id
        result["turn"] = self.turn_count
        if self._ask and self._ask.status == _p.ASK_STATUS_AWAITING:
            result["ask"] = self._ask.to_dict()

        # Record tool call metrics to StatsCenter
        if tool_calls:
            t0 = time.time()
            try:
                from l3.services.stats_center import MetricPoint as _Mp
                from l3.services.stats_center import get_center
                sc = get_center()
                ts = time.time()
                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name", "unknown")
                    err = tc.get("error", "")
                    success = err == ""
                    latency = (time.time() - t0) / max(len(tool_calls), 1)
                    sc.ingest(_Mp(name="l3a.tools.executed", value=1.0,
                              tags={"tool": fn_name, "success": str(success).lower(),
                                    "session": self.id, "agent": _p.AGENT_ID},
                              timestamp=ts, metric_type="counter"))
                    sc.ingest(_Mp(name="l3a.tools.latency", value=round(latency, 3),
                              tags={"tool": fn_name, "session": self.id},
                              timestamp=ts, metric_type="gauge"))
                    sc.ingest(_Mp(name="l3a.tokens.consumed",
                              value=float(tc.get("tokens", 0)),
                              tags={"tool": fn_name, "session": self.id},
                              timestamp=ts, metric_type="counter"))
            except Exception:
                capture("l3a session: stats_center tool recording failed", error_code="E_L3A_SESSION", component="l3a")
                logger.debug("l3a session: stats_center tool recording failed")

        # Token savings tracking: compare projected vs actual
        post_tokens = self.context_stats()["projected_tokens"]
        token_saved = pre_tokens - post_tokens
        try:
            from l3.services.stats_center import MetricPoint as _Mp
            from l3.services.stats_center import get_center
            sc = get_center()
            ts = time.time()
            sc.ingest(_Mp(name="l3a.tokens.projected", value=float(pre_tokens),
                      tags={"session": self.id, "agent": _p.AGENT_ID},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(_Mp(name="l3a.tokens.actual", value=float(post_tokens),
                      tags={"session": self.id, "agent": _p.AGENT_ID},
                      timestamp=ts, metric_type="gauge"))
            if token_saved > 0:
                sc.ingest(_Mp(name="l3a.tokens.saved", value=float(token_saved),
                          tags={"session": self.id},
                          timestamp=ts, metric_type="counter"))
        except Exception:
            capture("l3a session: token savings recording failed", error_code="E_L3A_SESSION", component="l3a")
            logger.debug("l3a session: token savings recording failed")
        return result

    def context_stats(self) -> dict:
        """Compute session context pressure (epoch/history/projected vs window)."""
        from l3.cell.peers.l3a.session import _est_tokens
        epoch_tok = self.epoch.estimate_tokens() if self.epoch else 0
        history_tok = _est_tokens(
            " ".join(m.content for m in self.history._messages)
        ) if self.history._messages else 0
        projected = self.history.project()
        projected_tok = sum(_est_tokens(m.get("content", "")) for m in projected)
        window = self._query_context_window()
        pressure = projected_tok / window if window > 0 else 0.0
        level = "ok"
        if pressure >= 0.95:
            level = "critical"
        elif pressure >= 0.80:
            level = "medium"
        elif pressure >= 0.60:
            level = "warn"
        limits = self._resolve_limits()
        return {
            "epoch_id": self.epoch.id if self.epoch else "",
            "epoch_baseline_tokens": epoch_tok,
            "history_tokens": history_tok,
            "projected_tokens": projected_tok,
            "context_window": window,
            "pressure_ratio": round(pressure, 3),
            "pressure_level": level,
            "max_steps": limits["max_steps"],
            "max_turns": limits["max_turns"],
            "turns_used": self.turn_count,
        }

    def _query_context_window(self) -> int:
        """Resolve the LLM context window (cached, port-driven)."""
        if isinstance(self._ctx_window_cache, int) and self._ctx_window_cache > 0:
            return self._ctx_window_cache
        try:
            from l1.kernel.ports import get_port as _get_port
            engine = _get_port("llm")
            raw = engine.context_window(
                cell_id=self._cell_id, agent_id=_p.AGENT_ID)
            # The LLM port may return an int or a dict like
            # {"context_window": N, "source": "llm"} — normalize both.
            if isinstance(raw, dict):
                raw = raw.get("context_window", raw.get("max", 0))
            self._ctx_window_cache = int(raw or 0)
        except Exception:
            capture("l3a session: context window query failed", error_code="E_L3A_SESSION", component="l3a")
            self._ctx_window_cache = _p.CONTEXT_WINDOW_FALLBACK
        return self._ctx_window_cache

    def _resolve_model_config(self) -> dict:
        """Resolve effective model config (cached: spec overlays session cfg)."""
        if self._model_spec_cache:
            return self._model_spec_cache
        try:
            from l3.services.model_service import get_service as _gs
            spec = _gs().resolve_dict("l3a")
            cfg = self.model_config.resolve()
            cfg.update({k: v for k, v in spec.items() if k not in cfg or not cfg[k]})
            self._model_spec_cache = cfg
        except Exception:
            capture("l3a session: model spec resolve failed", error_code="E_L3A_SESSION", component="l3a")
            cfg = self.model_config.resolve()
            self._model_spec_cache = cfg
        return cfg

    def _resolve_limits(self) -> dict:
        """Resolve step/time/turn limits from SettingsCenter (with fallbacks)."""
        try:
            from l3.config.settings_center import get_center
            sc = get_center()
            l3a_steps = sc.get("l3a.max_steps", 0)
            loop_steps = sc.get("loop.max_steps", 0)
            steps = l3a_steps if l3a_steps > 0 else (loop_steps if loop_steps > 0 else _p.SESSION_MAX_STEPS_UNLIMITED)
            timeout = sc.get("l3a.timeout", sc.get("loop.timeout", 0))
            max_turns = sc.get("l3a.max_turns", sc.get("session.max_turns", 0))
        except Exception:
            capture("l3a session: limits resolve failed", error_code="E_L3A_SESSION", component="l3a")
            steps = _p.SESSION_MAX_STEPS_UNLIMITED
            timeout = 0
            max_turns = 0
        return {"max_steps": steps, "timeout": timeout, "max_turns": max_turns}

    def _report_stats(self) -> None:
        """Emit token/pressure/turn metrics to PMU + StatsCenter."""
        stats = self.context_stats()
        est = stats["projected_tokens"]
        pressure = stats["pressure_ratio"]
        level = stats["pressure_level"]

        if self._pmu:
            self._pmu.increment("token.estimated", est)
            if level == "critical":
                self._pmu.increment("memory.context.critical")
            elif level == "medium":
                self._pmu.increment("memory.context.warnings")

        try:
            from l3.services.stats_center import MetricPoint, get_center
            sc = get_center()
            ts = time.time()
            sc.ingest(MetricPoint(name="l3a.epoch.tokens", value=float(est),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(MetricPoint(name="l3a.epoch.pressure", value=float(pressure),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(MetricPoint(name="l3a.session.turns", value=float(self.turn_count),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(MetricPoint(name="l3a.session.tokens_consumed", value=float(est + stats["epoch_baseline_tokens"]),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="counter"))
        except Exception:
            capture("l3a session: StatsCenter ingest failed", error_code="E_L3A_STATS", component="l3a")
            logger.warning("l3a session: StatsCenter ingest failed")
