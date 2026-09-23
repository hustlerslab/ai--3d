# P1-IDENTITY-001…004 — Evidence: the provenance chain

**Completed 2026-09-22.** A rendered pixel can be traced back to the element that caused it, and a mesh can say what it is of.

---

## What was broken

Identity survived only as a join: `plan_key` → `ObjectPlanItem.object_key` → `.element_id`. **Nobody performed it.** So three identical bar stools looked like three unrelated objects, and the link back to the one element — and the one mesh they share — existed in principle only.

`item.element_id` was in scope at the compiler's `SceneObject(...)` constructor and simply unused.

## The four hops, now joined

| Task | Hop | Result |
|---|---|---|
| **001** | `SceneObject` schema | `element_id`, `instance_id`, both `Optional[str] = None`; `plan_key` **kept**; flat `source_intent_ids` accessor |
| **002** | compiler | 3-count item → **1 `element_id`, 3 distinct `instance_id`s**, deterministic |
| **003** | Blender manifest | three identity fields per object entry; `MANIFEST_VERSION` **1.1 → 1.2** |
| **004** | asset record | `canonical_element_id`, `source_image_id` |

## Acceptance criteria

| Criterion | Result |
|---|---|
| A pre-V4 `scene_spec.json` still loads | ✅ both fields Optional/None |
| `plan_key` retained | ✅ asserted alongside the new fields |
| Flat accessor returns `visual.source_intent_ids` | ✅ delegates, `is` the same list |
| 3-count → 1 element, 3 instances | ✅ `{cel…#0, cel…#1, cel…#2}` |
| `instance_id` deterministic | ✅ two compiles, identical sets |
| count ≠ instances **emitted, not tolerated** | ✅ warning names both numbers |
| Every manifest entry has the 3 fields | ✅ |
| Version bumped **and a reader rejects an unknown major** | ✅ — see below |
| Built scene otherwise unchanged | ✅ geometry keys identical with/without identity |
| Every generated asset carries both fields | ✅ |
| **Existing registry records load unchanged** | ✅ **69/69 real records** |
| `project_id` tenancy unchanged | ✅ |

## `manifest_version` was written since 1.0 and never read by anything

`grep -rn "manifest_version"` matched **only the writer**. A version nobody checks is a comment.

`build_scene.py` now refuses a major it does not understand, because building from a document you have misread fails silently and looks like success. Verified in a **real Blender process**:

```
manifest 1.2 -> built OK, 8 objects, 2 rooms, 9 walls, validation_ok=True
manifest 2.0 -> refused: RuntimeError: manifest_version 2.0 has major 2,
                which this build script does not understand
```

A **minor** bump is accepted — it only adds keys an older reader ignores, and refusing those would make every additive change a breaking one. An **absent** version is accepted: those are valid 1.x documents.

## Decisions worth defending

| Decision | Why |
|---|---|
| `instance_id` **derived**, not resolved from `ElementInstance` rows | design.md TDR-004: resolving them would make `app/planning` import from `app/intelligence`, crossing the boundary `app/scene/schema.py` exists to keep. Derived is also deterministic — no uuid, no clock. |
| No element → **`None`**, never an invented id | A catalog piece the planner added is not an occurrence of anything the client approved. An invented id becomes a fiction every later consumer treats as fact. |
| `canonical_element_id`, not `element_id`, on the asset | The value is the **canonical** key, so three stools share one asset. Calling it `element_id` would invite a per-occurrence id — exactly the mistake that made three stools three purchases. |
| `reading` is **keyword-only, optional** on `place_objects` | Nine call sites predate it; none had to change. |
| Silence ≠ zero occurrences | A reading that never saw an element says nothing about it. Warning there would fire on every catalog item the planner legitimately added. |

## Tests

| Suite | Result |
|---|---|
| `tests/test_element_identity.py` | **12 passed** |
| `tests/test_manifest_identity.py` | **18 passed** |
| **Full backend** | **1200 passed · 10 skipped · 30 xfailed · 0 failed** |

### Teeth by mutation

| Mutation | Caught |
|---|---|
| `instance_id` keyed on the loop index alone (collides across elements) | ✅ |
| Divergence tolerated silently | ✅ |

## Two corrections to my own work

**1. My determinism test was wrong, not the code.** It rebuilt the scene each time, and `object_id` has a random `default_factory` — so it compared two independently-created objects. The manifest *is* deterministic given a scene; the test now pins the id and says why.

**2. A pre-existing test froze `manifest_version == "1.1"`.** The task requires bumping it. Replaced with an assertion against the imported `MANIFEST_VERSION` plus a check that the **major** is still 1 — which tracks the source of truth and additionally catches an accidental breaking bump, something the literal could not distinguish.
