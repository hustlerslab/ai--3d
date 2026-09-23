# P0-AI-001 — Evidence: provider resolution under four configurations

**Captured:** 2026-09-21 · **Method:** real `app.intelligence.get_provider()` against real `Settings`, temp data dir, no network call (provider constructors do no I/O — verified at `anthropic_provider.py:39-48`).
**Keys:** the Anthropic key used in config C is the synthetic literal `sk-ant-synthetic-not-a-real-key`. No real credential appears in this file.

---

## A — explicit `gemini`

```
INFO  aether.intelligence: intelligence provider resolved: provider=gemini model=gemini:gemini-3.5-flash-lite mode=live INTELLIGENCE_PROVIDER=gemini fallback_to_mock=True
```

No warning. Explicit configuration is not scolded.

## B — `auto`, Gemini key only — **this was production**

```
INFO     aether.intelligence: intelligence provider resolved: provider=gemini model=gemini:gemini-3.5-flash-lite mode=live INTELLIGENCE_PROVIDER=auto fallback_to_mock=True
WARNING  aether.intelligence: INTELLIGENCE_PROVIDER is 'auto' (or unset): the reasoning model was chosen by which API keys are present, and resolved to gemini:gemini-3.5-flash-lite. Set INTELLIGENCE_PROVIDER explicitly to one of anthropic|gemini|ollama|mock so the production model cannot change just because a key was added.
```

## C — `auto` + `ANTHROPIC_API_KEY` added — **the risk, demonstrated**

```
INFO     aether.intelligence: intelligence provider resolved: provider=anthropic model=anthropic:claude-opus-5 mode=live INTELLIGENCE_PROVIDER=auto fallback_to_mock=True
WARNING  aether.intelligence: INTELLIGENCE_PROVIDER is 'auto' (or unset): ... resolved to anthropic:claude-opus-5. ...
WARNING  aether.intelligence: INTELLIGENCE_PROVIDER=auto found BOTH ANTHROPIC_API_KEY and GEMINI_API_KEY and preferred anthropic (claude-opus-5). Gemini (gemini-3.5-flash-lite) is configured but NOT in use. If that is not what you intended, set INTELLIGENCE_PROVIDER=gemini.
```

**Nothing changed but one environment variable, and the model reading customers' homes went from `gemini-3.5-flash-lite` to `claude-opus-5`.** Before this task that transition was completely silent.

## D — explicit `mock`

```
INFO  aether.intelligence: intelligence provider resolved: provider=mock model=mock mode=mock INTELLIGENCE_PROVIDER=mock fallback_to_mock=True
```

`mode=mock` is stated, so a green run can never be mistaken for a real one.

---

## Acceptance criteria

| Criterion | Met | Proof |
|---|---|---|
| Startup logs `provider=` and `model=` | ✅ | all four configs above; `main.py` lifespan also resolves at boot |
| `auto` emits a warning naming what it resolved to | ✅ | B and C — the warning interpolates `provider.label` |
| Adding `ANTHROPIC_API_KEY` without changing the setting produces a visible warning | ✅ | C — two warnings, one naming the unused Gemini key |
| Integration test under three configurations | ✅ | `tests/test_providers.py` — 4 tests, all passing |

## Change also applied to configuration

`.env` had **no** `INTELLIGENCE_PROVIDER` line at all, so production ran on `auto`. It is now pinned to `gemini` — the model that was already running — so the behaviour is unchanged and the accident is no longer possible. `.env.example` now recommends explicit selection and documents why.
