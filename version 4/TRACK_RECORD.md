# Allure V4 — Execution Track Record

*Live ledger for `task.md`. Updated as tasks complete. **A task is DONE only with linked evidence.***

**Last updated:** 2026-09-23 · **Mode:** continuous execution · **Meshy spend: 0 / 500** (see `MESHY_CREDIT_LEDGER.md`)

---

## 1. Scoreboard

| Priority | Total | 🟢 DONE | 🟡 IN PROGRESS | 🟠 BLOCKED | ⬜ TODO |
|---|---:|---:|---:|---:|---:|
| **P0** | 19 | **19** | 0 | 0 | 0 |
| **P1** | 46 | **10** | 0 | 0 | 36 |
| **P2** | 6 | 0 | 0 | 0 | 6 |
| **P3** | 5 | 0 | 0 | 0 | 5 |
| **P4** | 1 | 0 | 0 | 0 | 1 |
| **TOTAL** | **77** | **29** | **0** | **0** | **48** |

**Critical path: 10 of 10 complete. ALL 19 P0 TASKS COMPLETE. Phase 2 gate (M2 — Identity Complete): all 6 criteria evidenced.**

*Plus **2 unplanned tasks** (P0-QA-004, P0-FRONTEND-003) found while executing. Neither is one of the 77, so neither is counted above; both are recorded in full below — one concerns real money, the other was the difference between a secured API and an unusable product.*

---

## 2. Completed — with evidence

### 🟢 P0-QA-001 — Repository and test baseline
**Hat:** QA Engineer · **Completed:** 2026-09-21

| Evidence | Value |
|---|---|
| Command | `./.venv/Scripts/python.exe -m pytest -q --tb=no` |
| Result | **970 passed · 9 skipped · 30 xfailed · 0 failed** in 183.30s |
| Reproduced | Yes — matches the documented figure exactly |
| Artifact | `docs/benchmarks/v4_baseline.json` (JSON-validated) |
| Git | `02ca264`, branch `ai-3d` |
| Versions | Python 3.14.4 · Node v24.15.0 · Blender 5.2.1 LTS (`9e2066aef7ef`) |

---

### 🟢 P0-QA-002 — Classify the 30 xfails
**Hat:** Spatial Engineer · **Completed:** 2026-09-21

**Finding — `task.md` was wrong.** It claimed the xfails were "unexplained." They are not. There are **5 decorators** (not 30 — the rest are `parametrize` expansions), and **every one already carries `strict=True` and a detailed `reason=`**. A naive grep missed them because the reason sits on the line *after* the decorator.

| Disposition | Count | Detail |
|---|---:|---|
| accepted-limitation | 3 | guard substring scan · unscanned text surfaces · Protocol provider not filtered |
| **deferred-bug** | **2** | JSON object → zero rooms silently accepted · module constants deleted not deprecated |

Recorded in `docs/benchmarks/v4_baseline.json → xfail_inventory`.

---

### 🟢 P0-RENDER-001 — Fix the silently-swallowed render setting ⭐ CRITICAL PATH
**Hat:** Blender / Rendering Engineer · **Completed:** 2026-09-21

**The defect:** `build_scene.py:38-42` set `look = "AgX - Medium Contrast"`, Blender rejected it, and `except TypeError: pass` discarded the failure. **Every render this project ever produced shipped with no contrast look applied.**

**Probed on the configured Blender 5.2.1** — the look enum is namespaced; `AgX - Medium Contrast` does not exist:
```
None · AgX - Punchy · AgX - Greyscale · AgX - Very High Contrast ·
AgX - High Contrast · AgX - Medium High Contrast · AgX - Base Contrast ·
AgX - Medium Low Contrast · AgX - Low Contrast · AgX - Very Low Contrast
```

**The fix:** new `apply_colour_management(scene)` — sets `VIEW_TRANSFORM = "AgX"` and `LOOK = "AgX - Medium High Contrast"` (nearest accepted value to the original intent), **asserts both stuck**, and raises with the accepted list on rejection. No swallowing.

| Test | Result |
|---|---|
| 1 — success path | ✅ `AgX` / `AgX - Medium High Contrast` applied |
| 2 — old invalid value | ✅ **raises** with actionable message + valid list |
| 3 — `reset_scene()` end to end | ✅ look applied, METRIC units, `film_transparent=False` |
| Regression | ✅ **970 passed**, 9 skipped, 30 xfailed |

**File:** `aether-backend/blender/scripts/build_scene.py` (+46 −5)

**Not yet proven:** that renders *look* better. Needs a before/after image pair — deferred to `P1-RENDER-002` so both render changes are compared together.

---

### 🟢 P0-FRONTEND-001 — Resolve the `/cinematic` route ⭐ RECLASSIFIED
**Hat:** Frontend Engineer · **Completed:** 2026-09-21 · **Verified by Playwright**

**Outcome: NOT A DEFECT. My earlier audit finding was wrong.**

| My claim | Verified reality |
|---|---|
| Calls the Aether backend and returns HTTP 404 | Calls a **separate engine on port 4000** via `NEXT_PUBLIC_WALKTHROUGH_API_URL` |
| Dead feature, backend missing | **Optional integration** with "RE Walkthrough Pro" — a different product |
| Broken page a user can land on | Renders a clear, documented "engine not running" state |

**What a user actually sees** (Playwright, `main` innerText):
> *The walkthrough engine is not running — This is the one part of Allure that needs a service behind it. Nothing else in the portal is affected. Expected at http://localhost:4000 — [Check again]*

The intent was documented all along: `src/app/cinematic/page.tsx:15` and `src/features/walkthrough/README.md` both state the route degrades gracefully when the engine is absent.

**Root cause of my error:** I tested the URL, saw a non-200, and never read the page's own docstring. This propagated as a P0 defect into six documents. **Correction pending across all of them** — see §5.

---

### 🟢 P0-FRONTEND-002 — Make the designer step honest
**Hat:** Product Engineer + Frontend Engineer · **Completed:** 2026-09-21

**Confirmed a real defect** on four independent proofs:

| Proof | Finding |
|---|---|
| Backend endpoint | **None** — grep of `app/api/*.py` for designer/connect returns nothing |
| Data source | `import { DESIGNERS } from "@/lib/mock/designers"` — **the path says `mock`** |
| State | `useState<string \| null>(null)` at line 241 — browser memory only |
| Network calls in block | **0** fetch/api/await |

The button set a variable and rendered **"Request sent."** Nothing was sent or stored; a reload erased it.

**Decision — Option B (label it a preview), not Option A (build it).** Option A needs a designers table, a connection endpoint, authorization to know *who* is connecting, delivery, and consented real profiles — all gated behind `P0-SEC-001/002` and therefore the blocked auth decision. Option B is honest today and doesn't fake a marketplace that does not exist. That the data already lived at `lib/mock/designers.ts` shows the author knew it was a placeholder; the **UI** had forgotten.

**Changes** — `aether-frontend/src/features/walkthrough-studio/components/walkthrough-studio.tsx`:
- Subtitle → "Designer matchmaking is in development. The profiles below are examples, not real designers."
- Added a dashed preview banner stating **"no request is sent to anyone"**
- `Connect` → **`Note interest`**; `Request sent` → **`Noted on this device`**
- Each card labelled **"Example profile"**; avatars de-emphasised
- `aria-label` states the local-only semantics

| Verification | Result |
|---|---|
| `Request sent` in UI | ✅ gone (survives only inside the explanatory comment, line 1288) |
| `connecting is free` | ✅ gone |
| Honest strings present | ✅ all 5 |
| Network calls still 0 | ✅ honest about what it does |
| `npx tsc --noEmit` | ✅ exit 0 |
| `next lint` | ✅ no warnings or errors |

**Live-UI limitation, stated honestly:** step 9 is `disabled` until a project completes (correct gating), so the rendered block could not be photographed in-browser. Verification is by source + typecheck + lint. Full visual confirmation belongs to the §54 golden-project run.

---

### 🟢 P0-AI-001 — Make provider selection explicit ⭐ CRITICAL PATH
**Hat:** GenAI Engineer · **Completed:** 2026-09-21

**The risk, demonstrated live rather than asserted.** `.env` had **no `INTELLIGENCE_PROVIDER` line at all**, so the resolver ran on `auto`, which landed on Gemini *only because* `ANTHROPIC_API_KEY` was absent. I set that one variable and captured the result:

| Config | Resolved model |
|---|---|
| `auto`, Gemini key only | `gemini:gemini-3.5-flash-lite` |
| `auto` + `ANTHROPIC_API_KEY` | **`anthropic:claude-opus-5`** |

One environment variable changed the model that reads customers' homes. **Before this task, nothing said so** — no log line, no warning.

**The fix**, three parts:

