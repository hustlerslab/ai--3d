# Phase 9 — Element-First (P1-ELEM-001 · 002 · 003 · 004) · verification

**Completed:** 2026-09-25 · **Meshy spend: 0** · `tests/test_element_first.py` **19 passed** (`pytest_verbose.txt`)

## P1-ELEM-001 — `MoodboardOccurrence` (Backend, + GenAI)

`app/intelligence/schema.py`: `MoodboardOccurrence` — `frame: Literal["MOODBOARD"]`, frozen, `extra="forbid"`; bbox must be fractions in [0, 1] with x0 < x1, y0 < y1; `crop_px` whole non-negative pixels. **Derived, never authored**: `from_element()` / `moodboard_occurrences(reading)` are the only constructors the pipeline uses (TDR-015: one source, two views). `scene_plan` writes `planning/moodboard_occurrences.json` beside the reading every time the reading is written (with the reading's version); registered in `CHECKPOINTS`.

| Criterion | Evidence |
|---|---|
| `frame` is always MOODBOARD; a metric value fails | `frame="ROOM"` refused; a bbox of metres `(0.5, 0.2, 2.4, 1.1)` refused; `position_m` / `dimensions_m` refused (the fields do not exist on it); an inverted box and a fractional pixel count refused |
| `crop_px` = native size before upscaling | real `write_element_crops` on an 800×600 render: `crop_px` equals the native padded box; the saved PNG is a different (enlarged) size |
| Derived, no second source of truth | equal field-for-field to its `SceneElement`; frozen (cannot be edited); an element with no box has no occurrence |
| Artifact in `CHECKPOINTS` | `moodboard_occurrences → planning/moodboard_occurrences.json`; written by the real `_read_scene` (`sample_moodboard_occurrences.json`) |

## P1-ELEM-002 — the `MOODBOARD` frame (Spatial)

`FrameId.MOODBOARD` + registry row: `metric=False`, `parent=None`, units `fraction`, transform source "none — a generated image has no camera pose". **No edge in `frame_graph.py`**, and `Rigid3` now refuses to be constructed on **any non-metric frame** — so no future edge can be added by accident. The docstring's "EIGHT FRAMES" (the enum had seven) is now true and lists all eight.

| Criterion | Evidence |
|---|---|
| `FRAME_REGISTRY[MOODBOARD].metric is False` | asserted, with `parent None` |
| No `Rigid3` connects MOODBOARD to ROOM | construction MOODBOARD↔ROOM/CAMERA/OBJECT in both directions raises `FrameMismatchError`; `describe_graph()` and `frame_graph.py` never name it; existing metric edges unaffected |
| Docstring/enum count corrected | 8 members; the docstring names all 8 |

## P1-ELEM-003 — `"floor_plan"` means one thing (Spatial, + Backend)

The relation-frame name is now **`room_plan`** (ROOM projected to XZ) in `relation_model.Frame`, `SpatialRelation.frame`, `scene_graph`, `clearance_engine`, `scene_serialization`. `InputKind.floor_plan` (the uploaded document) is untouched. `coordinate_frames.relation_frame()` maps the legacy spelling on load.

| Criterion | Evidence |
|---|---|
| The two concepts no longer share a string | both frame literals ∩ `InputKind` values = ∅ |
| No code compares them | a source scan finds `"floor_plan"` literals only in `projects/schema.py` (the document kind) and the legacy map |
| Pre-rename relations still load | a `SpatialRelation`, a bridge dict and a serialized `GeometricRelation` saying `"floor_plan"` all load as `room_plan`; an unknown frame is still refused |

Two existing tests pinned the old string; one now asserts `room_plan`, the other asserts that the legacy spelling it feeds loads as `room_plan`.

## P1-ELEM-004 — "keep this furniture" (Product, + Backend, Frontend)

A **structured control**, not brief phrasing. `SceneElement.client_owned` → `ElementDefinition.client_owned` → `ObjectPlanItem.client_owned` → `SceneObject.client_owned` → manifest `client_owned`; `ElementInventory.yours`. `PATCH /scene-reading` takes `keep: {element_id: bool}`; keeping implies approval (it is in the room by the client's word). `approved_for_generation` **never** offers a kept piece, whatever its approval. `carry_client_owned()` carries the flag across a re-read by canonical key (safe: it can only reduce spend). Frontend: review cards get **"Mine — keep it"** (Skip disabled while kept) and a **"Yours"** badge; the footer counts "N yours, kept"; the 3D viewer's selected-object panel shows **"Yours"**; `reviewSceneReading` sends the `keep` map.

| Criterion | Evidence (one real flow: plan → review via the API → generate → forced re-plan) |
|---|---|
| **A marked piece appears in the final scene** | the scene spec after re-planning holds the sofa with `client_owned: true` |
| **It consumes zero generations** | the fake vendor received **2** submissions for the 2 approved pieces and **none** for the kept sofa; no `asset.requested` event names it |
| **Labelled "yours" in the inventory and the viewer** | inventory `yours` counted; manifest carries `client_owned`; frontend badges (typecheck + lint clean) |
| **Provenance resolves it to the image showing it** | `resolve()` on the placed sofa ends at `moodboard`, with the crop on the chain |
| Survives a re-read | the forced re-read moved every box (new row ids); the sofa's new row inherited `client_owned`, and its definition too |

## Found while building it — a real defect in P1-ORCHESTRATOR-001, fixed

The policy's RE_READ dispatched `scene_plan` with `{"force": True}` — which **re-plans but does not re-read the moodboard** (`scene_plan` re-reads only on `force_read`). A "re-read" directive would have re-run the same wrong reading. Fixed (`force_read: True`), asserted in `test_orchestrator.py`, and mutation-checked.

## Mutation tests (source restored byte-identical)

| Mutation | Result |
|---|---|
| frame not pinned · metric bbox accepted · metric fields allowed | **3/3 caught** |
| Rigid3 accepts non-metric frames · moodboard marked metric | **2/2 caught** |
| legacy `floor_plan` not read | **caught** |
| kept piece generated · keep not carried across re-read · compiler drops the flag | **3/3 caught** |
| RE_READ does not re-read | **caught** |

## Owed

- **Browser check of the review toggle and badges** — typecheck, lint and the 46 frontend unit tests pass, but the control has not been clicked in a running app yet. To be done with the P1-FRONTEND tasks, which need the dev server anyway.
- The Phase 9 gate's "golden identity benchmark" rows are P1-IDENTITY-006 (met earlier).
