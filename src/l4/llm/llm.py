"""LLM inference engine — provider-agnostic interface for agent thinking.

Each call goes through the kernel device manager for rate limiting.
Supports multiple providers: Claude, GPT, local, or mock (for testing).

Usage:
  from l4.llm.llm import think, analyze

  result = think("What is the capital of France?", system="You are a helpful assistant")
  # → {"content": "Paris", "tokens": 15, "model": "claude-3-haiku"}

  result = analyze("review this code", code_snippet, context="security audit")
  # → {"content": "Found 3 vulnerabilities...", "findings": [...]}
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from l1.kernel.device import get_device_manager
from l1.kernel.params.system import CONTEXT_TRAIL_TRUNC, HASH_TRUNC_SHORT, LOG_TRUNC_200, LOG_TRUNC_60

from l1.kernel.params.agent import (
    LLM_ANALYZE_MAX_TOKENS,
    LLM_CACHE_RETENTION_THRESHOLD,
    LLM_CACHE_RETENTION_STRING,
    LLM_THINKING_BUFFER,
    LLM_TOOL_RESULT_TRUNCATION,
    LOOP_TURN_WARNING_THRESHOLD,
)
from l1.kernel.params.api import (
    DEFAULT_REASONING_EFFORT,
    DEFAULT_THINKING_BUDGET,
    FALLBACK_LLM_API_URL,
    FALLBACK_MODEL,
    LLM_DEFAULT_MAX_TOKENS,
    LLM_EMPTY_RESPONSE_WAITS,
    LLM_HTTP_TIMEOUT,
    LLM_MAX_EMPTY_RETRIES,
    LLM_MAX_OVERFLOW_RETRIES,
    LLM_MAX_RATE_LIMIT_RETRIES,
    LLM_MAX_TRANSIENT_RETRIES,
    LLM_RATE_LIMIT_WAIT,
    LLM_TRANSIENT_BACKOFF_BASE,
)
from l1.kernel.params.tool import TOOL_HANDLER_TIMEOUT as _TOOL_HANDLER_TIMEOUT
from l1.kernel.params.system import TOOL_SEARCH_MIN_COUNT as _TOOL_SEARCH_MIN_COUNT, TOOL_SEARCH_MAX_RESULTS as _TOOL_SEARCH_MAX_RESULTS
from l1.kernel.discovery import get_tool_config

# Resolve tool config at module level (lazy-safe: discovery may not be ready at import)
_LLM_TOOL_TIMEOUT = get_tool_config("handler_timeout", _TOOL_HANDLER_TIMEOUT) or _TOOL_HANDLER_TIMEOUT

# Base types extracted to llm_base.py
from .llm_base import (
    _PROVIDER_REGISTRY,
    LLMConfig,
    LLMProvider,
    ToolSearch,
    register_provider,
)

# Provider implementations extracted to llm_providers.py
from .llm_providers import MockProvider, WebSocketProvider
from l3.tool_system.tool_spec import ToolSpec

logger = logging.getLogger(__name__)


class LLMEngine:
    """Inference engine — routes prompts to the configured provider."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._provider = self._build_provider()
        self._http_opener = self._build_http_opener()

    @staticmethod
    def _build_http_opener():
        """Build a shared HTTP opener with keep-alive for connection reuse."""
        import urllib.request as req
        return req.build_opener()

    def _get_strategy(self):
        from l3.config.cache_strategy import get_strategy
        return get_strategy(self.config.provider)

    def context_window(self, cell_id: str = "", agent_id: str = "") -> int:
        """Query the effective context window for the current provider+model.

        Resolution chain:
          1. ModelStrategyEngine.resolve() → check strategy config for context_window
          2. CapabilityDetector probe cache → detected context_window
          3. Return 0 = unknown (no compression, caller uses fallback)

        Args:
            cell_id: Cell identifier for strategy resolution.
            agent_id: Agent identifier for strategy resolution.
        """
        try:
            from l3.services.model_strategy import get_engine as _strat
            strat = _strat()
            pname = getattr(self._provider, "name", "")
            pmodel = getattr(self._provider, "model", "")
            resolved = strat.resolve(cell_id, agent_id,
                                     provider_name=pname, model=pmodel)
            cw = resolved.get("context_window", 0)
            return cw if cw > 0 else 0
        except Exception:
            return 0

    def _build_provider(self) -> LLMProvider:
        """Construct a provider instance using ModelRegistry.

        Falls back to MockProvider if no matching provider is found.
        """
        from l1.kernel.model_registry import get_registry

        p = self.config.provider
        if self.config.use_websocket:
            from .llm_providers import WebSocketProvider
            return WebSocketProvider(self.config.api_url, self.config.model, self.config.api_key)

        registry = get_registry()
        provider = registry.build_provider(
            provider=p,
            model=self.config.model,
            api_key=self.config.api_key,
            api_url=self.config.api_url,
            cache_breakpoints=self.config.cache_breakpoints,
        )
        if provider is not None:
            return provider

        logger.warning("llm: no provider '%s', using MockProvider", p)
        from .llm_providers import MockProvider
        return MockProvider()

    def _apply_strategy(self, overrides: dict) -> dict:
        """Apply ModelStrategyEngine filtering: remove params the provider doesn't support."""
        try:
            from l3.services.model_strategy import get_engine as _strat
            strat = _strat()
            provider_name = getattr(self._provider, "name", "")
            model = getattr(self._provider, "model", "")
            filtered = strat.resolve("", "", provider_name=provider_name, model=model)
            # Take only strategy keys from filtered; keep override keys
            for k in filtered:
                if k in overrides:
                    filtered[k] = overrides[k]
            return filtered
        except Exception:
            return overrides

    def generate(self, prompt: str, system: str = "",
                 max_tokens: int | None = None, user_id: str = "",
                 **overrides: Any) -> dict:
        """Generate a plain-text response from the LLM (no tool calls)."""
        dm = get_device_manager()
        r = dm.check_rate(self.config.device_name)
        if r.get("error", "").startswith("unknown device"):
            pass
        elif not r.get("allowed"):
            wait = r.get("reset_after", 1)
            logger.warning("LLM rate limited, waiting %.1fs", wait)
            time.sleep(wait)

        mt = max_tokens or self.config.max_tokens

        # Pre-call hooks
        hook_kwargs = {"prompt": prompt, "system": system,
                       "max_tokens": mt, "user_id": user_id}
        for hook in _LLM_HOOKS.get("pre", []):
            try:
                hook(**hook_kwargs)
            except Exception as e:
                logger.warning("services/llm: %s", e)

        prompt, system, cache_extra = self._get_strategy().optimize(prompt, system, user_id)
        merged = {**cache_extra, **overrides,
                  "reasoning_effort": overrides.get("reasoning_effort", self.config.reasoning_effort),
                  "thinking_budget": overrides.get("thinking_budget", self.config.thinking_budget)}
        # Filter by provider capabilities
        strategy_params = self._apply_strategy(merged)

        result = self._provider.generate(
            prompt, system, mt, user_id=user_id,
            cache_retention=self.config.cache_retention,
            **strategy_params,
        )

        # Post-call hooks
        for hook in _LLM_HOOKS.get("post", []):
            try:
                hook(result=result, **hook_kwargs)
            except Exception as e:
                logger.warning("LLM post-hook failed: %s", e)

        dm.record_call(self.config.device_name, success="error" not in result)
        return result

    def generate_with_cache(self, prompt: str, system: str = "",
                 max_tokens: int | None = None, user_id: str = "") -> dict:
        """Generate with KV cache tracking. Pass user_id for per-agent cache isolation.

        DeepSeek: user_id maps to agent_id → independent KV cache namespace.
        Returns cache hit/miss tokens alongside response.
        """
        result = self.generate(prompt, system, max_tokens, user_id=user_id)
        # Ensure cache stats are present (providers may already populate them)
        if "cache_hit_tokens" not in result:
            result["cache_hit_tokens"] = 0
        if "cache_miss_tokens" not in result:
            # Use input_tokens (prompt tokens only, not total) for accurate miss count
            input_tokens = result.get("input_tokens", result.get("tokens", len(prompt) // 4))
            result["cache_miss_tokens"] = input_tokens - result.get("cache_hit_tokens", 0)
        # Calculate hit rate
        total = result["cache_hit_tokens"] + result["cache_miss_tokens"]
        result["cache_hit_rate"] = round(result["cache_hit_tokens"] / total * 100, 1) if total > 0 else 0.0
        return result

    @property
    def provider_name(self) -> str:
        """Return the current provider's name (e.g. 'openai', 'anthropic')."""
        return self.config.provider

    @staticmethod
    def _execute_one_tool(tool_def, fn_args, call_id, fn_name):
        if tool_def and tool_def.handler:
            result = tool_def.handler(fn_args, "")
            return {"name": fn_name, "arguments": fn_args, "result": result, "call_id": call_id}
        return {"name": fn_name, "arguments": fn_args, "error": "no handler", "call_id": call_id}

    def tool_use(self, prompt: str, tools: list[ToolSpec], system: str = "",
                 max_turns: int = 5, user_id: str = "",
                 context_trail: list[dict] | None = None,
                 **overrides: Any) -> dict:
        """LLM autonomously calls tools to fulfill a task.

        Args:
            prompt: The user's task description
            tools: List of ToolDef definitions the LLM can call
            system: System prompt
            max_turns: Max tool-call iterations
            user_id: Per-agent KV cache isolation (DeepSeek) or cache_control key
            context_trail: Previous conversation turns for continuity

        Returns:
            {"content": final_response, "tool_calls": [...], "turns": N, "context_trail": [...]}
        """
        import json as _json
        import uuid

        prompt, system, cache_extra = self._get_strategy().optimize(prompt, system, user_id)

        messages = list(context_trail or [])
        if system and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # ToolSearch: defer loading — only send relevant tools (saves ~10-18% tokens)
        if self.config.tool_search and len(tools) > _TOOL_SEARCH_MIN_COUNT:
            ts = ToolSearch()
            ts.register_many(tools)
            active_tools = ts.search(prompt, max_results=_TOOL_SEARCH_MAX_RESULTS)
            logger.debug("tool_search: %d → %d tools for prompt[:LOG_TRUNC_60]",
                        len(tools), len(active_tools))
        else:
            active_tools = tools

        tool_defs = [t.to_api_format() for t in active_tools]
        tool_map = {t.name: t for t in tools}
        all_calls = []
        import concurrent.futures as _cf

        for turn in range(max_turns):

            # ── Inject turn budget warning ──
            remaining = max_turns - turn
            from l1.kernel.prompts import get_prompt as _gp
            if remaining <= LOOP_TURN_WARNING_THRESHOLD and messages:
                warning = {"role": "user", "content": _gp("llm.turn_budget_warning", "").format(remaining=remaining)}
                messages.append(warning)

            # Build request with tool definitions
            merged = {**cache_extra, **overrides}
            # Apply provider capability filtering
            strategy_params = self._apply_strategy(merged)
            model_name = strategy_params.get("model", self.config.model) if self.config and self.config.model else FALLBACK_MODEL
            max_tok = strategy_params.get("max_tokens", self.config.max_tokens)
            temp = strategy_params.get("temperature", self.config.temperature)
            reff = strategy_params.get("reasoning_effort", "")
            tbud = strategy_params.get("thinking_budget", 0)

            body_dict: dict = {
                "model": model_name,
                "messages": messages,
                "tools": tool_defs,
                "max_tokens": max_tok,
                "temperature": temp,
            }
            if user_id:
                body_dict["user_id"] = user_id
            if self.config.cache_retention >= LLM_CACHE_RETENTION_THRESHOLD:
                body_dict["prompt_cache_retention"] = LLM_CACHE_RETENTION_STRING
            if reff and reff != "none":
                body_dict["reasoning_effort"] = reff
            if tbud > 0:
                body_dict["thinking"] = {"type": "enabled", "budget_tokens": tbud}
                body_dict["max_tokens"] = max(max_tok, tbud + LLM_THINKING_BUFFER)
            body = _json.dumps(body_dict).encode()

            try:
                response = self._call_api(body)
                content = response.get("content", "")
                tool_calls = response.get("tool_calls", [])

                if not tool_calls:
                    # LLM finished — no more tool calls
                    return {"content": content, "tool_calls": all_calls, "turns": turn + 1, "context_trail": messages[-CONTEXT_TRAIL_TRUNC:]}

                # Execute tool calls in parallel with per-handler timeout
                assistant_msg = {"role": "assistant", "content": content, "tool_calls": [tc for tc in tool_calls]}
                messages.append(assistant_msg)

                with _cf.ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
                    futures = {}
                    for tc in tool_calls:
                        fn_name = tc.get("function", {}).get("name", "")
                        fn_args = _json.loads(tc.get("function", {}).get("arguments", "{}"))
                        call_id = tc.get("id", uuid.uuid4().hex[:HASH_TRUNC_SHORT])
                        tool_def = tool_map.get(fn_name)
                        futures[pool.submit(LLMEngine._execute_one_tool, tool_def, fn_args, call_id, fn_name)] = tc

                    for future in _cf.as_completed(futures, timeout=_LLM_TOOL_TIMEOUT * 2):
                        tc = futures[future]
                        try:
                            call_record = future.result()
                        except _cf.TimeoutError:
                            call_record = {
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": {}, "error": "timeout",
                                "call_id": tc.get("id", uuid.uuid4().hex[:HASH_TRUNC_SHORT]),
                            }
                        except Exception as e:
                            call_record = {
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": {}, "error": str(e),
                                "call_id": tc.get("id", uuid.uuid4().hex[:HASH_TRUNC_SHORT]),
                            }
                        all_calls.append(call_record)
                        result_str = _json.dumps(
                            call_record.get("result", call_record.get("error", "")),
                            ensure_ascii=False,
                        )[:LLM_TOOL_RESULT_TRUNCATION]
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_record["call_id"],
                            "content": result_str,
                        })

            except Exception as e:
                return {"content": "", "tool_calls": all_calls, "turns": turn + 1, "error": str(e), "context_trail": messages[-CONTEXT_TRAIL_TRUNC:]}

        return {"content": "Max turns reached", "tool_calls": all_calls, "turns": max_turns, "context_trail": messages[-CONTEXT_TRAIL_TRUNC:]}

    def _call_api(self, body: bytes, retry_count: int = 0) -> dict:
        """Low-level API call with retry layers. Returns parsed response dict with cache stats.

        Retry layers (AtomCode-style):
          1. Overflow (context too long) → compact + retry (3 attempts)
          2. Transient (5xx/timeout) → linear backoff 3/6/9s (3 attempts)
          3. Empty response (200 with no content) → retry 1/1/2/2/3s (5 attempts)
          4. Rate limit (429) → wait from Retry-After header or 60s (5 attempts)
        """
        import time as _time
        import urllib.error
        import urllib.request as req

        provider_name = self.config.provider
        if provider_name == "mock":
            data = json.loads(body)
            prompt = data["messages"][-1]["content"]
            return {"content": f"[mock] tool_use: {prompt[:LOG_TRUNC_60]}...", "tool_calls": [],
                    "cache_hit_tokens": 0, "cache_miss_tokens": 0}

        provider = self._provider
        headers = {"Content-Type": "application/json"}
        try:
            headers.update(provider.get_headers())
        except Exception as e:
            logger.warning("provider get_headers failed: %s", e)
        url = provider.get_api_url(self.config.api_url)

        try:
            r = self._http_opener.open(req.Request(url, data=body, headers=headers, method="POST"), timeout=LLM_HTTP_TIMEOUT)
            raw = r.read()
        except urllib.error.HTTPError as e:
            code = e.code
            body_text = e.read().decode()[:LOG_TRUNC_200]
            if code == 429 and retry_count < LLM_MAX_RATE_LIMIT_RETRIES:
                wait = LLM_RATE_LIMIT_WAIT
                if hasattr(e, 'headers'):
                    ra = e.headers.get("Retry-After", "")
                    if ra and ra.isdigit():
                        wait = int(ra)
                _time.sleep(wait)
                return self._call_api(body, retry_count + 1)
            if code in (413, 400) and "too long" in body_text.lower() and retry_count < LLM_MAX_OVERFLOW_RETRIES:
                logger.warning("llm overflow, compact+retry (attempt %d/%d)", retry_count + 1, LLM_MAX_OVERFLOW_RETRIES)
                try:
                    from .memory.memory import get_memory
                    get_memory().compact("system")
                except Exception:
                    logger.debug("llm: memory compact failed")
                return self._call_api(body, retry_count + 1)
            return {"content": "", "tool_calls": [], "cache_hit_tokens": 0, "cache_miss_tokens": 0,
                    "error": f"HTTP {code}: {body_text}"}
        except Exception as e:
            err = str(e)
            if any(x in err for x in ("timeout", "reset", "refused", "500", "502", "503")):
                if retry_count < LLM_MAX_TRANSIENT_RETRIES:
                    wait = LLM_TRANSIENT_BACKOFF_BASE * (retry_count + 1)
                    _time.sleep(wait)
                    return self._call_api(body, retry_count + 1)
            return {"content": "", "tool_calls": [], "cache_hit_tokens": 0, "cache_miss_tokens": 0,
                    "error": err}

        try:
            data = json.loads(raw)
        except Exception:
            return {"content": "", "tool_calls": [], "cache_hit_tokens": 0, "cache_miss_tokens": 0,
                    "error": f"json decode: {raw[:LOG_TRUNC_200]}"}

        # Empty response detection
        content = ""
        tool_calls = []
        if isinstance(data, dict):
            msg = data.get("choices", [{}])[0].get("message", {}) if "choices" in data else {}
            content = msg.get("content", "") or data.get("content", "")
            tool_calls = msg.get("tool_calls", []) or data.get("tool_calls", [])
        if not content and not tool_calls and retry_count < LLM_MAX_EMPTY_RETRIES:
            wait = LLM_EMPTY_RESPONSE_WAITS[retry_count]
            _time.sleep(wait)
            return self._call_api(body, retry_count + 1)

        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        cache_hit = usage.get("prompt_cache_hit_tokens", usage.get("cache_hit", 0))
        cache_miss = usage.get("prompt_cache_miss_tokens",
                       usage.get("cache_miss",
                       usage.get("prompt_tokens", 0) - (usage.get("prompt_cache_hit_tokens", 0) if "prompt_tokens" in usage else 0)))

        if provider_name in ("ollama",):
            msg = data.get("message", {})
            return {"content": msg.get("content", ""), "tool_calls": msg.get("tool_calls", []),
                    "cache_hit_tokens": cache_hit, "cache_miss_tokens": cache_miss}

        if provider_name in ("openai",):
            choice = data["choices"][0]["message"]
            return {"content": choice.get("content", ""), "tool_calls": choice.get("tool_calls", []),
                    "cache_hit_tokens": cache_hit, "cache_miss_tokens": cache_miss}

        return {"content": "", "tool_calls": [],
                "cache_hit_tokens": cache_hit, "cache_miss_tokens": cache_miss}


