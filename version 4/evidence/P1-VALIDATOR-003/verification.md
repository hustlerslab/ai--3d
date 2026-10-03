# P1-VALIDATOR-003 — Wire `FailureCategory` · verification

**Completed:** 2026-09-25 · **Hat:** Spatial Engineer (+ Backend) · **Meshy spend: 0**

## Before

`app/spatial/failures.py` defined the twelve-category taxonomy and the three P10 rules; a repo-wide search for importers returned **zero**. Failures were strings.

## The change — the enum is untouched

| Where | What |
|---|---|
| `app/supervisor/classify.py` (new) | `Classification(category, origin, layer, code, reason, entity_ids, evidence)`. **The P10 rules are the constructor**: `ALLOWED[origin]` fixes which categories each origin (model / architecture / hardware / asset / environment / unknown) may carry, so a relabelling cannot be built. Classifiers for each reporting layer: `from_violation`, `from_repair`, `from_compiler_warning`, `from_constraints`, `from_build_report`, `from_exception`. `is_code_defect` marks the three rows retrying cannot fix; `abstained` marks UNKNOWN |
| `app/spatial/validation.py` | `Violation.failure_category` |
| `app/spatial/repair_engine.py` | `RepairResult.failure_category` (REPAIRED / ALREADY_VALID → none; UNREPAIRABLE → candidate vocabulary; ESCALATE → repair; TIMEOUT → hardware; UPSTREAM_REQUIRED → perception) |
| `app/planning/compiler.py` output, via `scene_plan` | every `place_objects` warning emitted as a `validation.failed` event carrying its category (code defects at severity error); the solve event carries the repair's category. The compiler's return type is unchanged — its nine call sites keep working; the classifier mirrors its own format strings |
| `app/jobs/handlers/build.py` | a failed build report → `BLENDER_EXECUTION_FAILURE`; a **missing** report → `VALIDATION_FAILURE` (a check that did not run is not a pass) |
| `app/jobs/runner.py` | every `job.retrying` / `job.failed` payload carries `failure_category`, `failure_origin`, `failure_layer`, `failure_code`, `code_defect` |

## Acceptance — `tests/test_failure_classification.py` (22 passed; `pytest_verbose.txt`)

| Criterion | Evidence |
|---|---|
| **All 12 categories reachable from a real failure** | `category_coverage.json` — each produced by running the real reporting layer (below) |
| **The three P10 rules** | a model origin labelled geometry/solver/hardware, an architecture origin labelled perception, a hardware origin labelled perception → **cannot be constructed**; a Gemini call that *times out* (real `GeminiError` from the real provider over a timing-out transport) → **HARDWARE**, not perception |
| **UNKNOWN is abstention, not "no problem"** | a job failing with an unrecognised `KeyError` → `job.failed`, severity **error**, `failure_category: unknown`; `abstained` true, not a code defect |
| The enum is not changed | asserted value-for-value |

| Category | Real failure that reached it |
|---|---|
| perception | `repair_scene` on a duplicate pair the reading produced → UPSTREAM_REQUIRED; a job failing with a real `GeminiError` (invalid JSON after repair) |
| geometry | `validate_scene` on a collinear room polygon → INVALID_ROOM_POLYGON |
| representation | `validate_scene` on an object whose room does not exist → ROOM_NOT_FOUND; `place_objects` "room … not in scene" |
| constraint | a compiled constraint naming a subject the plan lacks (silently skipped by `apply_constraints_to_plan` until now) |
| candidate vocabulary | `repair_scene` on an impossible scene → UNREPAIRABLE; `place_objects` "no valid position" (12 beds in one room) |
| solver | `validate_scene` on a committed collision → COLLIDES_OBJECT |
| repair | `repair_scene` moves a table and must leave a duplicate pair → ESCALATE |
| validation | the build handler with Blender faked to write no report |
| asset | a job failing with `MeshyTaskFailed`; `place_objects` "no asset decision" |
| blender execution | the real `BlenderRunner` with no Blender configured |
| hardware | `repair_scene` out of iteration budget → TIMEOUT |
| unknown | a job failing with `KeyError` |

## Mutation tests (source restored byte-identical)

| Mutation | Result |
|---|---|
| a model origin may carry geometry/solver | **CAUGHT** |
| model errors checked before hardware markers | **CAUGHT** (timeout relabelled perception) |
| UPSTREAM_REQUIRED relabelled a repair failure | **CAUGHT** |
| runner drops the category | **CAUGHT** (4) |
| a missing build report passes | **CAUGHT** |
| "no valid position" unmapped | **CAUGHT** |

## Judgement calls, recorded

- A committed object in hard violation is **SOLVER_FAILURE** (valid positions existed and one was not chosen); the repair classification overrides when repair says the input was the problem.
- A plan count that disagrees with the approved reading is **PERCEPTION_FAILURE**: both numbers came from models.
- "No asset decision" is **ASSET_FAILURE**, not representation.
- Repair **TIMEOUT** is a compute budget → **HARDWARE_FAILURE**, per P10's "a hardware limitation is never relabelled a model failure".
