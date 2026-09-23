# P0-SEC-006 — Evidence: rate limiting

**Completed 2026-09-21.** A single client cannot exhaust the service or the job queue.

---

## Acceptance criteria

| Criterion | Result |
|---|---|
| Exceeding a limit returns **429** | ✅ with `Retry-After`, `code: RATE_LIMITED`, `retryable: true` |
| Limits are **configurable** | ✅ five env vars; `0` disables a bucket; `rate_limit_enabled=false` disables all |
| **Normal use is unaffected** | ✅ a realistic studio session and a full share-page load, both clean |

## Four buckets, not one number

Reading a project list and spending thirty Meshy credits are not the same act, and a number loose enough for the first is useless for the second.

| Bucket | Default | Keyed on | Covers |
|---|---:|---|---|
| `auth` | 10 / 60 s | **client address** | `/api/auth/*` — where password guessing lives |
| `spend` | 5 / 60 s | principal | `elements/generate`, `assets/resolve`, and `POST /jobs` |
| `write` | 60 / 60 s | principal | every other mutating route |
| `read` | 300 / 60 s | principal | reads — deliberately generous |

**`POST /jobs` is priced as spending** even though most job types are free: P0-ARCH-001 established it is a wildcard dispatcher that reaches both Meshy handlers.

**`auth` keys on the address, everything else on the principal.** A login attempt has no principal — and one that did would let an attacker reset their own limit by signing out. Conversely, keying everything on the address would let one office behind one NAT exhaust everyone's allowance.

## The load test

Driving a real route past its limit, end to end through the middleware:

```
RATE_LIMIT_WRITE_PER_WINDOW=5, nine POST /api/projects
  -> [200, 200, 200, 200, 200, 429, 429, 429, 429]
  Retry-After: <digits>   code: RATE_LIMITED   retryable: true
```

Brute force, `RATE_LIMIT_AUTH_PER_WINDOW=4`, eight wrong passwords → **four 401s then four 429s**.

**A refused request never reaches the handler.** With a limit of 2 and six creates, exactly **2 projects exist**. A 429 that still did the work is not a limit.

## Normal use, asserted rather than assumed

Two tests exist purely so the limits cannot quietly become too tight:

- **A realistic studio session** — three page loads (session, projects, credits, catalog) plus creating a project plus twenty job/event polls. **No 429.**
- **A share page loading one tour** — the tour JSON plus forty asset fetches. **No 429.** A limiter that makes a shared link look broken is worse than none.

If either ever fails, the right response is to read the test, not to raise every number until it passes.

## Teeth verified by mutation

| Mutation | Tests failed |
|---|---:|
| **A** — spend routes fall into the `write` bucket (one shared allowance) | **3** |
| **B** — `auth` keyed on the principal, so signing out resets it | **1** |

## Test results

| Suite | Result |
|---|---|
| `tests/test_rate_limiting.py` | **24 passed** |
| **Full backend** | **1133 passed · 10 skipped · 30 xfailed · 0 failed** (515 s) |

## Two things stated rather than hidden

**1. Deliberately in-process.** The job runner is already an in-process thread pool (`AUTH_PLAN.md` finding 2), so a second instance would need a shared store for both. Until Allure runs more than one process, a dict is the honest amount of machinery — and a limiter that silently gave every instance its own allowance would be *worse* than none, because it would read as protection. This is recorded for P0-INFRA-001.

**2. The test suite resets the limiter between tests.** `auth` keys on the client address, and every test that signs in shares one address — the eleventh registration in a suite of a thousand would 429, and the failure would look like an auth bug in whichever test happened to be eleventh. The autouse fixture does **not** weaken the limiter: `test_rate_limiting.py` drives past each bucket deliberately.

## One test bug of my own, corrected

`test_a_refused_request_never_reaches_the_handler` first counted the whole project store and expected 2, but the app seeds `proj_seed` at startup, so it saw 3. The limiter was correct — four refusals were logged and only two projects were created. I fixed the test's arithmetic to count only what it created, rather than making the assertion about `ensure_seed`.