# ── LLMPort adapter (breaks L3→L4 dependency) ──


def _register_llm_port(engine: LLMEngine) -> None:
    """Wrap LLMEngine as an LLMPort and register it in the kernel port registry.

    Registered as "llm" so L3 callers can use ``get_port("llm")`` instead of
    importing from ``l4.llm.llm`` directly.
    """
    from l1.kernel.ports import register_port, LLMPort

    class _LLMEngineAdapter(LLMPort):
        """Thin adapter: LLMEngine → LLMPort interface."""

        def tool_use(self, prompt: str, tools: list,
                     system: str = "", max_turns: int = 10,
                     user_id: str = "",
                     **model_kwargs: Any) -> dict:
            return engine.tool_use(prompt, tools, system=system,
                                   max_turns=max_turns, user_id=user_id,
                                   **model_kwargs)

        def generate(self, prompt: str, system: str = "",
                     user_id: str = "", **model_kwargs: Any) -> dict:
            return engine.generate(prompt, system=system, user_id=user_id,
                                   **model_kwargs)

        def context_window(self, cell_id: str = "",
                           agent_id: str = "") -> dict:
            cw = engine.context_window(cell_id=cell_id, agent_id=agent_id)
            return {"context_window": cw, "source": "llm"}

        def optimize_prompt(self, prompt: str,
                            system: str = "") -> tuple[str, str]:
            return _optimize_prompt(prompt, system)

        def provider_status(self) -> dict:
            return {"status": "ok", "provider": str(engine.provider_name())}

    register_port("llm", _LLMEngineAdapter())