1. `provider.py` — new `_announce()`, called on every resolution path including the early `ollama` return. Logs `provider= model= mode= INTELLIGENCE_PROVIDER= fallback_to_mock=` at INFO; on `auto` raises a WARNING naming what it resolved to; when both keys exist, a second WARNING names the configured-but-unused one.
2. `main.py` — the provider is now resolved **in the lifespan at boot**, not lazily on the first job, so the line appears while somebody is watching the console. The "backend up" line carries `provider=`/`model=`/`mode=`.
3. `.env` — pinned to `INTELLIGENCE_PROVIDER=gemini`, the model already running, so behaviour is unchanged and the accident is impossible. `.env.example` now recommends explicit selection and says why.

| Acceptance criterion | Result |
|---|---|
| Startup logs `provider=` and `model=` | ✅ four configurations captured |
| `auto` warns, naming what it resolved to | ✅ interpolates `provider.label` |
| Adding `ANTHROPIC_API_KEY` is visibly warned | ✅ two warnings, one naming the unused Gemini key |
| Integration test, three configurations | ✅ 4 tests in `tests/test_providers.py`, all passing |

**Evidence:** `version 4/evidence/P0-AI-001/startup-logs.md`
**Regression:** ✅ **973 passed**, 10 skipped, 30 xfailed, 0 failed.

---

### 🟢 P0-QA-004 — The test suite was only *accidentally* offline ⭐ UNPLANNED, FOUND WHILE TESTING
**Hat:** QA Engineer · **Completed:** 2026-09-21

Found by a failing test of my own: a test asserting "no keys → mock provider" resolved to **live Gemini**. It was reading the developer's real `.env`.

**Root cause.** The key blanking lived in the `env` fixture, which is **not autouse**. Measured: **547 of 728 test functions never request it.** `Settings` reads `.env` (`config.py:16`), so every one of those 547 could construct a live provider — and `MESHY_API_KEY` was in the same unguarded set, which is real money.

Nothing was observed to have spent credits. **That was luck, not design.**

**Fix:** new autouse `_no_real_keys` fixture in `tests/conftest.py` blanking all three keys for *every* test and clearing the settings cache. A test that genuinely wants a key sets it in its own body, which runs after the fixture and still wins — so reaching a real provider becomes deliberate and visible, which is the point of the MOCK / REAL-PROVIDER split.

| Check | Result |
|---|---|
| Overhead | **3.78 ms per test** (measured: 728 × cache_clear + `Settings()` = 2.75 s) |
| Regression | ✅ 973 passed, 0 failed |
| Baseline corrected | `v4_baseline.json → backend_tests.class_note` |

### 🟢 P0-AI-002 — Regression-test the no-silent-mock rule
**Hat:** GenAI Engineer + QA Engineer · **Completed:** 2026-09-21 · **No behaviour change**

The rule: *a deterministic estimate must never be presented as a reading of a customer's photograph.* `ResilientProvider` already enforced it correctly and had almost no test behind it.

**Coverage that existed:** `test_intelligence.py:170-183` — `analyze_input` only, via a Gemini HTTP 500.
**Coverage that did not:** the other two Protocol stages, all five optional capabilities, and the distinction the whole rule rests on — *selected* mock versus *failed* primary.

**New:** `tests/test_no_silent_mock.py`, **12 tests**.

| What it pins | Why it matters |
|---|---|
| Selected mock carries **no** fallback warning | A false alarm on every project teaches people to ignore the warning that matters |
| A failed primary names **provider and stage**, all 3 stages | "explodey failed during plan_objects" distinguishes a timeout from a bad prompt |
| The warning is **`warnings[0]`** | Buried under six advisory lines, it is not a notice |
| `allow_fallback=False` **raises** | The setting production should run |
| The estimate is still usable | Honesty must not cost usability |
| Failed render read → `_error`, **not** an empty room | "the model timed out" ≠ "this room is empty" — collapsing them once hid a real outage |
| Failed reference classification → `_error` | An unreadable photograph stays visible |
| Failed crop check → `{}` = **unreadable, not approved** | Otherwise an unverified element goes straight to spend |
| Failed prompt compose → `""` = use the template | A mock-written prompt *is* the silent degradation |
| Missing capability ≠ empty answer | "cannot read" must differ from "read nothing" |

**Teeth verified by mutation, not by passing.** Twelve green tests prove nothing on their own, so I broke the source twice and confirmed they catch it:

| Mutation | Tests failed |
|---|---:|
| `_run` substitutes the mock silently (drop the provider relabel + warning) | **4** |
| `read_scene_elements` swallows the failure as `{}` | **1** |

Source restored both times; `git diff --stat` confirms `provider.py` carries only the intended `+41` from P0-AI-001.

**Result:** 12 passed · combined with `test_providers.py`, **21 passed**.

---

### 🟢 P0-ARCH-001 — Inventory the production path ⭐ CRITICAL PATH
**Hat:** Technical Architect · **Completed:** 2026-09-21

**Deliverable:** `docs/production/v4_inventory.md` (17 KB) — **generated by introspecting the running application**, not written by hand. Routers, `_REGISTRY`, `Settings.model_fields` and `CHECKPOINTS` are read directly, so the document cannot drift from the code without the generator saying so.

**Cross-check the task demanded** — grep against introspection:

| Quantity | grep | introspection | |
|---|---:|---:|:--:|
| Routes (`projects_routes.py` 35 + `routes.py` 28) | **63** | **63** | ✅ |
| `@register(` | 13 | 13 | ✅ |
| `Settings` fields | — | 43 | ✅ |
| `CHECKPOINTS` | — | 17 | ✅ |

`app.openapi()` independently reports **64** served paths — the 63 router routes plus `GET /` on the app.

**Three findings that changed the answer:**

1. **13 job types, not 11.** Eleven *modules* are imported; `tour.py` registers `preview` **and** `walkthrough`, `scene_plan.py` registers `scene_plan` **and** `resolve_assets`. Counting imports is not counting registrations — and both `task.md` and `AUDIT_CODEBASE.md` carry the wrong number.
2. **`POST /api/projects/{project_id}/jobs` is a wildcard dispatcher.** `projects_routes.py:1028` hands `body.type` and `body.params` straight to the runner. **One unauthenticated route reaches all 13 job types with caller-controlled parameters**, including both Meshy handlers. `generate_assets` has **no dedicated route** — this is its only entry point. A literal-string scan cannot see it, and my first pass missed it entirely.
3. **Zero authenticated routes.** My first scan said one; it had matched `require_model: bool`, a catalog *filter*. The correct test is `Depends(`/`Security(` in the signature.

**An over-count I caught before publishing:** the first spend classification scanned each handler's *module* and flagged four job types. Only **two** actually submit to Meshy. `scene_plan` plans generation without performing it — its own comment: *"approval gates SPENDING, which is the generate_elements job."* Over-counting spend is as misleading as under-counting it.

**Evidence:** `version 4/evidence/P0-ARCH-001/` — `verification.md` + the regenerable `generate_inventory.py`.

---

### 🟢 P0-SEC-001 — Authentication and the principal dependency ⭐ CRITICAL PATH
**Hat:** Security Engineer · **Completed:** 2026-09-21

**Allure can now tell one person from another. It still lets everyone in — deliberately.**

**The blocked decision did not block this.** `AUTH_PLAN.md` answers it in its own words: *"Steps 1–5 deliver most of the security benefit and are independent of the database decision. Only 6 and 7 depend on it — so the A/B/C decision does not block starting."* So `users` carries **both** `password_hash` (option B) and `external_id` (options A/C), either nullable. Shipping one column would have made the owner's decision inside a migration.

**Shipped:** `app/auth/` (`service.py`, `deps.py`, `routes.py`, `__init__.py`), schema **v2 → v3** (`users`, `sessions`, `idx_sessions_user`), 6 new routes. Served paths **64 → 70**.

| Decision | Why |
|---|---|
| **stdlib `hashlib.scrypt`** | Memory-hard, in the stdlib. A dependency on a security path is a supply chain to own. Cost parameters live *inside* the hash, so raising them later is a per-user upgrade at next login. |
| **Opaque tokens, not JWT** | The JWT ADR `AUTH_PLAN.md` cites belongs to a *sibling codebase*. A JWT cannot be revoked before it expires; a stolen session for someone's home photographs must be killable **now**. `logout-everywhere` proves it. |
| Only the SHA-256 is stored | A database leak must not hand over live sessions. |
| One error for wrong-password and unknown-account | Anything else is a free account-enumeration oracle. |
| `role` on register is **refused** | Caller-controlled input. Honouring it would make P0-SEC-002 decorative on day one. |
| `secure` **not** set on the cookie | Plain HTTP on localhost — a secure cookie would never be stored, producing a login that silently does nothing. Recorded for P0-INFRA-001 rather than left to memory. |

| Acceptance criterion | Result |
|---|---|
| Register and sign in | ✅ |
| Principal for a valid session, **401 otherwise** | ✅ absent, malformed, unknown, revoked, expired, disabled — all 401, all one error |
| **Existing routes still work** | ✅ `test_the_existing_api_is_still_completely_open` |
| Migration runs twice safely, additive only | ✅ measured: two opens, version 3 both times, 8 original tables untouched |

