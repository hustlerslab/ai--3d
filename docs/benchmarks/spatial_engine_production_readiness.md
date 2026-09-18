# Allure Spatial Engine — Production Readiness Review

**Classification: RED — research prototype**, with three subsystems that are
individually green, and a bridge between them now built and measured (this was
the exact blocker this review named; it is superseded by
`docs/benchmarks/spatial_architecture_report.md`, which this section
summarizes — read that report for the full measurement).

The design-from-brief path (brief → plan → deterministic solver → 2D validation →
Blender → read-back) is production code, deterministic, and measured clean: 12 of
12 frozen scenes valid, 547 of 559 objects placed, 12 of 12 built in Blender with
zero errors and centimetre-level read-back agreement. The perception path (photo
→ metric geometry → floor → walls → grounding) is research code that reaches an
honest, abstaining primitive — wall contact at **77.8% precision, 7.7%
false-wall, 25% UNKNOWN** on the frozen 48-case benchmark — against a target of
90% precision. A research-only bridge (`research/spatial_architecture/`) now
converts that grounding output into real `Scene` objects and runs them through
the **unmodified** production solver, validator, and Blender build. After a
dedicated P1 collision-solving phase (`docs/spatial_architecture/collision.md`)
added a deterministic DFS-family placement resolver, **20 of 21 photo-derived
scenes (95.2%, up from an initial 76.2%) are fully valid, all 46 grounded
objects are placed, and all 20 attempted Blender builds succeed with zero
errors.** This is the first measured end-to-end number for the photo path. It
is still research code — nothing in `app/` imports it, and no job handler or
API route produces a scene from a photo for a real user. 3D OBB collision (2D
footprint collision now IS solved, see P1) and a general repair loop remain
not built beyond the P1 resolver and one narrow, measured-effective rule.

**Date:** 2026-09-16 · Test status: **377 passed, 7 skipped, 30 xfailed**
(371 at this section's last revision + 6 new P1 collision-resolver tests; no
regression). Production code changed by this program: **none**. Models
added: **none**. Dependencies added: **none**.

Claims are tagged **[M] measured**, **[I] inferred**, **[Q] qualitative**,
**[N] not tested**.

---

## 1. Architecture as it stands

```
PHOTO PATH (research; bridge now built + measured)  BRIEF PATH (production, measured)

SAM 2 mask + MoGe-2 metric points  [M]              brief -> MockProvider/VLM plan
   |                                                    |
floor hypothesis, gravity-oriented, UNKNOWN  [M]     compile_scene (rooms, walls, openings)
   |                                                    |
walls: RANSAC + Manhattan (frozen fit_room)             place_objects: candidate poses,
   |                                                    ranked; solver owns XYZ + yaw  [M]
wall-quality gate: enclosure >= 0.80,                   |
   floor_band <= 0.75, else UNKNOWN  [M]             validate_scene: SAT footprint
   |                                                    collision, walls, bounds, doors  [M]
catalogue-grounded extent: registry dims +              |
   orientation hypotheses along wall normal  [M]     build_manifest -> to_blender_xyz  [M]
   |                                                    |
ObjectGrounding: footprint, position, depth,         Blender headless build  [M]
   orientation candidates, confidence  [M]              |
   |                                                 validate_scene.py: bbox read back
GroundingHypothesis (FACT/HYPOTHESIS/DECISION)          through matrix_world  [M]
   |  research/spatial_architecture/grounding_contract.py
grounding_to_scene: room boundary, walls, yaw,
   asset selection, Scene + SpatialRelation  [M]
   research/spatial_architecture/scene_from_photo.py
   |
   >--- feeds the SAME validate_scene / build_manifest / BlenderRunner
        shown on the right (unmodified) --- 95.2% scene success  [M]
   |
collision_solver.resolve_collisions: deterministic DFS-family placement
   pass BEFORE validate_scene (P1, closed 10->2 COLLIDES_OBJECT)  [M]
   research/spatial_architecture/collision_solver.py
   |
   X  still research-only: no `app/` import, no job handler, no API route
```

Principle held throughout: models perceive, geometry decides, constraints
validate, Blender executes, validation verifies. No model emits XYZ, yaw, scale,
contact, support or placement anywhere in either path. **[M by inspection]**

## 2. All phases

