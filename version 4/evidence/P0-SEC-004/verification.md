# P0-SEC-004 — Evidence: share links as capability tokens

**Completed 2026-09-21.** Sharing a design stays effortless without making every project publicly readable.

---

## The change, in one line

**The project id used to *be* the capability.** Anyone who saw an id — in a URL, a server log, a support email — could read that project's tour, and the owner could neither rotate the id nor revoke access. The id still identifies the project. It no longer authorises anything.

## Acceptance criteria — each verified twice, in tests and against the live server

| Criterion | Tests | Live server |
|---|---|---|
| A share link opens the tour with no account | `test_a_share_link_opens_the_tour_with_no_account` | **200** with `?k=<token>`, no cookie |
| Grants **no** access beyond the tour package | 10 parametrised routes + spend + minting, all **401** | — |
| Revoking breaks the link | `test_revoking_breaks_the_link` (+3 more) | revoked → **401** |
| **Guessing a project id does not grant access** | `test_the_project_id_alone_no_longer_opens_the_tour` | id alone → **401** |

### Live sequence, against the running backend

```
1. register (first account -> admin, adopts 3 projects)   role: admin | claimed: 3
2. anonymous tour by project id alone                     401   <- the change
3. owner mints a share link                               token_id c68354792c12, 43-char token
4. anonymous WITH the link                                200
5. same link pointed at a DIFFERENT project               401
6. revoke, then the same link again                       revoked: True -> 401
```

## Design decisions

| Decision | Why |
|---|---|
| A **separate table**, not a session with flags | A session says *who you are* and unlocks everything that person may do. A capability says nothing about who you are and unlocks one thing on one project. Forwarding a link must not hand over an account. |
| Only the **SHA-256** is stored | A database leak must not hand over working share links. The token is returned once and cannot be reprinted — a link the server can reprint is one a server compromise can reprint. |
| `scope` column, one value (`tour`) | A link can never quietly become a skeleton key. Widening is a deliberate act with a name. |
| Project and scope are **in the query**, not checked after | There is no branch where the wrong project can be returned and then rejected by a caller who forgot to check. Mutation A below proves it. |
| Token in a **query parameter** | The point is that it can be pasted into a message; a header cannot be. The cost is stated in the code: query strings reach logs, history and `Referer` — which is *why* these tokens are scoped to one capability and revocable in one call. |
| Expiry **offered, not imposed** | A link that dies on its own while a client is still looking at the design is a support call. |
| Revoked links **stay listed** | "It stopped working on the 3rd" is what people actually ask; a list that forgets them cannot answer. |

## Test results

| Suite | Result |
|---|---|
| `tests/test_share_links.py` | **30 passed** |
| `tests/test_authz_matrix.py` | **21 passed** |
| **Full backend** | **1078 passed · 10 skipped · 30 xfailed · 0 failed** (190.48 s) |
| `tsc --noEmit` / `next lint` | clean / no warnings |

## Teeth verified by mutation

| Mutation | Result |
|---|---|
| **A** — drop `project_id` from the token lookup (the classic "check it later, or forget to" bug) | caught by `test_a_token_for_one_project_does_not_open_another` |
| **B** — ignore `revoked_at` | **2 failures** |

## Browser verification (Playwright)

| # | File | State |
|---|---|---|
| 1 | `page-...15-20-43...yml` | **`/w/{id}?k=<token>` with no account** — full tour: "test 1", palette swatches, *1 rooms · 2 viewpoints*, floor plan, panorama controls. **0 console errors.** |
| 2 | `page-...15-20-56...yml` | Same URL **without** the token → refused |
| 3 | `page-...15-21-33...yml` | After a wording fix → *"This link doesn't work / This link has expired or been turned off. Ask whoever shared it with you for a new one."* |

**A wording flaw I found and fixed in the browser, not in review.** The refusal first read *"This walkthrough isn't ready yet"* — which is what a 404 `TOUR_NOT_READY` means, and is a lie for a revoked link. Someone holding a link that was deliberately turned off would have waited for a render that was never coming. Now a 401 says so plainly.

## Side effect of verifying, and its reversal

The probes registered against the **real dev database**, so first-run bootstrap again handed the operator's 3 projects to a throwaway account, and my verification minted share links on a real project. All removed:

```
projects: 3, all owner: None
users: []   sessions: 0   capability_tokens: 0   spend_records: 0
```

The operator's own first registration will bootstrap as administrator and adopt all three, as a real first run does.

## What this does NOT yet do

**`/files/*` is still completely open.** A share link now guards `tour.json` — but the panorama images that tour references are served by `GET /files/projects/{id}/{path}`, which has a path-traversal guard and **no authorization at all**. Anyone who can guess or see a project id can still fetch its renders directly. `AUTH_PLAN.md` calls this the largest single hole; it is **P0-SEC-005**, the next task.
