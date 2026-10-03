# P1-FRONTEND-002 — Review surface and repair visibility · verification

**2026-09-26 · Hat:** Frontend Engineer (+ Backend) · **Meshy spend: 0** · **Blender:** real, for the end-to-end review test

## Built

| Where | What |
|---|---|
| `app/review_surface.py` (new) | **Everything the review screen says, assembled once, in plain words.** Sources: the render verifier's evidence (each deterministic check as a question a person would ask, e.g. "Doors can open fully", "The picture shows the current design"; `unknown` becomes "not checked", **never "passed"**; materials and colours are "not checked" until a vision model is wired), the review queue (issue text as a sentence, plus what the person can do), the trade-offs, and the repair audit trail ("Correcting the layout — 1 of 2", or "corrected automatically (1 of 2 attempts used)"). Status is one of four: not ready / not verified / needs attention / verified |
| `GET /api/projects/{id}/review` | Typed response model (`ReviewView`); the frontend type is generated. Registered in the contract walk. The trade-offs route now shares one function with it (`tradeoff_statements`), so both say the same thing |
| `…/components/review-surface.tsx` (new) | **A dedicated studio step, "Review your design"**, between "Generate 3D Space" and "View 3D Experience". It shows the render, the live 3D scene, what was checked (icons plus words), things to look at, the repair counter, and the element inventory with its assumptions panel (P1-FRONTEND-001) |
| The four decisions | **Approve** saves an *accepted* version (P1-FRONTEND-004). **Edit** opens the 3D editor step. **Regenerate** runs a forced re-plan. **Reject** saves the design as a version labelled rejected, so **nothing is deleted** and the person is told so. All four are disabled while there is no design to decide on |
| Machine fields | `status` and `outcome` are styled as icons and words and never printed raw |

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Presents render · 3D scene · inventory · **assumptions** · validation status · detected issues | rendered test: all six are on the page; real-Blender test: after a real build and `verify`, the review carries the render and the plain checks |
| **Approve / Edit / Regenerate / Reject** all reachable | rendered test (and all four are disabled with no design) |
| **Reject does not delete work** | behavioural test with a recording `fetch`: Reject sends exactly one request, `POST /versions {accept: false, label: "Rejected design"}`, and **no DELETE**; the person is told "kept as saved version N. Nothing was deleted" |
| Repair shows the round counter | backend: a **real** injected collision → `check_scene` → Orchestrator → Repair Engine round → the review says "N of 2"; rendered: "Correcting the layout — 1 of 2" |
| **No raw error, code or internal identifier appears anywhere** | backend: every string in the payload is scanned for internal ids, UPPER_SNAKE codes, snake_case names and FAIL/PASS (the scan's own test proves it fires); frontend: the rendered text is scanned for the same, plus `Error`/`undefined`/`null`/`NaN`, **in all four statuses** |

## Mutations (8/8 caught, each restored sha1-identical)

| Mutation | Caught by |
|---|---|
| FE: the raw status enum printed instead of its sentence | DOM scan + section test |
| FE: the raw check outcome printed instead of words | DOM scan + outcome test |
| FE: the Reject button removed | "makes all four decisions reachable" |
| FE: the repair counter hidden | "shows the repair as an attempt out of two" |
| FE: reject records the design as *accepted* | "rejecting saves the design as a version and deletes nothing" |
| BE: an unknown check shown as passed | `test_verification_is_told_as_plain_checks` |
| BE: an issue told by its internal type instead of its words | the needs-attention test (payload scan) |
| BE: a failed check not counted as needing attention | **survived first**: the only needs-attention test also had an open issue, which masked it. Added `test_a_failed_check_alone_needs_attention`, which now catches it |

## Full suites

Backend `class=MOCK passed=1540 failed=1` (+7; the same pre-existing CLIP test) · `class=PRODUCTION-PATH passed=24` (+1) · generated types current · failure-injection matrix **18/18** · frontend `tsc` + `next lint` clean, **vitest 132 passed** (+9).

## Owed

- **Browser screenshots and a click-through of the four actions.** The studio needs a signed-in session, and this agent does not create accounts or enter passwords. Covered by rendered-HTML tests, a behavioural test of Approve/Reject against a recording `fetch`, and the real endpoint.