| Phase | Subsystem | Result | Verdict |
|---|---|---|---|
| 1c–1h | VLM relation extraction | false-wall 14.1% best, 0/78 abstentions, non-deterministic | FAIL — VLM removed from the geometric path |
| 1 | relative depth + RANSAC | false-wall 61.5%, AUC 0.55 | FAIL |
| 2 | MoGe-2 metric geometry | Manhattan 17.7° → 3.7°, AUC 0.72, false-wall 24.3% | geometry fixed; decision not |
| 3 | SAM 2 grounding | false-wall 21.6%; positives collapse to 18.2% | PARTIAL — visible-surface statistic exposed |
| 4 | rear extent from visible points | false-wall 37.8% — rear extent unobservable | FAIL, diagnostic |
| 5 | manual amodal oracle ceiling | 51.3% bal. acc.; contaminant walls identified | LOW CEILING — wall set, not perception |
| 6 | wall quality + abstention | **false-wall 21.6% → 6.1%**, 4/48 UNKNOWN, AUC 0.84 | PARTIAL — frozen |
| 7 | catalogue-grounded extent | **pos. recall 9.1% → 70%**, precision 70%, F1 70% | PARTIAL |
| 8 | floor hypothesis | countertop-as-floor 2/2 → 0/2 by rejection; 4/21 UNKNOWN | PARTIAL — first "fix" retracted |
| 9 | object grounding | 46/48 grounded, 95.7% inside room, deterministic | PARTIAL — no-wall fallback weak |
| 10 | asset normalisation audit | 58/58 accepted; 8 mount-record warnings | PASS |
| 11–12 | solver + 2D validation (audit) | 12/12 valid, 0 hard violations, deterministic | PASS on what exists |
| 13 | Blender + read-back | 12/12 built, 0 errors, XY p95 0.015 m | PASS |
| 14 | repair loop | **NOT BUILT** as a general system — one narrow collision rule exists (see below), 4/7 cleared | BLOCKED (general case) |
| 15 | architecture decision (Candidate A vs. B vs. C) | 6 papers read (Holodeck, RoomCraft, HSM, DirectLayout, 2 scene-graph works); extend `Scene`/`SpatialGraph`, not replace | PASS — see `spatial_architecture/architecture_decision.md` |
| 16 | perception → Scene bridge + integration benchmark | 21/21 images build a `Scene`; **20/21 (95.2%) scene success** (up from 76.2% pre-P1); 46/46 objects placed; 20/20 Blender builds ok | PARTIAL — see `docs/benchmarks/spatial_architecture_report.md` |
| P1 | multi-object collision solving | deterministic DFS-family resolver; `COLLIDES_OBJECT` 10→2, `COLLIDES_WALL` 6→1; 1 remaining case = duplicate perception-level grounding, out of scope | PARTIAL PASS — see `docs/spatial_architecture/collision.md` |

## 3. Frozen baselines

| Benchmark | Fixture | Frozen result |
|---|---|---|
| Wall contact | 48 cases / 21 images (32 generated neg., 11 historical pos., 5 historical neg.) | Phase 6 permissive: 1/31/2/10, 4 UNKNOWN |
| Wall contact, object side | same | Phase 7 primary: 7/25/3/3, 10 UNKNOWN |
| Wall contact, full pipeline | same | Phase 9: **7/24/2/3, 12 UNKNOWN** |
| Floor | 21 images | 17 decided, 4 UNKNOWN, countertop 0/2 |
| Scene validity | 12 briefs | 12/12 valid, 547/559 placed |
| Blender | 12 briefs | 12/12 built, 547 read back |

Every harness re-runs its predecessor's control first and aborts on drift; all
controls reproduced exactly at every run in this program. **[M]**

## 4. Final metrics against §41 targets