# ── Module-level convenience ──

_engine: LLMEngine | None = None
_engine_lock = threading.Lock()


def get_engine(config: LLMConfig | None = None) -> LLMEngine:
    """Get or create the singleton LLMEngine instance."""
    global _engine
    if config is None:
        try:
            from l1.kernel.settings import get_settings
            s = get_settings()
            config = LLMConfig(
                provider=s.get("llm.provider", "mock"),
                model=s.get("llm.model", FALLBACK_MODEL),
                api_url=s.get("llm.api_url", FALLBACK_LLM_API_URL),
                api_key=s.get("llm.api_key", ""),
                max_tokens=s.get("llm.max_tokens", 2048),
                temperature=s.get("llm.temperature", 0.3),
                reasoning_effort=s.get("llm.reasoning_effort", DEFAULT_REASONING_EFFORT),
                thinking_budget=s.get("llm.thinking_budget", DEFAULT_THINKING_BUDGET),
            )
        except Exception:
            config = LLMConfig()
    if _engine is None or _engine.config != config:
        with _engine_lock:
            if _engine is None or _engine.config != config:
                _engine = LLMEngine(config)
                _register_llm_port(_engine)
    return _engine


def reset_engine() -> None:
    """Reset the singleton LLMEngine (for testing)."""
    global _engine
    _engine = None


