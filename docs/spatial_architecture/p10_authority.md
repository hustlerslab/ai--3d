# P10 — Authority: who is allowed to decide what

Continues `p10_integration.md`. The full "who created it / who may modify
it / who may invalidate it / who verifies it" audit (§3), for the 17
artifacts the brief names at minimum. Implemented in `research/
spatial_architecture/authority_audit.py`; the full table is that module's
own `AUTHORITY_MATRIX` (encoded as data, not only prose, so it can be
checked rather than only asserted).

## 1. The central property

**No row in the 17-artifact authority matrix has `ai_can_decide_final_
value=True`.** Checked by `authority_audit.check_no_ai_override()`
(returns the list of violations - empty means the property holds) and
asserted by `test_no_ai_override_of_final_geometry`. This is the concrete,
checkable form of this whole program's founding principle ("AI provides
evidence. ... The solver decides. Blender executes."), re-verified against
every artifact this phase's brief specifically named, not just the ones
earlier phases happened to already test.

## 2. Summary table (full detail in `authority_audit.AUTHORITY_MATRIX`)

| Artifact | Creator | AI's role | Can AI decide the final value? |
|---|---|---|:-:|
| object identity | `place_objects` (default) / `grounding_to_scene` (deterministic `f'obj_{case_id}'`) | none | No |
| object dimensions | `AssetDecision.dimensions` (catalogue) / `GroundingHypothesis.extent_wdh_m` (measured) | may suggest a semantic type whose catalogue dims are looked up | No |
| object footprint | derived on demand (`footprint_corners`) | none | No |
| object orientation | `place_objects` / `repair_scene` / `regenerate_after_placement` | may assert a FACES intent (a request) | No |
| room boundary | `layout_rooms` / `build_room_boundary` | may estimate a room's dimensions as evidence | No |
| wall geometry | `build_walls_and_openings` / plane-fit geometry (`app/spatial/planes.py`) | none (a VLM approach was tried and replaced - see §3) | No |
| floor | fixed constant (brief) / plane-fit scoring (photo) | none | No |
| wall contact | `constraint_evaluator._evaluate_contact` | may assert a claim (checked, not trusted) | No |
| FACES | `constraint_evaluator._evaluate_orientation` | Intent only | No |
| NEAR | `constraint_evaluator._evaluate_distance` | Intent + a numeric parameter (still just a request) | No |
| BETWEEN | `constraint_evaluator._evaluate_between` | Intent only | No |
| support | `app.planning.compiler._pick_support` | none | No |
| clearance | `clearance_engine` | none | No |
| collision | `validate_object` (the ONE hard-collision authority everywhere in this program) | none | No |
| final XYZ | `place_objects` / `repair_scene` / `regenerate_after_placement` | none - not even a suggested coordinate | No |
| final yaw | same three functions | none | No |
| final intent satisfaction | `constraint_evaluator.evaluate_all` (strictly read-only) | none - a model may only be the SOURCE of the Intent being checked | No |

## 3. Why "AI's role: none" for wall geometry is itself evidence, not an assumption

Wall contact was ONCE attempted via a VLM, in six formulations, and measured
at 78/78 refusals to abstain with a constant-function wall gate
(`failure_taxonomy.HISTORICAL_FAILURES["vlm_wall_contact_refusal"]`,
`app/spatial/planes.py`'s own module docstring). It was replaced by
deterministic plane-fit geometry, which is what every wall-geometry row
above actually describes. The "AI's role: none" entries in this table are
therefore not merely a design choice stated in the abstract - they are the
documented outcome of a real, measured experiment that tried the
alternative and rejected it.

## 4. Regression

`authority_audit.py` reads, never modifies, the functions it documents -
verified by the full P0-P9 regression gate (`decisions.md`'s P10 entry
§12): every function named as an "authority" in this matrix still produces
byte-identical output to its own frozen baseline after this phase.