**Teeth verified by mutation, not by passing.** Two real defects introduced: honouring the caller's `role` (privilege escalation), and storing the token instead of its hash. Combined: **9 failed, 17 passed**, including both targeted tests. Restored → 26 pass.

| Suite | Result |
|---|---|
| `tests/test_auth_identity.py` | **26 passed** |
| **Full backend** | **1011 passed · 10 skipped · 30 xfailed · 0 failed** (289.83 s) |

Accounting: 970 baseline + 4 + 12 + 26 = 1012, minus one Ollama test now skipping because **Ollama is not running**. Environment drift, not a regression — verified independently with `curl`.

**One pre-existing test corrected, and it is not a weakening.** `test_the_vertical_change_added_a_column_and_no_new_table` asserted `SCHEMA_VERSION == 2` / `MIGRATIONS == [2]` — i.e. *"no future feature may ever add a migration"*, broader than its own docstring and a blocker on all schema work. The substantive eight-table `SCHEMA` assertion is **kept byte-identical**; three were **added** (the vertical step is still at v2, `SCHEMA_VERSION >= 2`, the ladder has no gaps). All 5 `strict=True` xfails in that file still xfail — none flipped to xpass.

**Evidence:** `version 4/evidence/P0-SEC-001/verification.md`

---

### 🟢 P0-SEC-002 — Authorization at one choke point, deny by default ⭐ CRITICAL PATH
**Hat:** Security Engineer · **Completed:** 2026-09-21 · **Playwright-verified**

**A person's home photographs and designs are now visible only to them.**

**One router-level dependency**, attached in `main.py` on both routers — not 63 per-route decorators. A per-route check is a per-route opportunity to forget, and the forgotten one is the one that matters. Schema **v3 → v4** adds `projects.owner_id` (nullable) and `project_members`.

Measured by walking the **live route table**: `probed=62 · allow-listed=2 · gated-401=60 · **unguarded=0**`. A test fails on any route that answers an anonymous request without being on the justified allow-list — so deny-by-default is a property of the system, not of the cases someone remembered.

| Acceptance criterion | Result |
|---|---|
| Unauthenticated → **401** | ✅ |
| Another user's project → **403** | ✅ incl. 7 mutating routes, `POST /jobs` among them |
| Owner's own → **200** | ✅ |
| **Share link still anonymous** | ✅ `GET /{id}/tour` → 404 `TOUR_NOT_READY`, **not** 401 |
| Matrix covers every route × role | ✅ 21 tests + the route-table walk |
| Existing projects backfilled | ✅ first-run bootstrap, measured adopting 3 |

**`owner_id` is nullable with no default, deliberately.** There was no user to point existing rows at — the database predates `users` by three schema versions, and a `NOT NULL DEFAULT` would have to *invent* an owner. NULL means unclaimed; only an admin may read an unclaimed project. So the **first account on an instance becomes admin and adopts unowned work**. Its cost is stated, not hidden: on a reachable host, whoever registers first wins that race, so the first account must be made before the host is exposed. It fires only when `users` has exactly one row.

**The blast radius, handled honestly.** Enforcement broke **152 existing tests** — every one an existing suite calling a now-gated route anonymously. No assertion was weakened and the gate was not loosened: a shared `sign_in_admin()` in `conftest.py` signs each product-behaviour suite in, as admin, because that visibility matches the pre-auth behaviour they were written against. Two tests in `test_auth_identity.py` were **inverted on purpose and say so in place** — they asserted the API was still open, which was P0-SEC-001's explicit contract and is exactly what this task ends.

**Teeth by mutation:** treating authenticated as authorized (classic IDOR) → **11 failures**; adding `/api/` to the allow-list → **13 failures**. Restored, 21 pass.

| Suite | Result |
|---|---|
| `test_authz_matrix.py` | **21 passed** |
| **Full backend** | **1032 passed · 10 skipped · 30 xfailed · 0 failed** |

**Evidence:** `version 4/evidence/P0-SEC-002/` — verification + 4 Playwright snapshots.

**A side effect of my own testing, and its reversal.** Both probes registered against the **real dev database**, so bootstrap handed the operator's 3 existing projects to a throwaway account. Removed, and `owner_id` returned to NULL on all three — the exact pre-probe state (`users: []`, `sessions: 0`). The operator's own first registration will bootstrap and adopt them, as a real first run does.

---

### 🟢 P0-FRONTEND-003 — Sign-in, or the product is unusable ⭐ UNPLANNED, AND BLOCKING
**Hat:** Frontend Engineer + Security Engineer · **Completed:** 2026-09-21 · **Playwright-verified**

**A gap in `task.md`, not in the code.** All 77 tasks specify backend authentication and authorization. **None adds sign-in to the frontend.** Shipping P0-SEC-002 alone leaves a correctly-secured API behind a UI that sends no credentials — every call 401s and the studio reports a network error it cannot explain. Verified: `grep` for `Authorization`/`credentials` across all four frontend API clients returned **nothing**.

Marking P0-SEC-002 done without this would have satisfied its acceptance criteria and broken the product.

**Shipped:**

| Change | Detail |
|---|---|
| `features/auth/api/auth-api.ts` | register / sign in / session / sign out. **No token is stored by script** — the session is the httpOnly cookie |
| `features/auth/components/auth-gate.tsx` | three states: *checking* (calm text, never a flash of the form — that reads as being logged out), *signed out* (the form), *signed in* (studio + sign out) |
| `app/page.tsx` | studio wrapped in `<AuthGate>` |
| 4 API clients | `credentials: "include"`; XHR upload needed `withCredentials` separately |
| `main.py` CORS | `allow_credentials=True` with **explicit** methods/headers — the spec forbids wildcards once credentials are allowed, and `cors_origins` is a parsed list that is never `*` |

The form shows the **server's own error text**. "Email or password is incorrect" is deliberately vague so it cannot be used to discover which accounts exist; paraphrasing in the UI would either leak more or say less.

| Verification | Result |
|---|---|
| `npx tsc --noEmit` | ✅ exit 0 |
| `next lint` | ✅ no warnings or errors |
| CORS preflight, real origin | ✅ specific origin, `allow-credentials: true`, no wildcards |
| **Playwright, full round trip** | ✅ form → create account → **"Signed in as … · admin"** → studio with **"3 projects on this engine"** → sign out → form |
| Browser network | ✅ `/auth/session` `/auth/register` `/projects` `/credits` all **200** |
| **Console errors** | ✅ **0** |

---

### 🟢 P0-SEC-003 — Spend protection on paid generation ⭐ CRITICAL PATH
**Hat:** Security Engineer · **Completed:** 2026-09-21 · **Meshy spend: 0 credits**

**The limit that already existed was not one.** `meshy_max_per_project: 20` caps how many pieces **one job** attempts, is held nowhere, and resets with every new job — ten jobs cost twenty times what it implies.

Spend is now a **table**. `spend_records`, one row per confirmed charge, written the moment the provider confirms rather than at the end of a batch, because a crash in between would lose money genuinely spent. Schema **v4 → v5**, plus `jobs.created_by`.

| New setting | Default | Meaning |
|---|---:|---|
| `meshy_max_credits_per_project` | **600** | 20 pieces × 30 — the ceiling the old per-job limit *implied*, now enforced for the project's life |
| `meshy_max_credits_per_user` | **3000** | 100 pieces: generous for one person, ruinous for none |

`0` means uncapped — an explicit deployment choice, never the default; a test asserts both shipped defaults exceed zero.

| Acceptance criterion | Result |
|---|---|
| Unauthenticated → **401, zero spend** | ✅ named route **and** the wildcard `POST /jobs`, then the ledger is asserted empty |
| Cap reached → halts, **project preserved**, review raised | ✅ emitted as a **warning**; plan and existing assets untouched |
| **Restart does not reset accumulated spend** | ✅ the restart is *performed*, not simulated |

**Measured is never mixed with estimated.** `credits` is Meshy's own reported figure. An unmeasurable charge is marked `is_estimate=1`, totals report the two apart, and `is_exact` turns False — an estimated total that reads as measured is how a budget becomes fiction. Estimates still count against the cap, so they cannot be used to exceed it.

**Partial allowance, not all-or-nothing.** 3 of 10 affordable → generate 3, flag 7, and tell a human exactly what is waiting and why.

**`created_by` is a column, not a `params` key** — `POST /jobs` lets the caller write `params` wholesale, so a user id there would be forgeable. A test posts `params.created_by = "usr_somebody_else"` and asserts the stored value is the authenticated user.