| Target | Required | Measured | Status |
|---|---|---|:--:|
| Wall quality: false-wall < 10% at useful coverage | <10% | **7.7%** decided, 75% coverage (Phase 9 pipeline) | ✓ |
| Floor: 0% countertop-as-floor on frozen benchmark | 0% | **0/2** — by rejection, not replacement | ✓ (partial) |
| Object grounding: high-confidence placement on catalogue assets | — | wall-oriented 31/46 cover 95% of evidence; fallback 15/46 cover 24% | ✗ partial |
| Support ≥ 95% | ≥95% | solver: asserted by construction, not verified **[N]**; photo path: 78% contact-consistent | ✗ |
| Collision: near-zero hard collisions on solved scenes | ≈0 | **0** in 547 objects (2D) | ✓ (2D only) |
| Room bounds: near-zero violations | ≈0 | **0** (solver); 95.7% inside (photo path) | ✓ |
| Critical wall contact ≥ 90% precision on decided cases | ≥90% | **77.8%** (7 of 9) | ✗ |
| UNKNOWN allowed and measurable | yes | 25% of wall-contact cases, every one with a reason | ✓ |
| End-to-end ≥ 85% scene-level geometric validity | ≥85% | brief path **100%** valid / 58% fully placed; photo path **not measurable — not integrated** | ✓ / ✗ |

## 5. End-to-end scene success

**Definition used:** zero hard violations from `validate_scene` AND every
requested object placed AND Blender builds with zero errors. Stylistic warnings
do not fail it.

| Path | Scenes | Valid | Fully placed | Blender ok | **Success** |
|---|--:|--:|--:|--:|--:|
| Brief → Blender (production) | 12 | 12 | 7 | 12 | **7 / 12 (58%)** — 5 shortfalls are upstream room parsing / no-surface skips |
| Photo → Blender (research bridge, `research/spatial_architecture/`) | 21 | 20 | 21 (46/46 objects) | 20 | **20 / 21 (95.2%)**, up from 16/21 (76.2%) pre-P1 — the 1 remaining shortfall is a duplicate perception-level grounding (two `tv_unit` detections of one physical object), not a collision-solving failure; full breakdown in `spatial_architecture_report.md` §7a and `docs/spatial_architecture/collision.md` §12 |

## 6. Failure distribution (photo path, Phase 9 pipeline, 48 cases) **[M]**

| Category | n | Notes |
|---|--:|---|
| Correct decisions | 31 | 7 TP + 24 TN |
| FLOOR_FAILURE → UNKNOWN | 2 | s07 stools: fitter floor implausible, no replacement |
| WALL_FAILURE → UNKNOWN | 4 | s11: no wall fitted |
| PERCEPTION_FAILURE → UNKNOWN | 4 | mask span > 2× any dimension |
| OBJECT_EXTENT_FAILURE | 3 | bed (asset/photo mismatch), vanity (mirror), s15 table |
| GROUNDING_FAILURE (label-borderline) | 1 | `s16.chair.0`, 1 mm from a real wall |
| FLOOR_FAILURE (decided wrong) | 2 | s13 armchair FP, kitchen counter FN |
| AMBIGUITY | 1 | sectional sofa, borderline |

## 7. UNKNOWN distribution **[M]**

Wall contact: 12 / 48 (25%). Floor: 4 / 21 images. Grounding: 2 / 48.
Every abstention carries a stated reason; none is a silent fallback. Decision
confidence is **not calibrated** and is not used as an abstention threshold.

## 8–10. Latency, VRAM, CPU RAM (RTX 3050 6 GB, 16.8 GB RAM) **[M]**

| Stage | Latency | Peak VRAM | Notes |
|---|--:|--:|---|
| MoGe-2 vitl (metric geometry) | 0.71 s warm | 2636 MiB | bit-deterministic |
| SAM 2.1 base-plus (segmentation) | 0.52 s warm | 920 MiB | run alone, unloaded before MoGe |
| Room fit + wall gate + extent + grounding | ~5 s + 50 ms/object | none (CPU) | floor scorer 4.8 s/image is the cost |
| Solver + 2D validation | 0.19 s / scene | none | |
| Blender build (no render) | 2.1 s / scene | — | |
| Blender smoke render, Cycles/OptiX | 11.4 s | GPU | |
| Qwen2.5-VL 7B | 3.47 GB + 2.70 GB spill | — | **not on the geometric path** |

Models are never co-resident; sequential load/unload is the measured practice.

## 11. Licensing **[M]**

MoGe-2 MIT · SAM 2.1 Apache-2.0 · Depth Anything V2 Small Apache-2.0 (control
only) · Blender GPL (executable, subprocess) · assets CC0-1.0 / meshy-commercial.
UniDepthV2 excluded (CC BY-NC). No non-commercial model is on any path.

## 12. Dependencies