def think(prompt: str, system: str = "", max_tokens: int = LLM_DEFAULT_MAX_TOKENS,
          user_id: str = "") -> dict:
    """Convenience: one-shot LLM inference."""
    return get_engine().generate(prompt, system, max_tokens, user_id=user_id)


def analyze(findings: list, context: str = "", user_id: str = "") -> dict:
    """Analyze findings (scout results, code review, etc.) with LLM."""
    from l1.kernel.prompts import get_prompt as _gp
    prompt = f"Context: {context}\n\nFindings:\n" + "\n".join(str(f) for f in findings)
    prompt += _gp("llm.analyze_suffix", "")
    return get_engine().generate(prompt, system=_gp("llm.analyze_system", "You are a code analysis expert."),
                                 max_tokens=LLM_ANALYZE_MAX_TOKENS, user_id=user_id)


def optimize_prompt(prompt: str, system: str = "") -> tuple[str, str]:
    """Optimize prompt structure for token efficiency and cache matching.
    
    Based on Copilot's Treatment B approach:
    - Structured [System]/[Task]/[Context] sections for cache prefix alignment
    - Minimized redundant whitespace
    - Clear section boundaries for cache_control breakpoint matching
    """
    sections = []
    if system:
        sections.append(f"[System]\n{system.strip()}")
    sections.append(f"[Task]\n{prompt.strip()}")
    optimized = "\n\n".join(sections)
    return optimized, system