**A wrong turn, and what caught it.** The actor was first recorded in a `ContextVar` set inside the `authorize` **dependency**. FastAPI runs a sync dependency and a sync endpoint in **two separate threadpool calls with separate copied contexts**, so the value never arrived and jobs got `created_by=""` — silently, in every way except one failing test. Moved to middleware, which runs in the parent context both copies inherit; it now also resolves the session once per request instead of twice.

**Teeth by mutation:** caching totals in memory (the exact thing the task forbids) → **9 failures**, *including the restart test*; a cap that never holds anything back → **6 failures**. Mutation A is the one that matters: only the restart test separates it from the correct implementation.

| Suite | Result |
|---|---|
| `test_spend_protection.py` | **16 passed** |
| **Full backend** | **1048 passed · 10 skipped · 30 xfailed · 0 failed** |

**A pre-existing test caught my prose, correctly.** The compliance-vocabulary scan failed because a CORS comment used *"load-bearing"*, matching its `load[ _-]?bearing` guard against building-code logic. The test was right and the comment was wrong — reworded. The scan was not weakened.

**Not yet done:** the **idempotency key** (P1-ASSET-002), the fourth of the deliverable's four gates. Human approval, authentication and the cap are in place; a retried request can still spend twice.

**Evidence:** `version 4/evidence/P0-SEC-003/verification.md`

---

### 🟢 P0-SEC-004 — Share links as capability tokens ⭐ CRITICAL PATH
**Hat:** Security Engineer + Frontend Engineer · **Completed:** 2026-09-21 · **Playwright-verified**

**The project id used to *be* the capability.** Anyone who saw an id — in a URL, a log, a support email — could read that project's tour, and the owner could neither rotate it nor revoke access. The id still identifies the project; it no longer authorises anything.

Schema **v5 → v6** adds `capability_tokens`. Three new routes: mint, list, revoke.

| Acceptance criterion | Tests | Live server |
|---|---|---|
| Opens the tour with **no account** | ✅ | **200** with `?k=`, no cookie |
| Grants **nothing** beyond the tour | ✅ 10 routes + spend + minting, all 401 | — |
| Revoking breaks the link | ✅ 4 tests | revoked → **401** |
| **Guessing a project id grants nothing** | ✅ | id alone → **401** |

| Decision | Why |
|---|---|
| A **separate table**, not a session with flags | A session says who you are and unlocks everything you may do; a capability says nothing about you and unlocks one thing on one project. Forwarding a link must not hand over an account. |
| Only the **SHA-256** is stored | A leak must not hand over working links. The token is shown once — a link the server can reprint is one a compromise can reprint. |
| Project + scope are **in the query**, not checked after | No branch exists where the wrong project is returned and then rejected by a caller who forgot to check. Mutation A proves it. |
| Token in a **query parameter** | The point is that it can be pasted into a message. The cost — logs, history, `Referer` — is written into the code, and is *why* the token is scoped and revocable in one call. |
| Expiry **offered, not imposed** | A link that dies while a client is still looking at the design is a support call. |
| Revoked links **stay listed** | "It stopped working on the 3rd" is what people ask; a list that forgets cannot answer. |

**Teeth by mutation:** dropping `project_id` from the token lookup → caught; ignoring `revoked_at` → **2 failures**.

| Suite | Result |
|---|---|
| `test_share_links.py` | **30 passed** |
| **Full backend** | **1078 passed · 10 skipped · 30 xfailed · 0 failed** |
| `tsc` / `next lint` | clean / no warnings |

**Browser:** `/w/{id}?k=<token>` with no account renders the full tour — "test 1", palette, *1 rooms · 2 viewpoints*, floor plan, panorama controls, **0 console errors**. Without the token it refuses.

**A wording flaw I found in the browser, not in review.** The refusal first read *"This walkthrough isn't ready yet"* — which is what a 404 means, and a lie for a revoked link: the holder would have waited for a render that was never coming. A 401 now says *"This link doesn't work — ask whoever shared it with you for a new one."*

**One superseded test inverted, and it says so in place.** `test_the_share_link_is_still_anonymous` asserted the behaviour P0-SEC-002 deliberately preserved and this task deliberately ends. It now asserts the id alone is refused, and that a signed-in owner still reaches the handler.

**What this does NOT yet do:** `/files/*` is still completely open. A share link now guards `tour.json`, but the panoramas it references are served by `GET /files/projects/{id}/{path}` with a path-traversal guard and **no authorization at all**. That is P0-SEC-005 — next.

**Evidence:** `version 4/evidence/P0-SEC-004/` — verification + 3 Playwright snapshots.

**Side effect reversed, again.** The probes registered against the real dev database and minted links on a real project. All removed: 3 projects `owner: None`, `users: []`, `sessions: 0`, `capability_tokens: 0`, `spend_records: 0`.

---

### 🟢 P0-SEC-005 — Authorize file access ⭐ CRITICAL PATH
**Hat:** Security Engineer · **Completed:** 2026-09-21 · **Playwright-verified**

**The largest single hole in `AUTH_PLAN.md`, closed.** Scenes are JSON and images **on disk**, not rows, so no amount of database authorization reached them. `/files/projects/{id}/{path}` had a traversal guard and no authorization; the other three were bare `StaticFiles` **mounts** — and a mount is not a route, so the P0-SEC-002 gate never saw them. All four are ordinary routes now.

| Acceptance criterion | Tests | Live |
|---|---|---|
| Another user's render not retrievable | ✅ 403 / 401 | pano **401**, brief **401** |
| Share holder gets only the tour assets | ✅ carve-out is `outputs/web/` | pano **200**, brief **401**, blend **401** |
| Traversal still fails | ✅ 36 encoded probes | `../allure.db` → **404** |
| **Viewer + share page still load assets** | ✅ | **35 requests, all 200** |

**The boundary:** a tour token reaches the tour package and *exactly what it points at* — `outputs/web/**`, the shared library and its read-only catalog API, and the one scene the tour names. Live proof both ways: `/api/materials` 200, `/api/catalog` 200, its own scene 200; `/api/projects` 401, `/api/credits` 401, `/analysis` 401.

**Three defects found by testing, not review:**

1. **P0-SEC-002 had silently broken the share page's "Explore in 3D" tab** — it calls `/api/scenes/*`, which that task gated. Nobody would have seen it until a client opened a link.
2. **My first browser check was about to be a false positive.** Playwright showed the panoramas as 200; the **server log showed zero matching requests** — they came from disk cache populated while `/files/` was still anonymous. `fileUrl()` never appended the token, so a *fresh* visitor would have seen an empty tour. Fixed with `features/tour/share-token.ts` and re-verified against a new token with the server log as the source of truth.
3. **`material_file` raised `ImportError` → 500 in the browser.** My shared-library traversal test had passed **without ever reaching the handler**: httpx and Starlette normalise `../` out before sending, so the route never matched. A refusal proves nothing until the code under test has run. The suite now seeds a real file, asserts **200** (the handler runs), then attacks with percent-encoded traversal.

**Teeth by mutation:** carve-out widened to the whole project directory → **2 failures**; `/files/` back on the anonymous list → **10 failures**.

| Suite | Result |
|---|---|
| `test_file_authorization.py` | **31 passed** |
| **Full backend** | **1109 passed · 10 skipped · 30 xfailed · 0 failed** |

**Browser:** the Explore-in-3D tab, **anonymous with a share link** — 6 meshes, 12 textures, scene, spawn, catalog. **35 requests, all 200, 0 console errors.**

**Evidence:** `version 4/evidence/P0-SEC-005/` — verification + 5 snapshots.

---

### 🟢 P0-SEC-006 — Rate limiting ⭐ CRITICAL PATH
**Hat:** Security Engineer · **Completed:** 2026-09-21

Four buckets, sliding window, **no new dependency** (stdlib `deque` + `time.monotonic`).

| Bucket | Default | Keyed on | Covers |
|---|---:|---|---|
| `auth` | 10 / 60 s | **client address** | `/api/auth/*` — where password guessing lives |
| `spend` | 5 / 60 s | principal | `elements/generate`, `assets/resolve`, `POST /jobs` |
| `write` | 60 / 60 s | principal | every other mutating route |
| `read` | 300 / 60 s | principal | reads — deliberately generous |

`POST /jobs` is priced as **spending**: P0-ARCH-001 established it is the wildcard dispatcher reaching both Meshy handlers. `auth` keys on the **address** because a login has no principal — and one that did would let an attacker reset their own limit by signing out.

**The load test:** `WRITE=5`, nine creates → `[200×5, 429×4]` with `Retry-After` and `retryable: true`. `AUTH=4`, eight wrong passwords → **four 401s then four 429s**. With a limit of 2 and six creates, **exactly 2 projects exist** — a 429 that still did the work is not a limit.

**Normal use is asserted, not assumed.** Two tests exist so the limits cannot quietly become too tight: a realistic studio session (page loads + 20 job polls) and a share page loading one tour (41 requests). **Neither hits a 429.** If either ever fails, read the test rather than raising every number until it passes.