Added by this program: none. Earlier phases added `moge`, `utils3d_moge`,
`opencv-python-headless`, `scipy` with `--no-deps`; torch 2.14.0+cu126 unchanged.

## 13. Test status

`pytest -q`: **367 passed, 7 skipped, 30 xfailed**. New:
`tests/test_spatial_engine_research.py` — 12 synthetic, CPU-only checks on sign
conventions, the wall gate, floor selection (countertop vs floor, implausible
depth → UNKNOWN), catalogue extent, grounding footprints and UNKNOWN paths. One
of them caught the Phase 8 orientation error before it shipped.

## 14. Blender validation

Read back and verified: object position (XY p95 0.015 m), floor contact (z = 0),
dimensions (91.8% within 25%), room bounds (0 errors), scene completeness
(floor/ceiling/light per room). Not read back: wall contact, mesh-level
collision, rotation beyond axis swap, render-based comparison. **[M / N]**

## 15. Remaining limitations

1. **Photo-to-scene bridge exists but is research-only.**
   `research/spatial_architecture/` converts `ObjectGrounding` to real `Scene`
   objects and, after the P1 collision-solving phase
   (`docs/spatial_architecture/collision.md`), measures **95.2% scene
   success** (up from an initial 76.2% — dense-scene collisions are now
   mostly resolved by a deterministic DFS-family placement pass). Nothing in
   `app/` imports it, so no user-facing path produces a scene from a photo yet.
   The one remaining failure is a duplicate perception-level object detection
   (two groundings of one physical TV unit), not a collision-architecture gap.
2. **Wall-contact precision 77.8%** vs 90%: residuals are one asset/photo
   mismatch (bed platform vs mattress), one mirror scene, one label-borderline
   chair, one borderline sectional.
3. **Floor recovery** where the fitter fails is rejection-only; s07-type shots
   need a room-height prior or a second view.
4. **No-wall grounding fallback** covers 24% of its evidence; needs a
   non-wall orientation source.
5. **Through-glass depth** contaminates every MoGe consumer until glazing is
   masked.
6. **Validation is 2D**, and a flat `Wall`/`Room.boundary` schema cannot
   represent a photo-reconstructed wall with real tilt (measured: an 11° tilt
   on one benchmark wall, within Phase 6's own 25° tolerance, causes the
   largest two `COLLIDES_WALL` residuals — a genuine representation loss, not
   a bug; see `spatial_architecture_report.md` Finding 2). No 3D OBB
   collision, no clearance rules beyond doors, either.
7. **No general repair loop.** One narrow rule (nudge the lower-confidence
   object 0.3 m on a `COLLIDES_OBJECT`, re-validate once) exists in the
   research bridge and clears 4 of 7 attempts; nothing more general is built,
   and job-level retry is the only repair mechanism in production.
8. **Decision confidence uncalibrated.**
9. **Asset records:** 8 mount mismatches; forward axis unverifiable from mesh.
10. **Benchmark scope:** 48 cases / 21 images / 12 briefs. No claim beyond it.

## 16. Production recommendation

**RED overall.** The brief-driven design path is fit for a controlled beta on its
own — deterministic, validated in plan, executed and read back in Blender — and
would be YELLOW if judged alone. The photograph-driven spatial engine is a
research prototype with an honest abstaining primitive and is not connected to
anything a user can see. Do not describe the system as production-ready.

**Exact next blocker (superseded twice now — first the bridge, then the
collision gap; both are built/closed and measured; this is the current
blocker):** the research bridge (`research/spatial_architecture/`) is still
not wired into anything a user or job handler can reach — that remains
**P8 (production integration)** in the wider `docs/spatial_architecture/`
program, and is explicitly gated behind P2-P7 by that program's own phase
ordering, not skippable. Two secondary, smaller items are open in parallel:
whether `Wall`/`Room.boundary` should gain a tilt field, or photo-
reconstructed walls beyond a small tilt should report UNKNOWN instead of
being silently flattened (**P5**, `docs/spatial_architecture/`, not yet
started); and whether Phase 9's `ground_object` should detect duplicate
groundings of one physical object (newly surfaced by P1, not yet scoped into
a numbered phase). Collision-solving itself (P1) is no longer the blocker —
see `docs/spatial_architecture/decisions.md`.
