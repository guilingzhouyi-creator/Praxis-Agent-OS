# L4 — LLM / Reasoning System

How Praxis talks to models: providers, effort tiers, strategy packs, and
the model_spec cascade. The reasoning system is config-first — no model
name is hardcoded in agent code.

## Provider layer

| Provider | Module | Notes |
|----------|--------|-------|
| OpenAI / Anthropic / DeepSeek / Ollama / mock | `llm/llm_providers.py` | unified `LLMProvider` ABC; streaming + tool calls |
| HTTP pool | `llm/http_pool.py` | per-thread keep-alive `HTTPConnection` reuse (no fresh TLS handshake per call); `Retry-After` honored |
| Engine | `llm/llm.py` | `LLMEngine`: strategy application, effort normalization, capability probes, `generate`/`tool_use`/`context_window` |
| Port | `"llm"` | AgentLoop resolves the engine via `get_port("llm")` (duck-typed) |

## Effort tiers (provider-normalized)

Requested `reasoning_effort` is clamped per provider by
`EFFORT_TIERS_BY_PROVIDER` (params/api.py): a tier outside the provider's
set falls back to the highest supported at or below the request; empty set
= provider has no effort support (param dropped). `EFFORT_RANK` orders
none < low < medium < high < xhigh < max.

| Tier | Modern models (GPT-5.x / Claude Opus 5+ / DeepSeek V4) |
|------|--------------------------------------------------------|
| `xhigh` / `max` | adaptive server-side reasoning; `thinking_budget` only honored by legacy Anthropic/Gemini |
| `none` | default — no reasoning budget requested |

`think.max_reasoning` (default `"max"`) caps the ceiling admin-side;
`think.max_budget` caps budget tokens.

## Strategy packs

`config/praxis.yaml` `model_spec.strategies` — named presets
(fast / balanced / deep / xhigh / max) combining reasoning_effort,
thinking_budget, max_tokens, temperature:

```yaml
model_spec:
  strategies:
    fast:      { reasoning_effort: low,    thinking_budget: 0,     max_tokens: 2048, temperature: 0.3 }
    balanced:  { reasoning_effort: medium, thinking_budget: 2048,  max_tokens: 4096, temperature: 0.5 }
    deep:      { reasoning_effort: high,   thinking_budget: 8192,  max_tokens: 8192, temperature: 0.4 }
    xhigh:     { reasoning_effort: xhigh,  thinking_budget: 16384, max_tokens: 12288, temperature: 0.3 }
    max:       { reasoning_effort: max,    thinking_budget: 32768, max_tokens: 16384, temperature: 0.2 }
```

Applied via `ModelService.resolve_dict_with_strategy(spec_name, strategy)`.

## Model spec cascade

```
per-call overrides > model_spec.<executor> > llm global (praxis.yaml)
executors: scout / l3a / l3a_subagent / subagent / r4_agent
```

`ModelService.resolve(spec_name, ...)` merges the chain (deep-merge +
env interpolation + credential resolution); `_clamp_reasoning` enforces
`think.max_reasoning`/`think.max_budget` ceilings.

## Think registry (L3)

`scheduler/think_registry.py` — 3-layer thinking-config overrides
(Global / Cell / Agent): `inherit` / `auto_balance` / `manual`.

## API surface

`/api/v2/providers*` (list/register/remove/health/config),
`/api/v2/model-spec*` (view/update per executor + strategies) — see
`l4-bridge.md` routes context.