**Teeth by mutation:** one shared allowance for spend and write → **3 failures**; `auth` keyed on principal → **1 failure**.

| Suite | Result |
|---|---|
| `test_rate_limiting.py` | **24 passed** |
| **Full backend** | **1133 passed · 10 skipped · 30 xfailed · 0 failed** |

**Stated, not hidden:** it is **in-process**. A second instance would need a shared store — and a limiter giving every instance its own allowance would be *worse* than none, because it reads as protection. Recorded for P0-INFRA-001.

**One test bug of mine, corrected:** the "never reaches the handler" test counted the whole store and saw 3, because the app seeds `proj_seed`. The limiter was right (4 refusals logged, 2 created); I fixed the test's arithmetic rather than the product.

**Evidence:** `version 4/evidence/P0-SEC-006/verification.md`

---

### 🟢 P0-INFRA-001 — Container image and CI
**Hat:** DevOps Engineer · **Completed:** 2026-09-21 · **Image built and booted for real**

**Built, not asserted.** Docker Desktop was not running; I started it and ran the build rather than claiming the file was correct.

```
docker build ...                 DONE 20.3s
image: 71,386,224 bytes, 11 layers, user: allure (non-root)
/api/health -> 200 after 5s
```

| Probe | Result |
|---|---|
| `GET /api/health` anonymous | **200** — a probe must work without credentials |
| `GET /api/projects` anonymous | **401** — P0-SEC-002 is in force *inside the image* |
| `GET /files/assets-web/x.glb` anonymous | **401** — P0-SEC-005 likewise |

The last two matter more than the first: a container that boots but shipped without its gate is worse than one that does not boot, because it looks fine. The CI `image` job asserts that 401 as a **build-blocking step**.

**No secret in the image:** `/app` holds `app blender data pytest.ini requirements.txt` and no `.env`. `.dockerignore` keeps `.env`, `data/`, `*.db`, `.venv` and `node_modules` out of the **build context** — an image layer is permanent, and a later `RUN rm` does not remove a file from the layer that added it.

**The CI spend guard, tested both ways:** keys blank → proceeds; `GEMINI_API_KEY` set → **refuses, exit 1**. The check is on the *value*, not on whether the variable is defined.

**Three deliberate omissions:** Blender (~1 GB — every bug-fix deploy would re-ship an unchanged renderer; `BLENDER_PATH` empty is a supported state), the frontend (a CSS change should not wait on a Python test run), and Postgres/Redis in compose (they do not exist yet; `AUTH_PLAN.md` 6–7 are deferred).

**`docker-compose.yml` carries the deployment step in the file, not in memory:** create the first account **before** the port is reachable, because P0-SEC-002 makes the first account an administrator. It also pins `INTELLIGENCE_PROVIDER` (never `auto`), ships spend caps on, and records that the rate limiter is in-process and therefore correct for **one** replica.

**Not verified, and stated:** the workflow has **not run on GitHub**. It parses (3 jobs) and every command in it was run locally, but "a CI run on a pull request" needs a push to a remote — the owner's call, not mine.

**Evidence:** `version 4/evidence/P0-INFRA-001/verification.md`

---

### 🟢 P0-OBSERVABILITY-001 — Structured logging with correlation ids
**Hat:** Backend Engineer · **Completed:** 2026-09-21

`logging.basicConfig(level=INFO)` was the **entire** logging configuration. Now: one JSON object per line, every line carrying `correlation_id` / `project_id` / `job_id` / `stage`. Schema **v6 → v7**.

**Real capture** (`evidence/.../sample-log.jsonl`), a register → create → enqueue cycle:

```
8 lines, 0 malformed
{"ts":"2026-09-21T16:53:06Z","logger":"aether.jobs","message":"job.start",
 "correlation_id":"cid_7f46371a902b","project_id":"proj_f26976fd4f","job_id":"job_fa189ec896"}
brief in the log? False    password? False    email? False
```

**The design decision took three attempts, and the first two were wrong:**

| Attempt | Why it fails |
|---|---|
| In the **formatter** | Runs when a handler *writes* — later, on another thread, for anything buffered. **The line still has ids, and they name the wrong customer.** |
| Filter on the **root logger** | `Logger.filter()` applies to records logged on *that* logger; child records reach root's handlers without passing its filters. Stamps nothing, silently. |
| **Record factory** ✅ | Runs once per record, whatever logger, whatever handler, at creation. Ids become real attributes, readable by caplog and anything else. |

A test pins it: a record made inside a `bind()` and **formatted outside it** still carries the right ids.

**Teeth by mutation:** format-time resolution → **1 failure** (the only test that can catch it); redaction removed → **8 failures**.

| Suite | Result |
|---|---|
| `test_structured_logging.py` | **25 passed** |
| **Full backend** | **1158 passed · 10 skipped · 30 xfailed · 0 failed** |

**Two corrections to my own work:** I bound `project_id` in the request middleware from `request.path_params`, which is always empty there — middleware runs before routing — so it silently bound nothing. And I left `... or True` in a test: an assertion that could not fail. Replacing it with two real ones is what exposed the first mistake.

**One pre-existing test updated, not weakened:** it matched substrings of a formatted message; those ids are structured fields now, so it asserts the fields and the rendered JSON — same claims, real mechanism, plus `correlation_id`.

**Evidence:** `version 4/evidence/P0-OBSERVABILITY-001/` — verification + sample-log.jsonl

---

### 🟢 P0-INFRA-002 — Define and test the `data/` backup strategy
**Hat:** DevOps Engineer · **Completed:** 2026-09-21 · **Restore performed on the real 1.5 GB directory**

**The `[UNKNOWN]` resolved to "none".** There was no backup of any kind of 1.5 GB holding **590 MB of paid Meshy meshes**, 828 MB of customer photographs and renders, and the database.

**The trap this script exists for.** The database runs in WAL mode; the write-ahead log was **1.9 MB against a 1.0 MB database**, so most recent commits were NOT in `allure.db`. A `cp allure.db` backup opens cleanly, passes a smoke test, and is **missing every recent transaction**. Copying `-wal` alongside is no fix — the pair is consistent only if nothing writes between the two copies. `scripts/backup.py` uses SQLite's **online backup API**.

**Measured on the live directory:** backup **8.2 s**, restore **8.7 s**, 1.5 GB.

**The restore test, actually performed** — restored into a clean directory, then the application booted against it:

```
GET /api/projects                    -> 3 projects
GET /api/projects/proj_a25a006c88    -> 200  name: test 1  stage: PREVIEW_RENDERING  inputs: 4
GET /files/.../panos/preview/n01.jpg -> 200, 160,216 bytes
restored: 82 jobs, 114 outputs, 1,123 events
PAID MESHES: 69 .glb files, 396,443,592 bytes
```

The meshes are the point. A backup that restores the database but not `assets/` looks successful and costs the price of regenerating every purchased model.

| Acceptance criterion | Result |
|---|---|
| A restore reproduces a working project **including its meshes** | ✅ 69 meshes, 396 MB, project opened through the API |
| Frequency and retention stated | ✅ daily + pre-deploy/pre-migration; 7/4/6; off-device; quarterly restore test |
| **Tested, not merely written** | ✅ real 1.5 GB round trip + **12 automated tests** |

**A bug in my own code, found by a test:** `verify()` **crashed** on a corrupt database instead of reporting it — useless exactly when corruption exists. It now reports unreadable databases as findings and runs `PRAGMA integrity_check`.

**Safety behaviours, each with a reason:** restore refuses a non-empty target without `--force`; refuses a snapshot that fails verification; removes stale `-wal`/`-shm` (a WAL from another database beside a restored `.db` is corruption waiting to be opened); backup integrity-checks at write time.

| Suite | Result |
|---|---|
| `test_backup_restore.py` | **12 passed** |
| **Full backend** | **1170 passed · 10 skipped · 30 xfailed · 0 failed** |

**Stated, not hidden:** no off-site copy and no scheduler are installed — both belong with a deployment target that has not been chosen. A backup that dies with its container is not a backup.

**Evidence:** `docs/production/backup.md` (the procedure) + `scripts/backup.py`

---

### 🟢 P0-SEC-000 — Record the authentication decision ✅ DECIDED BY THE OWNER
**Completed:** 2026-09-21 · **Was the only task blocked on a person rather than on code**

**The answer is none of A, B or C.** Quoted, because a decision record that paraphrases is one nobody trusts:

> *"right now we are not including the auth system because this code base is the part of other code base and other codebase have the proper auth part"*
> *"right now not linked i will link it further after this done"*

**Option D — identity is delegated to the parent `CODEBASE` project.** Allure does not own accounts, passwords, sessions or password reset. It removes the premise of the question rather than compromising between the three options — and it points the same way `AUTH_PLAN.md`'s own recommendation did, only further: the best version of not building identity is not building it at all.

**What this does not change, and why it matters:**

