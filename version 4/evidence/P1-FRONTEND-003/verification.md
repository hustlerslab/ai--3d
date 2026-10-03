# P1-FRONTEND-003 — Typed API contracts and generated client types · verification

**2026-09-26 · Hat:** Backend Engineer (+ Frontend) · **Meshy spend: 0** · no network (Poly Haven replaced by local files in tests)

## Built

| Where | What |
|---|---|
| `app/api/contracts.py` (new) | A response model for every route. `Envelope[T]` for `{success, data}` reads, `Written` for flat `{success, ...}` writes; the envelope itself is **unchanged**. Existing domain models (`Scene`, `Job`, `JobEvent`, `ProjectRecord`, `InputRecord`, `AssetRecord`, `MaterialRecord`, `CatalogItem`, `ProvenanceChain`, `TourPath`, `PositionCheck`, `SavedView`) are reused rather than re-declared; `dict[str, Any]` only where a route passes a JSON artifact from disk through verbatim. `ContractRoute` forces `exclude_unset` on every route (see "Found" below) |
| `app/api/routes.py`, `app/api/projects_routes.py`, `app/auth/routes.py`, `app/main.py` | `response_model=` on all 78 JSON routes; all three routers use `route_class=ContractRoute`. The 4 `/files/*` routes stream bytes and are the only routes without a model (`BINARY_ROUTES`) |
| `scripts/gen_api_types.py` (new) | Generates `aether-frontend/src/generated/api-types.ts` (1,490 lines) from the backend's own OpenAPI document: an interface per schema, `API_ENDPOINTS`, and `ApiResponses` keyed by `"METHOD /path"`. No new npm dependency. `--check` exits 1 when stale |
| `tests/test_api_contract.py` (new, 6 tests) | Route lint, `exclude_unset` lint and behaviour, snapshot (`tests/contracts/api_contract.json`), generated-types freshness, and a walk that **calls every endpoint** |
| `aether-frontend/src/generated/api-contract.test.ts` (new, 51 tests) | Every exported API function in the four modules that talk to this backend names the endpoint it means to call; the recorded request must match it exactly, and it must exist in the generated `API_ENDPOINTS` |
| `aether-frontend/vitest.config.ts` | Adds the `@/` alias (tsconfig resolves it for Next only; vitest could not load `auth-api.ts`) |
| `.github/workflows/ci.yml` | Backend: `gen_api_types.py --check` step. Frontend: **`npm test` added — the frontend CI job had never run vitest at all** |

`walkthrough-api.ts` is out of scope: it talks to a separate service (`NEXT_PUBLIC_WALKTHROUGH_API_URL`, port 4000, `/api/walkthroughs/*`), which is not in this backend's OpenAPI.

## How "the wire shape did not change" was proved, not assumed

Attaching a response model makes FastAPI validate and re-serialise every response, which can silently drop keys, invent keys, or reformat values. Three independent checks:

1. **Capture.** A throwaway pytest plugin recorded every `TestClient` response (method, path, status, full body) across the full MOCK suite and the PRODUCTION-PATH suite: **1,876 responses**.
2. **Round-trip.** Before touching any route, every captured 2xx body was validated through its new model and dumped back: **1,493 responses across 51 routes, 0 mismatches**, and 0 undeclared keys once the tour package's fields were added.
3. **Before/after diff.** The models were attached and both suites re-run with capture. Shapes compared per (method, id-normalised path, status):

| Run | Responses | Shapes only-before | Shapes only-after |
|---|---|---|---|
| first attempt (no `exclude_unset`) | 1,876 | 12 | 12 |
| with `ContractRoute` | 1,876 | **0** | **0** |

## Found

