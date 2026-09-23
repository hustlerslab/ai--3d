# P0-SEC-002 — Evidence: authorization at one choke point, deny by default

**Completed 2026-09-21.** A person's home photographs and designs are now visible only to them.

---

## Acceptance criteria

| Criterion | Result | Proof |
|---|---|---|
| Unauthenticated → **401** | ✅ | `test_anonymous_is_401_not_403`; live server probe |
| Another user's project → **403** | ✅ | `test_another_user_is_403` + 7 parametrised mutating routes |
| Owner's own project → **200** | ✅ | `test_the_owner_gets_their_own_project` |
| **Anonymous share link still works** | ✅ | `test_the_share_link_is_still_anonymous` — `GET /{id}/tour` returns 404 `TOUR_NOT_READY`, **not** 401 |
| Authz matrix covers every route × role | ✅ | 21 tests, incl. a walk of the **real route table** |
| Existing projects backfilled to an owner | ✅ | first-run bootstrap; measured adopting 3 projects |

## The gate

**One router-level dependency**, attached in `main.py` on both routers — not 63 per-route decorators. A per-route check is a per-route opportunity to forget, and the forgotten one is the one that matters.

Measured by walking the live route table:

```
probed=62  skipped=0  allow-listed=2  gated-401=60
status codes seen: {200: 1, 401: 60, 404: 1}
```

**Zero unguarded routes.** The coverage test fails on any route that answers an anonymous request without being on the justified allow-list — so "deny by default" is a property of the system, not of the cases someone remembered to write.

## Deliberately anonymous, each a decision

| Route | Why |
|---|---|
| `GET /health`, `GET /` | Liveness. A probe needing credentials reports the wrong thing during an outage. |
| `/api/auth/*` | You cannot authenticate in order to authenticate. |
| `GET /api/projects/{id}/tour` | The share link is a feature (`AUTH_PLAN.md`). **P0-SEC-004** replaces it with a capability token. |
| `/files/*` | `AUTH_PLAN.md` calls this the largest single hole; it is **P0-SEC-005**'s whole job. Guarding it here in passing would be worse than guarding it there deliberately. |

## First-run bootstrap — and its stated cost

`owner_id` is nullable with **no default**. There was no user to point existing rows at: the database predates the users table by three schema versions. A `NOT NULL DEFAULT` would have to *invent* an owner, and an invented owner is worse than an honest NULL. NULL means unclaimed, and only an admin may read an unclaimed project.

So the **first account created on an instance becomes administrator and adopts every unowned project**. Without it, switching on deny-by-default locks everyone out of a database that already holds work.

**The security cost, stated rather than hidden:** between deploying this and creating the first account, whoever registers first becomes administrator. On a laptop that is the operator. On a reachable host it is a race — **the first account must be created before the host is exposed.** P0-INFRA-001 carries this as a deployment step. The code only fires when `users` holds exactly one row, so it cannot be replayed (`test_the_second_account_is_not_an_admin`).

## Test results

| Suite | Result |
|---|---|
| `tests/test_authz_matrix.py` | **21 passed** |
| `tests/test_auth_identity.py` | **26 passed** |
| **Full backend** | **1032 passed · 10 skipped · 30 xfailed · 0 failed** (177.88 s) |

### The blast radius, handled honestly

Turning on enforcement broke **152 existing tests** — every one an existing suite calling a now-gated route anonymously. They were **not** weakened and the gate was **not** loosened. A shared `sign_in_admin()` helper in `conftest.py` signs each product-behaviour suite in; every assertion is unchanged. Administrator specifically, because its visibility matches the pre-auth behaviour those suites were written against.

Two tests in `test_auth_identity.py` were **inverted on purpose** and say so in place: they asserted the API was still open, which was P0-SEC-001's explicit contract ("capability, not enforcement") and is exactly what this task ends.

## Teeth verified by mutation

| Mutation | Tests failed |
|---|---:|
| **A** — treat authenticated as authorized (classic IDOR) | **11** |
| **B** — add `/api/` to the anonymous allow-list | **13** |

Source restored; 21 pass.

## Live browser verification (Playwright)

Snapshots in this folder, captured against the running stack:

| # | File | State |
|---|---|---|
| 1 | `page-...14-50-06...yml` | Sign-in form — *"Your projects, photographs and designs are visible only to you."* |
| 2 | `page-...14-50-20...yml` | Toggled to "Create your account", length hint appears |
| 3 | `page-...14-50-41...yml` | **Signed in as browser-check@example.com · admin**, studio loaded, *"3 projects on this engine"* |
| 4 | `page-...14-51-01...yml` | Signed out → back to the form |

Network, from the browser:

```
[GET]  /api/auth/session  => 200
[POST] /api/auth/register => 200
[GET]  /api/projects      => 200
[GET]  /api/credits       => 200
```

**Console errors: 0.**

CORS preflight from the real origin:

```
access-control-allow-origin: http://localhost:3001
access-control-allow-credentials: true
access-control-allow-methods: GET, POST, PATCH, PUT, DELETE, OPTIONS
access-control-allow-headers: Accept, ..., Authorization, ..., Content-Type
```

No wildcards — the spec forbids them once credentials are allowed, and `cors_origins` is a parsed list that is never `*`.

## Side effect of verifying, and its reversal

Both probes (curl and browser) registered on the **real dev database**, so first-run bootstrap fired and handed the operator's 3 existing projects to a throwaway account. That was a genuine side effect of my own testing, not a design outcome.

Both accounts were removed and `owner_id` returned to NULL on all three rows — the exact pre-probe state:

```
AFTER: proj_553cb09794 | owner: None
       proj_seed       | owner: None
       proj_a25a006c88 | owner: None
users: []   sessions: 0
```

**The operator's own first registration will therefore bootstrap as administrator and adopt all three**, as a real first run does.