| | Whose job |
|---|---|
| *Who is this person?* | the parent codebase |
| *May they open `proj_x`?* | **Allure** |
| *May they spend 30 Meshy credits?* | **Allure** |
| *May this link show this tour and nothing else?* | **Allure** |
| *May this request read `/files/projects/x/renders/…`?* | **Allure** |

The parent cannot answer the last four: it does not know which projects exist, who owns them, what a tour package contains, or what a mesh costs. **So P0-SEC-002 through P0-SEC-006 stay correct and stay necessary.** They were never about who you are; they are about what you may do.

**The size of the link, measured:** everything outside `app/auth/` touches identity through one type and two functions — **9 call sites in 2 files** (`projects_routes.py` ×6, `main.py` ×3). Linking means replacing **one function**, `resolve_session`, with whatever the parent hands over, and mapping it to a `Principal`. The authorization layer above it does not change.

**Redundant on the day it is linked:** `POST /api/auth/register` and `/login` (delete), `password_hash` + scrypt (stops being written). **`users.external_id` becomes the join to the parent's user id** — it was added nullable for exactly this, before the decision existed. `users`, `role` and `project_members` stay: project membership is Allure's, not the parent's.

**Why the local login was still worth building:** P0-SEC-002 closed 60 of 63 routes, and a gate with no way through it is an outage, not a control; it is the standalone path every test and the container use; and it defines the contract the parent will satisfy. The cost of the choice is one module and two routes.

**Evidence:** `docs/AUTH_PLAN.md` — status changed from *decision open* to **DECIDED**, with the full record appended and the original A/B/C analysis kept intact.

---

### 🟢 P0-QA-003 — Record the runtime and accuracy baseline ✅ LAST P0
**Hat:** QA Engineer · **Completed:** 2026-09-21 · **Meshy: 0 credits**

**Durations: N=3 projects / N=6 runs.** Real Blender builds against a *copy* of the data directory.

| Project | objects | rooms | builds (s) |
|---|---:|---:|---|
| Sample reference run | 14 | 5 | 39.4, 38.4 |
| test 1 | 13 | 1 | 35.4, 29.4 |
| Seed Project | 8 | 2 | 19.6, 15.8 |

**mean 29.66 s, median 32.39, range 15.75–39.42, stdev 9.98.** Per stage: `preview` **16.93 s**, `objects` **5.07 s**, everything else under 1.5 s. Stage means sum to 25.01 s vs a 29.66 s total — the 4.65 s gap is Blender startup/exit, outside the timed region, stated rather than smoothed.

**The documented `40–60 s` is retracted.** It was N=1, and **no run in this batch reached 40 s**.

**Accuracy: N=2**, and the result matters.

| Project | coverage | placement @1.0m | @0.5m | **composite** |
|---|---:|---:|---:|---:|
| test 1 | 100% | 91% | 55% | **98%** |
| Sample reference run | **75%** | 100% | 100% | **94%** |
| spread | **25.0 pts** | 9.1 | 45.5 | 3.9 pts |

The first project **reproduces the documented N=1 figures exactly** — so that measurement was not a fluke *for that project*. The second scores **94%, below the 95% target**, with five pieces no camera can reach; the harness reports `levers exhausted at 94%`. **98% was the better of two, not a typical value**, and coverage — the metric that catches missing meshes — swings **25 points**.

**Why accuracy is N=2 and durations are N=3:** accuracy scores a built scene against the moodboard reading the client approved. `proj_seed` is hand-authored and never went through the pipeline, so there is nothing to score it against — but it still builds. Reaching N=3 needs a third project run end to end from photographs. Inventing a third point by scoring a scene against itself would be worse than reporting N=2.

**The exit criterion, answered honestly:** *"until all the models reach 95%+"* is **NOT met at N=2** — one project 98%, one 94%. At N=2 that cannot be called a rate in either direction, which is the entire point of measuring N.

**An instrumentation defect found by measuring.** `build_scene.py` emitted `ALLURE_STAGE` using `Timer.seconds` — **elapsed-since-start, a cumulative mark, not a duration** — and `build.py:83` printed those straight into the project's event feed. On a real build the log claimed **`lighting 7.82s`**; lighting took **0.00 s**. The product was telling operators something false about where its time went. Fixed at source; the stages now sum **exactly** to the total (24.45 = 24.45), which they could not before. The benchmark checks for a regression on every run.

**Corrections applied** to `AUDIT_CODEBASE.md`, `TRD.md` (×2), `plan.md` (×3), `PRD.md`, and `v4_baseline.json` (`measured_pipeline_timings` marked superseded).

| Suite | Result |
|---|---|
| **Full backend** | **1170 passed · 10 skipped · 30 xfailed · 0 failed** |

**Evidence:** `version 4/evidence/P0-QA-003/` · `docs/benchmarks/v4_runtime_baseline.json` · `research/v4_runtime_baseline.py`

---

### 🟢 P1-IDENTITY-001 · 002 · 003 · 004 — The provenance chain ⭐ CRITICAL PATH
**Hat:** Backend + Spatial + Blender + 3D Engineer · **Completed:** 2026-09-22

**Identity survived only as a join nobody performed:** `plan_key` → `ObjectPlanItem.object_key` → `.element_id`. Three identical bar stools looked like three unrelated objects. `item.element_id` was in scope at the compiler's `SceneObject(...)` constructor and simply **unused**.

| Task | Hop | Result |
|---|---|---|
| **001** | `SceneObject` | `element_id` + `instance_id`, both Optional/None; `plan_key` **kept**; flat `source_intent_ids` accessor |
| **002** | compiler | 3-count item → **1 element_id, 3 distinct instance_ids**, deterministic |
| **003** | Blender manifest | 3 identity fields per entry; `MANIFEST_VERSION` **1.1 → 1.2** |
| **004** | asset record | `canonical_element_id` + `source_image_id` |

**`manifest_version` had been written since 1.0 and never read by anything** — a version nobody checks is a comment. `build_scene.py` now refuses a major it does not understand. Verified in a **real Blender process**: 1.2 builds (8 objects, validation OK); **2.0 is refused**. A minor bump is accepted (it only adds keys); an absent version is accepted (valid 1.x).

**Decisions:** `instance_id` is **derived**, not resolved from `ElementInstance` rows — resolving would make `app/planning` import `app/intelligence`, crossing the boundary `scene/schema.py` exists to keep, and derived is deterministic (no uuid, no clock). No element → **`None`**, never an invented id: a catalog piece is not an occurrence of anything the client approved, and a fake id becomes a fiction every consumer treats as fact. `canonical_element_id` is named for the **canonical** key so three stools share one asset — calling it `element_id` would invite the per-occurrence mistake that made three stools three purchases.

| Check | Result |
|---|---|
| Pre-V4 `scene_spec.json` loads | ✅ |
| **69/69 real registry records load unchanged** | ✅ |
| Built scene otherwise unchanged | ✅ geometry keys identical with/without identity |
| count ≠ instances surfaced | ✅ warning names both numbers |

**Teeth by mutation:** `instance_id` keyed on the loop index alone → caught; divergence tolerated silently → caught.

| Suite | Result |
|---|---|
| `test_element_identity.py` | **12 passed** |
| `test_manifest_identity.py` | **18 passed** |
| **Full backend** | **1200 passed · 10 skipped · 30 xfailed · 0 failed** |

**Two corrections to my own work:** my determinism test rebuilt the scene each time and `object_id` has a random default_factory — it was comparing two different objects, so the test was wrong, not the code. And a pre-existing test froze `manifest_version == "1.1"`; it now asserts against the imported constant **plus** that the major is still 1, which catches an accidental breaking bump the literal could not.

**Evidence:** `version 4/evidence/P1-IDENTITY/verification.md`

---

### 🟢 P1-IDENTITY-005 — Provenance query and index
**Hat:** Backend Engineer (+ Data) · **Completed:** 2026-09-22

**Present is not the same as answerable.** After 001–004 every hop carried identity; answering *"which uploaded photo caused this rendered chair?"* still meant opening four JSON files by hand. Now: `GET /projects/{id}/provenance/{scene_object_id}` returns the whole chain, and `GET /projects/{id}/provenance` counts how much of a scene traces — measured, never asserted.

| Piece | Decision |
|---|---|
| Index (`elements`, `element_instances`, schema **v8**) | **Derived, not a second record.** Rebuilt from disk by `index_project()`; a stale index is an inconvenience, never data loss. No FKs, so a re-index never fails on a momentarily absent project row |
| Staleness | Two `stat` calls per read; no backfill migration that parses every project's JSON (that turns a deploy into an outage) |
| `resolved` vs `gap` | A hop that did not resolve because its inputs were absent is **not** a defect. A moodboard-read sideboard has no `DesignIntent`; calling that a broken chain buries the one break that matters — an instance with no definition |
| Pre-V4 files | Every real `scene_spec.json` carries `element_id: null`; the resolver falls back to the `plan_key` join and **says so in the hop** |
| Source photos | Exact (`via: design_intent`) and contributing (`via: moodboard_reference`) are **never collapsed into one list** — a contributing reference is not a claim of identity |
| Catalog pieces | `origin: planner_catalog`, complete at `scene_object` — nothing upstream to break, and no invented id |

