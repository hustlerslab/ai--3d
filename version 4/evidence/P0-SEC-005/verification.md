# P0-SEC-005 — Evidence: authorize file access

**Completed 2026-09-21.** The largest single hole in `docs/AUTH_PLAN.md` is closed.

---

## Why database authorization never reached this

Scenes are **JSON and images on disk**, not rows. `GET /files/projects/{id}/{path}` had a path-traversal guard and **no authorization at all**, and `/files/assets`, `/files/assets-web`, `/files/materials` were bare `StaticFiles` mounts — **a mount is not a route**, so the router-level gate from P0-SEC-002 never saw them. Every uploaded photograph, every render, every `.blend` was readable by anyone who could guess a project id.

All four are now ordinary routes on `files_router`, behind the same gate as everything else.

## Acceptance criteria

| Criterion | Tests | Live server |
|---|---|---|
| Another user's render is **not** retrievable | `test_another_signed_in_user_cannot_fetch_a_render` → 403; stranger → 401 | pano **401**, brief **401** |
| Share holder gets only that project's tour assets | carve-out is `outputs/web/`; brief and `.blend` refused | pano **200**, brief **401**, blend **401** |
| Traversal still fails | 12 percent-encoded probes × 3 prefixes + 4 project probes | `../allure.db` → **404** |
| **The 3D viewer and share page still load their assets** | 4 tests | **35 requests, all 200, zero non-2xx** |

## The capability boundary, exactly

A tour-scoped token grants read access to the published tour package **and to exactly what that package points at** — nothing else:

1. `GET /api/projects/{id}/tour`
2. `/files/projects/{id}/outputs/web/**` — what `preview` publishes. **Not** the project directory, so the brief and the `.blend` beside it stay unreachable.
3. `/files/{assets,assets-web,materials}/**` and the read-only catalog API — the viewer cannot draw a room without them.
4. `GET /api/scenes/{id}` (+ `walkthrough/spawn|tour|views`) **only** for the scene belonging to that project.

Verified live that the boundary holds in both directions:

```
with a share token:   /api/materials 200 · /api/catalog 200 · /api/scenes/<its own> 200
                      /api/projects 401 · /api/credits 401 · /projects/<id>/analysis 401
```

## Three defects found by testing, not by review

**1. P0-SEC-002 had silently broken the share page's "Explore in 3D" tab.** It calls `/api/scenes/*`, which that task gated. Nobody would have seen it until a client opened a link. Found by tracing what the tab actually fetches; fixed by extending the capability to the scene the tour names.

**2. My first browser check was about to be a false positive.** Playwright reported the panoramas as 200 — but the server log showed **zero** matching requests: the images came from the browser's disk cache, populated when `/files/` was still anonymous. The frontend's `fileUrl()` took a path and never appended the token, so a *fresh* visitor would have seen an empty tour. Fixed with `features/tour/share-token.ts`, and re-verified against a freshly minted token with the server log as the source of truth.

**3. `material_file` raised `ImportError` and returned 500 to the browser** — `app.materials.registry` exports `get_material_registry`, not `get_registry`. My traversal test for the shared library had passed **without ever reaching the handler**: httpx and Starlette normalise `../` out of a path before the request is sent, so the route never matched. A refusal proves nothing until the code under test has run. The suite now seeds a real file, asserts it serves **200** (the handler runs), and attacks it with **percent-encoded** traversal that nothing normalises away.

## Test results

| Suite | Result |
|---|---|
| `tests/test_file_authorization.py` | **31 passed** |
| Security suites combined | **74 passed** |
| **Full backend** | **1109 passed · 10 skipped · 30 xfailed · 0 failed** |
| `tsc --noEmit` / `next lint` | clean / no warnings |

## Teeth verified by mutation

| Mutation | Tests failed |
|---|---:|
| **A** — carve-out covers the whole project directory, not `outputs/web/` | **2** |
| **B** — put `/files/` back on the anonymous allow-list | **10** |

## Browser verification (Playwright)

| File | State |
|---|---|
| `page-...15-40-08...yml` | Share link, cache-free token — tour renders; **server log confirms** `n01.jpg`/`n02.jpg` fetched with `?k=` → 200 |
| `page-...15-43-03...yml` | Reload after the catalog fix |
| `page-...15-45-36...yml` | **"Explore in 3D" tab, anonymous** — 35 requests, all 200, **0 console errors** |

Requests the 3D tab made and the server allowed: `/api/catalog`, `/api/materials`, `/api/scenes/{id}/walkthrough/spawn`, six `/files/assets-web/*.glb` meshes, twelve `/files/materials/**` textures.

## Side effect reversed

The probes registered on the real dev database again. Restored: 3 projects `owner: None`, `users: []`, `sessions: 0`.
