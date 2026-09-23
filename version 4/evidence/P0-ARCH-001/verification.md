# P0-ARCH-001 — Evidence

**Deliverable:** `docs/production/v4_inventory.md` (17 KB)
**Generator:** `generate_inventory.py` in this folder. Run from `aether-backend/` with its venv python; regenerates the document from the live app.

## Acceptance cross-check — grep vs introspection

The task requires: *"cross-check counts against `grep` of route decorators and the handler registry."*

| Quantity | By `grep` | By introspection | Match |
|---|---:|---:|:--:|
| Route decorators, `projects_routes.py` | 35 | — | |
| Route decorators, `routes.py` | 28 | — | |
| **Total routes** | **63** | **63** | ✅ |
| `@register(` occurrences | 13 | 13 | ✅ |
| `Settings` fields | — | 43 | ✅ |
| `CHECKPOINTS` entries | — | 17 | ✅ |

Commands:

```bash
grep -cE '^@(router|files_router)\.(get|post|put|patch|delete)' app/api/projects_routes.py   # 35
grep -cE '^@router\.(get|post|put|patch|delete)' app/api/routes.py                            # 28
grep -rc "^@register(" app/jobs/handlers/*.py | awk -F: '{s+=$2} END {print s}'               # 13
```

`app.openapi()` independently reports **64** served paths: the 63 router routes plus `GET /` declared on the app itself. The only textual difference is `{path:path}` vs `{path}` — FastAPI strips the converter in the schema.

## Acceptance criteria

| Criterion | Met | Note |
|---|---|---|
| All 63 routes listed with method, auth requirement, whether they spend money | ✅ | §1, one row each |
| All job types listed with lane and resource class | ✅ | §2 — **13**, not the 11 the task assumed |
| Every env var by name only, no values | ✅ | §3 — 43 names; only a `has_default` boolean is derived, never a value |
| Every `CHECKPOINTS` artifact path | ✅ | §4 — 17 |

## Three findings that changed the answer

**1. 13 job types, not 11.** Eleven *modules* are imported; `tour.py` and `scene_plan.py` each register two types. Counting imports is not counting registrations. `task.md` and `AUDIT_CODEBASE.md` both carry the wrong figure.

**2. `POST /api/projects/{project_id}/jobs` is a wildcard dispatcher.** `projects_routes.py:1028` passes `body.type` and `body.params` straight to the runner, so one unauthenticated route reaches **all 13** job types with caller-controlled parameters. `generate_assets` has no dedicated route — this is its only entry point. A literal-string scan cannot find it, and my first pass missed it.

**3. Zero routes are authenticated.** An earlier substring scan reported one; it had matched `require_model: bool`, a catalog filter, not a dependency. The correct test is `Depends(`/`Security(` in the signature, and the count is zero.

## One over-count I corrected before publishing

My first spend classification searched each handler's **module** source and flagged four job types. Only **two** — `generate_assets` and `generate_elements` — actually submit to Meshy. `scene_plan` merely plans generation; its own comment reads *"approval gates SPENDING, which is the generate_elements job."* `element_images` costs LLM and GPU time, not credits. Over-counting spend would have been as misleading as under-counting it.
