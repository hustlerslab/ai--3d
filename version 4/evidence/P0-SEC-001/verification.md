# P0-SEC-001 — Evidence: identity exists, and enforces nothing

**Completed 2026-09-21.** Allure can now tell one person from another. It still lets everyone in — deliberately.

---

## Acceptance criteria

| Criterion | Result | Proof |
|---|---|---|
| A user can register and sign in | ✅ | `test_a_person_can_register_and_is_signed_in_immediately`, `test_sign_in_with_the_right_password` |
| Dependency yields a principal for a valid session, **401 otherwise** | ✅ | `test_no_token_is_401` + 4 parametrised malformed-token cases + expiry + revocation + disabled account |
| **Existing routes still work** — capability, not enforcement | ✅ | `test_the_existing_api_is_still_completely_open`; full suite **1011 passed, 0 failed** |
| Migration runs twice safely, additive only | ✅ | measured below |

## The migration, run twice

```
first  open -> version 3
tables: analyses, events, inputs, jobs, meta, outputs, projects, scene_specs, sessions, users
second open -> version 3   (ran twice, no error)
users cols:    user_id, email, role, password_hash, external_id, created_at, disabled_at
sessions cols: token_hash, user_id, created_at, expires_at, revoked_at
```

Additive: the eight pre-existing tables are untouched, no column is altered or dropped, and no route reads the new tables.

## Test results

| Suite | Result |
|---|---|
| `tests/test_auth_identity.py` | **26 passed** |
| Full backend suite | **1011 passed · 10 skipped · 30 xfailed · 0 failed** (289.83 s) |

Baseline accounting: 970 + 4 (`test_providers`) + 12 (`test_no_silent_mock`) + 26 (`test_auth_identity`) = 1012, minus one Ollama test now skipping because Ollama is not running. That skip is environment drift, not a regression.

## Teeth verified by mutation

Twenty-six green tests prove nothing on their own. Two deliberate defects were introduced:

| Mutation | Tests failed |
|---|---:|
| **A** — honour the caller-supplied `role` on registration (classic privilege escalation) | caught, incl. `test_nobody_can_make_themselves_an_admin_by_asking` |
| **B** — store the session token instead of its SHA-256 | caught, incl. `test_the_session_token_itself_is_never_stored` |
| Combined run | **9 failed, 17 passed** |

Source restored; 26 pass again.

## Design decisions, and why

| Decision | Reasoning |
|---|---|
| **`hashlib.scrypt`**, not bcrypt/argon2/passlib | Memory-hard, in the stdlib since 3.6. A dependency on a security path is a supply chain to own. Cost parameters live inside the hash string, so raising them later is a per-user upgrade at next login, not a migration. |
| **Opaque session tokens**, not JWT | `AUTH_PLAN.md` cites an HS256 JWT ADR — but that ADR belongs to a *sibling codebase*, and a JWT cannot be revoked before it expires. A stolen session for a customer's home photographs must be killable **now**. `logout-everywhere` is the test that proves it. |
| Only the SHA-256 is stored | A database leak must not hand over live sessions. |
| Same error for wrong password and unknown account | Anything else is a free account-enumeration oracle. A dummy verify keeps the two branches comparable in time. |
| `role` on registration is **refused**, not ignored | It is caller-controlled input. If self-registration honoured it, P0-SEC-002 would be decorative the day it shipped. |
| `secure` **not** set on the cookie | The backend is plain HTTP on localhost; a secure cookie would never be stored, producing a login that silently does nothing. Turning it on with TLS is recorded in P0-INFRA-001, not left to memory. |

## The blocked decision was not pre-empted

`docs/AUTH_PLAN.md` leaves options A/B/C open and states:

> "Steps 1–5 deliver most of the security benefit and are independent of the database decision. Only 6 and 7 depend on it — so **the A/B/C decision does not block starting.**"

`users` carries **both** `password_hash` (option B) and `external_id` (options A/C), either nullable. Shipping only one would have made the decision inside a migration. Choosing C later replaces `verify_password` and adds a callback route; `Principal` and `require_principal` — everything the rest of the codebase touches — do not change.

## One pre-existing test corrected, not weakened

`test_the_vertical_change_added_a_column_and_no_new_table` asserted `SCHEMA_VERSION == 2` and `MIGRATIONS == [2]`. Its own docstring claims something narrower: that **the vertical feature** added one column and no table. The two version assertions said "no future feature may ever add a migration" — a blocker on all schema work.

The substantive assertion, the eight-table `SCHEMA` list, is **kept byte-identical**. Three were added: the vertical step is still at version 2, `SCHEMA_VERSION >= 2`, and the ladder has no gaps or duplicates. Net: more protection, not less. All 5 `xfail(strict=True)` markers in that file still xfail — none flipped to xpass.

## New routes (6)

`POST /api/auth/register` · `POST /api/auth/login` · `POST /api/auth/logout` · `POST /api/auth/logout-everywhere` · `GET /api/auth/me` · `GET /api/auth/session`

Served paths: **64 → 70**.