**Found by the query, fixed:** `review_scene_reading` used to say "nothing else changes" — approving a crop the check had rejected never re-resolved identity, so the piece stayed outside the canonical set forever and two approved identical chairs became two Meshy generations. It now re-resolves and re-indexes on every decision.

| Check | Result |
|---|---|
| **Every object in the golden scene resolves** (7/7, `gaps {}`) | ✅ `tests/test_provenance.py` |
| Sofa → uploaded `living.png` via its classified intent, URL serves 200 | ✅ |
| 3 stools → 1 `cel_` definition, 3 instance ids, `instance_count 3` | ✅ |
| Real break reported as a gap; stale index rebuilt on read | ✅ |
| 404 on unknown object; 401 anonymous on both routes | ✅ |
| Mutations M1 (drop plan_key fallback) · M2 (`complete` ignores gaps) · M3 (never stale) | **all CAUGHT**, source restored |
| Real `proj_553cb09794` | 14/14 complete, **0 traced to element** — reading predates `resolve_elements()`; unresolved, not a gap |
| Real `proj_a25a006c88` | 9/11 complete, **`instance: 2` gaps** — the approved-but-unresolved rug + TV unit; the review fix repairs them on the next PATCH. Data untouched |
| **Full backend** | **1209 passed · 10 skipped · 30 xfailed · 0 failed** (390 s) |

**One correction to my own work:** the first test put the canonical `cel_` id on `SceneObject.element_id`; the compiler writes the **reading-row** `el_` id (from `ObjectPlanItem.element_id`) and reaches the definition through the instance row. The test now follows the compiler.

**Not done here:** the `:8000` process still runs pre-provenance code (started 2026-09-21 15:44 UTC) and needs a restart before the routes exist on it; verified through the same ASGI app via TestClient.

**Evidence:** `version 4/evidence/P1-IDENTITY-005/verification.md` + captured chains and coverage JSON

---

### 🟢 P1-IDENTITY-006 — Golden identity benchmark ✅ PHASE 2 GATE (M2)
**Hat:** AI Evaluation Engineer (+ QA) · **Completed:** 2026-09-22

**The guards existed; their effectiveness had never been measured.** The ablation that chose the key scored *candidate key functions* and counted "assets" as "keys". This harness runs the **shipped** `resolve_elements()` (after `mark_duplicates()`, as production does) over a hand-labelled set and counts generations by the **production spend rule** — `approved_for_generation` → `distinct_shapes` → `storage_key`/mesh-on-disk — so a "generation" here is one the job would actually buy.

| Figure | Value | N |
|---|---|---|
| **False-merge rate** | **0.0** | 0 / 35 definitions, 10 cases |
| **False-split rate** | **0.0** | 0 / 35 labelled pieces |
| **Instance-count accuracy** | **1.0** | 33 / 33 (room, type) cells |
| Rows | **52 trustworthy** | 37 synthetic + 15 real (proj_553cb09794, 26 rows labelled by eye, 11 excluded as untrustworthy) |
| Golden composition | **11 definitions · 17 instances · 10 generations** | TV unit reused, 0 spend; reuse rate 0.41; 1.7 instances / generation |
| 3 stools → 1 · 2 chairs → 1 · 2 side tables → 2 · 2 dark + 1 light stool → 2 · `television` ≠ `tv_unit` | ✅ all | pinned in `tests/test_p1_identity_benchmark.py` (6 passed) |