- **Attaching models without `exclude_unset` changes the contract, and the 1,528-test suite did not notice.** `/credits` grew `"balance": null` and the tour package a dozen `null` keys that the routes never returned. Caught only by the before/after capture. Fixed once, at the router level (`ContractRoute`), and now pinned twice: a lint that every route uses it, and a behavioural test that `/credits` has no `balance` key.
- **28 of 82 operations never returned a success response anywhere in the existing suite.** Most `/api/scenes/*`, asset and material routes were exercised only by the auth-denial matrix. The contract walk now calls all 82.
- **"Does the backend serve this method + path?" would not have caught the bug this task was written for.** The historic `reviewElementImages` bug turned a PATCH into a POST on `/element-images`, and both routes exist. So the frontend test pins each function's intended endpoint, not mere membership. Mutation-proven below.
- **`GET /projects/{id}/tour` returns whatever `tour.json` holds:** the preview job's full package, or a minimal `{nodes}` / `{tour: {nodes}}` written by test fixtures. Modelled as a passthrough with every field optional; not redesigned here.
- **Material map paths are data-dir relative** (`materials/<id>/…`), and the viewer prefixes `/files/`. I checked this before "fixing" my test. It is not a bug.

## The endpoint walk (`endpoint_walk_report.json`)

82 operations called once each on a real app (MOCK provider, signed-in admin, golden fixture project, seed scene, Poly Haven faked with local files so the **real** ingest pipeline runs). Every 2xx body validates against its model with no undeclared payload key; every non-2xx body is the error envelope. Non-2xx statuses are pinned and explained in `EXPECTED`:

| Endpoint | Status | Why |
|---|---|---|
| `POST …/elements/generate` | 409 | the paid step refuses without a Meshy key |
| `POST …/build` | 503 | no Blender in the MOCK class |
| `POST …/preview`, `…/walkthrough`, `…/film` | 409 | `BUILD_REQUIRED`, checked before Blender |
| `GET …/build`, `GET …/tour` | 404 | nothing built yet |
| `GET /files/assets-web/{path}` | 404 | a light model gets no browser copy; the success path (bytes) is fetched by `test_file_authorization.py` |

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Every route has a response model; a lint test fails on a bare `dict` | `test_every_json_route_declares_a_named_response_model` |
| CI fails if generated types differ from committed ones | `gen_api_types.py --check` step in `ci.yml` + `test_generated_frontend_types_are_up_to_date` |
| Changing an endpoint's method or shape fails a test | snapshot + walk + frontend contract test; mutations 2–5 below |
| Envelope shape unchanged | 1,876-response before/after diff: 0 differences |

## Mutations (5/5 caught, each restored sha1-identical)

| # | Mutation | Caught by |
|---|---|---|
| 1 | `exclude_unset` removed from `ContractRoute` | route lint + `/credits` behaviour test |
| 2 | a response field renamed (`Credits.available`) | snapshot, generated-types, walk, behaviour |
| 3 | a route's method changed (`PATCH` → `POST` on `/element-images`) | snapshot, generated-types, walk |
| 4 | generated TS edited by hand | generated-types freshness |
| 5 | **the historic bug reintroduced**: `{ method: "PATCH", ...json(...) }` in `reviewElementImages` | frontend: *"reviewElementImages sent POST /api/projects/p1/element-images, not PATCH /api/projects/{project_id}/element-images"* |

## Full suites

Backend `class=MOCK passed=1513 failed=1` (+6; the same pre-existing CLIP test) · `class=PRODUCTION-PATH passed=21 failed=0` · frontend `tsc` clean, `next lint` clean, **vitest 101 passed** (was 50).

## Owed (not claimed)

- `src/features/studio/types.ts` is still hand-written. The generated types exist, are enforced, and guard every method + path. Moving the studio's own DTO imports onto them is the follow-up, and task.md's rollback names "keep hand-written types" as acceptable.
- Domain-model fields that have defaults come out optional (`?`) in the generated TS. That is pydantic's schema for fields with defaults: safe, but looser than the wire, which always carries them.
- The CI changes are local; there has been no GitHub run.
