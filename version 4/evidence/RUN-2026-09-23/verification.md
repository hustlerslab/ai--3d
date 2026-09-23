# Run verification — 2026-09-23 · does the product still run, end to end, on today's code?

**Backend** `:8000` restarted on the working tree (`02ca264` dirty, schema v9) at 20:53 UTC; **frontend** `:3001` `next dev`. Real browser (Playwright, Chromium). **Meshy spend: 0** — the "Generate 3D space" (paid) step was not clicked.

| # | Screen | Evidence | Result |
|---|---|---|---|
| 1 | Landing / sign-in | `v4-run-01-landing.png` | renders |
| 2 | Create account → Studio | `v4-run-02-studio-after-signin.png` | first account bootstraps **admin**, adopts the 3 existing projects; list renders |
| 3 | Open "test 1" (`proj_a25a006c88`) | `v4-run-03-project-opened.png` | lands on step 6 with the Blender preview; `GET /projects/{id}`, `/scene-spec`, `/analysis`, `/build`, `/scene-reading`, `/element-images` all **200**; 0 console errors |
| 4 | Review & Refine | `v4-run-04-review-step.png` | room table + live credit balance (2,295, read only) |
| 5 | 3D viewer `/3d?scene=scene_9c8486aee2` **before fix** | `v4-run-05-3d-viewer.png` | **runtime error** — 12 × `/files/materials/**` → **401**, 14 console errors |
| 6 | 3D viewer **after fix** | `v4-run-06-3d-viewer-fixed.png` | room renders, 13 objects; 11 mesh loads + 12 texture loads **all 200**; **0** console errors (1 three.js deprecation warning) |

Server-side (backend access log, same session): `/files/materials/**` **401 × 25 before the fix, 200 × 13 after**; `/files/assets*/**` 200 × 11.

## The defect found (correction C11)

P0-SEC-005 closed `/files/*` and verified the **anonymous share-token** viewer in the browser (35 requests, all 200). The **signed-in** `/3d` route was never browser-verified. It was broken from that day: the session is an httpOnly cookie; API `fetch`es send it (`credentials: "include"`), but three.js loads textures with `crossOrigin = "anonymous"` and files with `withCredentials = false` — CORS requests, and `localhost:3001 → localhost:8000` is a different **origin** even though it is the same site — so no cookie, **401**, and the viewer showed a runtime error instead of a room. `share-token.ts` carried the wrong assumption in its comment.

**Fix (frontend only, no auth weakened):** `walkthrough3d/api/loader-credentials.ts` — `withSessionCredentials(loader)` sets `use-credentials` + `withCredentials`; applied to the material maps (`useLoader(TextureLoader, …)` instead of drei's `useTexture`, which takes no loader extension), `useGLTF(…, extendLoader)`, and the panorama `useLoader`/`preload`. The backend already allows credentials for the studio origin. Share-link visitors are unaffected (their `?k=` token still rides in the URL).

Verified three ways: browser network log (12 textures 200), backend access log (server-side), screenshot. `tsc` clean; eslint clean on the changed files; frontend unit tests **46 passed**.

## Live server checks of this session's work

- `GET /api/projects/proj_a25a006c88/provenance` → 11 objects, 9 complete, `gaps {instance: 2}` (`live_coverage_proj_a25a006c88.json` in `P1-IDENTITY-005/`)
- `GET …/provenance/obj_fed08289c6` → full chain, 6/7 hops, terminus `moodboard`
- Schema migrated to **v9** on the real DB at start-up (`generation_tasks` present)

## Not exercised

The paid generation step, the Blender build, and the panorama tour page (its loader was changed by the same mechanism proven for textures; step 7 is disabled on this project because no preview tour has been rendered).