**Spec contradiction found, not papered over (C10):** §29.1 states "10 definitions · ≤9 generations" *and* requires the two side tables to stay two definitions. Both cannot hold. The no-false-merge rule governs (it is the ablation's own decision rule), so the correct arithmetic is **11 / 17 / 10**, which is what was measured. The benchmark JSON carries the note.

**Teeth by mutation** (shipped resolver mutated, benchmark must notice; source restored): colour dropped from the key → **caught**; position key restored → **caught**; untrustworthy rows admitted → **survived at first**, then pinned with a synthetic `one_rejected_stool` case → **caught**.

**CI:** `data/projects` is not tracked, so the real-project case is dropped when absent and the report says so in `absent_cases`; synthetic N alone is 37.

**What this is not:** an identity-*resolution* measurement with no model in the loop. Whether the reader *sees* three stools is reading quality, a different number, not claimed here.

**Regression:** targeted (no production code changed) — 64 passed across the identity/provenance suites + this file; full suite 1209 passed 30 min earlier.

**Evidence:** `version 4/evidence/P1-IDENTITY-006/verification.md` · `docs/benchmarks/p1_identity_benchmark.json`

---

### 🟢 P1-ASSET-001 — Re-bind assets on moodboard re-read
**Hat:** Backend (+ GenAI) · **Completed:** 2026-09-22 · **Meshy spend: 0**

Reading ids are minted from `room|type|name|bbox`; a forced re-read moves every box, every id changes, and the `asset_id` on the old row vanished with it — approvals were carried by canonical key, bindings were not. Now `carry_asset_bindings()` re-binds by the **position-free canonical key** (a changed piece gets no carry and is generated afresh; a `|?` no-evidence key never inherits; a loose `room|type|material|colour` pass only when unique on both sides), `_read_scene` carries before `resolve_elements()`, and `generate_elements` treats a group carrying a registry-resolvable `asset_id` as **paid for before any file lookup** — which also covers meshes bought under the legacy position-keyed name. Approvals are deliberately **not** carried (spend on a crop nobody has seen is what the gate exists to stop).

| Check | Result |
|---|---|
| Re-read with bound assets → **0** submissions, every asset bound, ids all new | ✅ |
| One recoloured piece → exactly **1** submission, new binding, others untouched | ✅ |
| Bindings stripped → **3** re-purchases (the old behaviour, reproduced) | ✅ |
| Mutations: bound check off · position key · previous never captured | **3/3 caught** |
| `tests/test_asset_rebind.py` | 9 passed · targeted 103 passed |

**Evidence:** `version 4/evidence/P1-ASSET-001/`

---

### 🟢 P1-ASSET-002 — Meshy idempotency key ⭐ CRITICAL PATH
**Hat:** Backend · **Completed:** 2026-09-22 · **Meshy spend: 0**

**The fourth spend gate.** `generation_tasks` (schema **v9**, `app/spend/tasks.py`): `request_id = sha1(canonical key | sha256(crop) | params)` — the canonical key, not the bbox-minted `element_id` the task text names, because a re-read would otherwise defeat the key exactly when it matters. The receipt is written **before** anything waits; a retry finds it and **polls**. Only the vendor ending the task (`MeshyTaskFailed`, new) or an ingest rejection clears it — a timeout or dropped connection is not a reason to buy again.

| Check | Result |
|---|---|
| Kill mid-generation (3 tasks live) → **real restart** (`_reset_singletons`) → rerun: **+0 submissions**, the same 3 task ids polled, 3 bound, spend ledger 90 not 180 | ✅ |
| Vendor-failed → re-submitted once each; timeout → receipt kept; next run polls | ✅ |
| Key deterministic; different crop/params/piece → different | ✅ |
| Mutations: resume off · receipt after wait · any error clears | **3/3 caught** |
| `tests/test_generation_idempotency.py` | 4 passed · targeted 81 passed |

**Evidence:** `version 4/evidence/P1-ASSET-002/`

---

### 🟢 P1-ASSET-003 — Distinguish the two Meshy 429s
**Hat:** Backend · **Completed:** 2026-09-22 · **Meshy spend: 0**

**Researched** (`docs.meshy.ai/en/api/rate-limits`, 2026-09-22): both are `429`; the body says `RateLimitExceeded` (20 req/s) or `NoMoreConcurrentTasks` (queue 10/30/20/100 by plan, per account across keys); **no Retry-After documented.** `_raise_for` now classifies; `_send()` routes every request: rate limit → exponential backoff 0.5 s ×2 with jitter (6 tries); full queue → **steady 10 s slot wait** (90 tries). `meshy_max_concurrent_tasks = 8` (under Pro's 10) enforced by a semaphore held from submit to done.

| Check | Result |
|---|---|
| Queue-429 ×3 → sleeps `[10, 10, 10]`, then success; rate-429 ×3 → increasing sub-10 s waits | ✅ |
| 6 pieces, cap 2 → max in flight **2** | ✅ |
| Mutations: queue collapsed into rate · no retry · cap removed | **3/3 caught** |
| `tests/test_meshy_rate_limits.py` | 10 passed |

**Not done:** a load test against the live account — real spend for no assertion the semaphore test does not give. **Evidence:** `version 4/evidence/P1-ASSET-003/`

---

### 🟢 P1-ASSET-004 — Persist meshes within the vendor retention window
**Hat:** Backend (+ DevOps) · **Completed:** 2026-09-22 · **Meshy spend: 0**

The download already preceded completion; the invariant was unstated, and **Meshy's signed thumbnail URL was stored on the asset record and served to the UI** — a reference that dies with the 3-day window. Now `assets.pipeline.persisted()` must be empty (original + normalized bytes present, no vendor file URL) before `SUCCEEDED`/checkpoint; on failure the download is unlinked (the file *is* the checkpoint); thumbnails are persisted beside the mesh as local `/files/…` URLs; a record or binding without its bytes is **not** a receipt; and a `SUCCEEDED` task whose bytes were lost is **re-downloaded from the vendor's open task**, never bought again.

| Check | Result |
|---|---|
| Real ingester, real GLB: every completion has both files, no vendor host anywhere on disk | ✅ |
| **Vendor URLs expired after download → next run +0 submissions, meshes resolve, thumbnails serve 200 from Allure** | ✅ |
| Not persisted ⇒ not done; bytes lost ⇒ re-ingest or re-poll, +0 submissions | ✅ |
| Mutations (5): invariant off · no unlink · reuse without bytes ×2 · SUCCEEDED not re-pollable | **5/5 caught** (one needed the loss tests first) |
| `tests/test_asset_persistence.py` | 5 passed · asset suites 81 passed |

**Full backend after 001–004: 1243 passed · 10 skipped · 30 xfailed · 0 failed (356 s).** **Evidence:** `version 4/evidence/P1-ASSET-004/`

---

---

## 3. In progress

*Nothing in progress — next task starts clean.*

---

## 4. Blocked

**Nothing is blocked.** The one owner decision was made on 2026-09-21; see P0-SEC-000 above.

---

## 5. Corrections discovered during execution

Recorded rather than silently applied, per `task.md` §35 Change Control.

| # | Original claim | Verified reality | Impact |
|---|---|---|---|
| C1 | `/cinematic` is a dead route returning 404 (P0 defect) | **Optional integration, degrades gracefully by design** | P0-FRONTEND-001 → `[ALREADY DONE]`; **one P0 defect drops** |
| C2 | 30 xfails are "unexplained" | 5 decorators, all with `strict=True` + `reason=` | P0-QA-002 was ~90% pre-done |
| C3 | Valid Blender looks include `Punchy`, `Base Contrast` | **Namespaced only** — `AgX - Punchy`, `AgX - Base Contrast` | Corrected before shipping the fix |
| C4 | `RaytraceEEVEE` defaults `[UNKNOWN]` (TRD U18) | **Probed: `use_raytracing` defaults `False`** | U18 resolved; unblocks P1-RENDER-002 |
| C5 | Dev target is AWS G6e / L40S 48 GB | **RTX 3050 6GB Laptop · 15.65 GB RAM (0.84 GB free)** | Infrastructure corrected across 4 docs |
| C6 | `enable_pbr` inherits Meshy's `false` default | Allure **explicitly passes `enable_pbr=True`** | Asset path better than documented |
| **C8** | `/api/projects/{id}/jobs` is an ordinary job route | **Wildcard dispatcher** — caller-supplied `type` + `params` reaches **all 13** job types, unauthenticated | Raises the ceiling on P0-SEC-002: protecting named generation routes alone would leave this open |
| **C9** | 11 job types (`task.md`, `AUDIT_CODEBASE.md`) | **13** — 11 modules, 2 of which register twice | Inventory, observability and CI coverage all keyed off the wrong number |
| **C7** | `conftest.py` blanks all provider keys for the suite | **It did not.** Blanking sat in the non-autouse `env` fixture; **547 of 728** test functions read the real `.env` | Suite was only accidentally offline. **Fixed** — autouse `_no_real_keys`; baseline note corrected |
| **C10** | §29.1 golden arithmetic: "10 definitions · 17 instances · ≤9 generations" | **Self-contradictory** with criterion 4 (2 side tables stay 2 definitions): 10 rows with that row split = **11 definitions**, and with the TV unit owned = **10 generations** | P1-IDENTITY-006 measured **11 / 17 / 10**; the no-false-merge rule governs. `task.md` §29.1 and P1-IDENTITY-006 not edited — recorded here and in the benchmark JSON |
| **C11** | P0-SEC-005: "the 3D viewer still loads its assets" (35 requests, all 200) | **Only the anonymous share-token viewer was browser-verified.** The **signed-in** `/3d` route answered **401** on every texture and mesh since P0-SEC-005: three.js loads are CORS requests (`crossOrigin=anonymous`), `:3001 → :8000` is a different origin, so the session cookie was never sent | Found in the browser 2026-09-23; **fixed** in the frontend (`loader-credentials.ts`, credentials on every three.js loader); verified by network log, server log and screenshot — `evidence/RUN-2026-09-23/` |

**C1 correction APPLIED 2026-09-21** to `AUDIT_CODEBASE.md` (9 places), `plan.md` (5), `TRD.md` (5), `task.md` (the whole P0-FRONTEND-001 block), `PRD.md` (1), and `docs/benchmarks/v4_baseline.json` (1, JSON re-validated). Withdrawn claims are struck through and labelled rather than deleted, so the record shows what was believed and why it was wrong. **`design.md` never carried the error** — the earlier note listing it was itself inaccurate; `grep -n cinematic` over it returns nothing.

---

## 6. Environment — verified, and binding

| Resource | Measured 2026-09-21 |
|---|---|
| GPU | **RTX 3050 6GB Laptop** — 6144 MiB, driver 592.82 |
| RAM | **15.65 GB total · 0.84 GB free · 45.21 GB commit** |
| CPU | i5-13420H — 8C / 12T |
| Blender | 5.2.1 LTS at `H:/Program Files/Blender Foundation/Blender 5.2/` |
| Backend | `:8000` ✅ running on `02ca264` (fix loaded) |
| Frontend | `:3001` ✅ running |
| Ollama | `:11434` |
| **Playwright** | ✅ **WORKING** — real Chrome, navigation, snapshots, console, `run_code` |

---

## 6b. Run verification — 2026-09-23

Both servers restarted on today's code and driven in a **real browser** (Playwright): sign-in, Studio, a real project at step 6, Review & Refine, and the 3D viewer. **One defect found and fixed (C11)** — the signed-in 3D viewer had been unusable since P0-SEC-005. After the fix: 13 objects rendered, 23 file loads all 200, 0 console errors; frontend `tsc` clean, unit tests 46 passed. Paid steps not clicked. Evidence: `version 4/evidence/RUN-2026-09-23/verification.md` + 6 screenshots.

---

## 7. Exit criteria — status

The stated exit bar is *"all models ≥95% accuracy and production-grade."* Tracked honestly:

| Criterion | Status | How it will be measured |
|---|---|---|
| Element identity accuracy ≥95% | **False-merge 0.0 · false-split 0.0** at N=52 rows / 35 pieces (37 synthetic + 15 real) | `docs/benchmarks/p1_identity_benchmark.json` — resolver only, no model in the loop |
| Instance count accuracy ≥95% | **1.0** (33/33 cells, N=52 rows) | Same — resolver only; reading quality is a separate, unmeasured number |
| False merge / false split rate | **0 / 35 · 0 / 35** | Same |
| Spatial validity ≥95% | `UNKNOWN` | `validate_scene` violations = 0 over N projects |
| Render verification pass ≥95% | `UNKNOWN` | P1-VALIDATOR-001, once built |
| Composite pipeline accuracy | **98% at N=1** | ⚠️ single observation, **not a rate** — needs N≥3 |
| Production-grade (security) | **NOT MET** | No auth on 63 routes |
| Production-grade (deployment) | **NOT MET** | No container, no CI |

**No accuracy figure may be claimed as ≥95% until measured at N≥3.** The one 98% figure is N=1 and is recorded as an observation, not a rate.

---

## 8. Next actions, in order

**All 19 P0 tasks are complete.** Next is P1 — 46 tasks.

1. ~~P1-IDENTITY-∗~~ **done (001–006, M2 gate met)**
2. ~~P1-ASSET-001 → 004~~ **done** — re-bind on re-read, idempotency key (fourth spend gate), the two 429s, retention-window persistence
3. **P1-ASSET-005** — measure and store the forward axis at ingest (Blender's `_native_forward_yaw` heuristic exists at import time; nothing is stored in `yaw_offset`)
3. **P1-RENDER-002** — render quality, now that P0-RENDER-001 unblocked it
4. **P1-EVENT-∗** — typed events on the `runner._execute` choke point, which P0-OBSERVABILITY-001 prepared
5. **P1-QA-001** — CI coverage gates, which P0-INFRA-001 prepared

**Completed:** every P0 task (19/19), plus 2 unplanned (P0-QA-004, P0-FRONTEND-003) and the C1 correction sweep.