# ── LLM lifecycle hooks (pre/post call monitoring) ──
#
# Allows internal modules to observe or modify every LLM call without
# modifying generate() internals.
#
# Usage:
#   from l4.llm.llm import on_llm_call
#
#   @on_llm_call("pre")
#   def log_prompt(prompt, system, **kwargs):
#       logger.info("LLM call: %s", prompt[:LOG_TRUNC_60])
#
#   @on_llm_call("post")
#   def log_result(result, **kwargs):
#       logger.info("LLM result tokens=%s", result.get("tokens", 0))

_LLM_HOOKS: dict[str, list] = {"pre": [], "post": []}


def on_llm_call(hook_type: str):
    """Decorator to register an LLM lifecycle hook.

    Args:
        hook_type: "pre" (before generate) or "post" (after generate)

    Pre-hooks receive: prompt, system, max_tokens, user_id, **kwargs
    Post-hooks receive: result (dict), **kwargs
    """
    def wrapper(fn):
        _LLM_HOOKS.setdefault(hook_type, []).append(fn)
        return fn
    return wrapper


# ── Auto-wire counter into post-call hook ──

@on_llm_call("post")
def _counter_hook(result, prompt="", system="", max_tokens=0, user_id="", **kwargs):
    try:
        from .services.counter import get_counter
        c = get_counter()
        inp = result.get("input_tokens", 0)
        out = result.get("output_tokens", 0)
        c.record_token(
            agent_id=user_id or "unknown",
            input_tokens=inp, output_tokens=out,
            cache_hit=result.get("cache_hit_tokens", 0),
            cache_miss=result.get("cache_miss_tokens", 0),
            model=result.get("model", ""),
        )
        # Also emit TOKEN_USAGE event for CentralCollector cross-Cell aggregation
        from l1.kernel import emit_signal
        provider = kwargs.get("provider", "")
        from l1.kernel.params.agent import EVENT_TOKEN_USAGE
        emit_signal(EVENT_TOKEN_USAGE, sender=user_id or "unknown", target="central_collector",
                    data={"agent_id": user_id or "unknown", "cell_id": kwargs.get("cell_id", "default"),
                          "input_tokens": inp, "output_tokens": out,
                          "provider": provider, "model": result.get("model", "")})
    except Exception as e:
        logger.warning("services/llm: %s", e)


# ── Auto-register built-in providers by scanning llm_providers module ──
try:
    import importlib as _il
    import inspect as _inspect
    _prov_mod = _il.import_module(".llm_providers", __package__)
    for _name, _cls in _inspect.getmembers(_prov_mod, _inspect.isclass):
        # Duck-type check: any class with .name (str) and .generate() is a provider
        if hasattr(_cls, "name") and isinstance(getattr(_cls, "name", None), str) and hasattr(_cls, "generate"):
            register_provider(_cls.name, _cls, override=True)
except Exception as e:
    logger.warning("services/llm: %s", e)
