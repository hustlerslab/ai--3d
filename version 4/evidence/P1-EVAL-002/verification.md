# P1-EVAL-002 — Render-mismatch detection test · verification

**2026-09-26 · Hat:** QA Engineer (+ 3D Engineer) · **Blender:** 5.2.1 LTS at `D:/Blender/blender.exe` (real) · **Meshy spend: 0**

## Objective

Prove `app/verification/render_verifier.py` (P1-VALIDATOR-001) **detects** a discrepancy rather than assuming it would — five deliberate breakages, one per check class.

## Built (one genuine addition, beyond just tests)

Writing the "removed object → detected as missing" case exposed a real gap: none of design.md §16's 13 checks compare the **live committed `Scene`** against what a render actually shows — they all compare the build's own manifest against its own output, so an object removed or moved by a *later* patch, without a rebuild, was invisible to every existing check. Added:

| Where | What |
|---|---|
| `app/verification/render_verifier.py::_render_matches_committed_scene()` | Compares `build_report["objects"]` (Blender's own record of what it placed at build time) against the live `Scene`'s object ids. Any object present in one but not the other is **drift** |
| `VerificationEvidence.scene_checks["render_matches_committed_scene"]` | New scene-level check (documented extension, same category as `scene_checks` itself — design.md's contract is illustrative, not a closed schema) |
| `VerificationEvidence.summary["drifted_object_ids"]` | Which objects drifted, for evidence |

This also closes most of **P1-QA-003 row 12**'s detection gap ("render mismatch, object moved post-capture") — the remaining piece there is wiring the Supervisor's Validator to read `render_verification.json` so it reaches `HUMAN_REVIEW` through the real pipeline, tracked separately, not done here.

## The five acceptance criteria, each a real, deliberate breakage

| # | Criterion | Test | Result |
|---|---|---|---|
| 1 | Removing an object → detected as missing | `test_removed_object_is_detected_as_missing` | build report lists the object; live scene doesn't → `render_matches_committed_scene` = `fail`, object id in `drifted_object_ids` |
| 2 | Moving an object into a wall → detected as intersecting | `test_object_moved_into_a_wall_is_detected_as_intersecting` | a real `Wall` at x=5, a sofa pushed to x=4.9 (half its 2m width crosses) → `app/spatial/validation.py`'s `COLLIDES_WALL` → `severe_intersections` = `fail` |
| 3 | Rotating an object 90° → detected as mis-oriented | `test_rotated_object_is_detected_as_mis_oriented` | plan says face −Z, object actually faces +X (90°) → `orientation` = `fail` |
| 4 | Hiding an object behind another → detected as occluded (ray-cast) | `test_hidden_object_is_detected_as_occluded_by_real_ray_cast` | **real Blender**: a wall built directly between a real camera and a real cube; `check_visibility.py`'s actual ray-cast (not a model) reports `visible=0, in_frame>0` → `major_objects_visible` = `fail`, `visibility` = `"occluded"` |
| 5 | Disabling a checker yields `unknown`, never a pass | `test_disabling_the_visibility_checker_yields_unknown_not_pass`, `test_disabling_the_entrance_point_yields_unknown_circulation_not_pass` | no `visibility_detail` supplied → `major_objects_visible` = `"unknown"` (not `"pass"`); no `entrance_xz` → `circulation` = `"unknown"` |

Two supporting tests confirm the negative: an unchanged scene is **not** flagged as drifted, and a correctly-oriented object **passes** — so the detectors aren't just permanently tripped.

**Mutation (1):** disabled the drift comparison (returned `"pass", []` unconditionally) — `sha1` before `0015da78...`, restored, `sha1` after `0015da78...` (identical) → `test_removed_object_is_detected_as_missing` failed as expected; the other 13 tests in the two files were unaffected (confirming the mutation was scoped to exactly the one check it should have broken).

## Full suite after the change

`class=PRODUCTION-PATH passed=19 failed=0` (up from 18 — the 1 new real-Blender occlusion test) · `class=MOCK passed=1503 failed=1` (same pre-existing CLIP failure, unrelated; +7 new pure-function tests) — see `pytest_verbose.txt`.

**Outcome:** the verification claim from P1-VALIDATOR-001 is demonstrated against deliberate breakage per check class, not merely asserted; and the render-vs-committed-scene drift check now exists for any future caller (including the still-owed row 12 wiring).
