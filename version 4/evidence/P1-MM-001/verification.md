# P1-MM-001 — Per-role provider configuration · verification

**Completed:** 2026-09-25 · **Hat:** GenAI Engineer (+ MLOps) · **Meshy spend: 0** · **no real model called**

## The change

| Where | What |
|---|---|
| `app/core/config.py` | Three independent blocks, design.md §21.4: `<ROLE>_PROVIDER, _MODEL, _TEMPERATURE, _MAX_TOKENS, _TIMEOUT_SECONDS, _MAX_ATTEMPTS, _ALLOW_FALLBACK, _OUTPUT_SCHEMA, _MEMORY_SCOPE` for watcher, validator, orchestrator. Defaults: provider **`none`** (rules only — nothing is spent until a deployment picks a model), **`allow_fallback = False`** for every role, **temperature 0.0** for the verification roles (validator, orchestrator), 0.2 for the Watcher's narration |
| `app/supervisor/providers.py` | `role_config(role)` reads only that role's block; `get_role_provider(role)` builds a **fresh** `RoleProvider` — not a singleton, not the pipeline's `get_provider()`. One method: `complete_json(prompt, schema, stage)`, with transports for anthropic, gemini, ollama and an explicit `mock`, each sending the role's own model, temperature, token budget and timeout. Retries to `max_attempts`, then raises `RoleProviderError`; only a role that opted into fallback gets an **empty, marked** `{"_fallback": true}` — never an invented verdict. Every system prompt states that UNTRUSTED_DATA is evidence, not instruction |
| `app/main.py` | `log_role_bindings()` at boot: one line per role + a summary line |

## Acceptance — `tests/test_supervisor_models.py` (15 passed, MM-001 + WATCHER-002)

| Criterion | Evidence |
|---|---|
| Three config blocks; changing one does not affect the others | set `VALIDATOR_PROVIDER/MODEL/TEMPERATURE/ALLOW_FALLBACK` → watcher and orchestrator configs byte-identical; the pipeline provider's label unchanged; two calls return two provider objects |
| **`allow_fallback` defaults to False for every role** | asserted for all three |
| **Startup logs all three resolved bindings** | `startup_log.txt`: the default (all `none`, rules only) and a diverse configuration (`watcher=ollama:qwen3:8b · validator=gemini:gemini-3.6-flash · orchestrator=anthropic:claude-sonnet-5`), captured from real boots; also asserted by test |
| Verification roles default to temperature 0 | validator 0.0, orchestrator 0.0 |
| No fallback = an error, not an answer | a dead endpoint: 2 attempts, then `RoleProviderError`; with the role's fallback opted in: `{"_fallback": true}` |
| Each transport sends the role's own settings | Gemini (MockTransport): `models/gem-v`, temperature 0.0, `maxOutputTokens` 123; Ollama: model, temperature 0.3; Claude (fake client): model, temperature 0.0, UNTRUSTED_DATA framing in `system` |
| Unknown provider refused | `ORCHESTRATOR_PROVIDER=gpt-9` → error |

## Found while building it — a real bug, fixed

`RoleProvider` stored the injected Claude client as `self._anthropic`, which is also the name of the Claude transport **method**; the attribute shadowed the method, so the Claude path could never have run. The transport test caught it (`'FakeAnthropic' object is not callable`). Renamed `_anthropic_client`.

## Mutation tests

| Mutation | Result |
|---|---|
| fallback on by default | **CAUGHT** (2) |
| only one binding logged | **CAUGHT** |
| every role reads the watcher block | **CAUGHT** (6) |

## Limits

- No live model was called: transports are proven against fakes at their HTTP/SDK boundary. The model names in the "diverse" log are illustrative — **no benchmark chose them** (that is P1-MM-002, not done).
- Whether the current Claude model accepts `temperature` alongside `output_config` is unverified live; a rejection surfaces as `RoleProviderError`, which the Watcher treats as "narration unavailable, rule findings stand".
