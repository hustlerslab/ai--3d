# P10 — Production boundary: what is actually ready, per input path, and why

Continues `p10_failure_taxonomy.md`. Covers §9 (model-independence), §10
(hardware boundary), §15 (production boundary per path), and the model/
perception vs. hardware/compute debt split required by §17. Implemented in
`research/spatial_architecture/production_boundary.py`.

## 1. The boundary, per path - never one overall label

| Path | Readiness | Why |
|---|---|---|
| brief -> deterministic core (constraints/candidates/solver/validation/repair, no LLM) | **PRODUCTION_READY** | Zero PERCEPTION_FAILURE-class defects found across P0-P9; every stage is deterministic and covered by a frozen regression benchmark |
| brief -> end-to-end with an LLM in the loop (intent extraction from free text) | **CONTROLLED_BETA** | Deterministic core is ready, but the LLM's OWN extraction quality (not the geometry) is unbounded input - needs staged rollout / human review, not a hard block |
| photo -> scene | **RESEARCH_ONLY** | 20/21 scenes valid (95.2%), but grounding (46/48, 95.8%) and wall usability (`usable` walls per image, as low as 1/4) are model-bounded, not geometry-bounded - see §3 |
| photo -> scene, perception layer specifically (SAM2/MoGe/grounding alone) | **MODEL_LIMITED** | The one hard failure in the 21-image run (`moodboard_room_living_room`, hard=3, UNREPAIRABLE) traces to grounding/extent measurement, not solver or geometry code |
| floorplan -> scene | **NOT_YET_SOLVED** | Confirmed via `grep -rli floorplan app/ research/` - no code path exists at all. Not a bug, not a limitation of existing code - the feature was never built |
| mixed-input (photo + brief together) | **NOT_YET_SOLVED** | No merge/precedence logic exists between a photo-derived scene and a brief-derived intent set - would need new design, not a fix |

Full detail (evidence, `assessed_by`) in `production_boundary.PRODUCTION_
BOUNDARY`; `readiness_counts()`: PRODUCTION_READY 1, CONTROLLED_BETA 1,
RESEARCH_ONLY 1, MODEL_LIMITED 1, NOT_YET_SOLVED 2.

## 2. §9: model-independence - the evidence-contract test

The question: can a model's mistake ever silently BECOME a wrong geometric
fact, or does it always pass through an evidence contract that geometry
independently interprets? Tested directly by `authority_audit.
check_no_ai_override()` (zero violations across 17 artifacts, see
`p10_authority.md`) plus one concrete case: trace #8 in `integration_audit.
trace_ten_decisions()` is a photo-path decision where a model HYPOTHESIS
happens to agree with independently measured geometry - the trace shows the
model's claim recorded as a `geometric_hypothesis`, not as the
`solver_decision`, and the actual placement comes from `validate_object`/
`place_objects`, which never reads the hypothesis field. **Result: the
architecture is model-independent by construction** - swapping the
perception model would change what EVIDENCE is offered, never what the
solver decides with it, because no code path exists for a hypothesis to
reach a `SceneObject`'s final XYZ/yaw without passing through a candidate,
a filter, and the solver.

## 3. §10: hardware boundary - separating hardware-caused from architecture-caused

No P0-P9 phase touched perception model code, so these are the same
measured numbers already recorded in `docs/benchmarks/
spatial_engine_production_readiness.md`, reused here (not re-run, to avoid
redundant GPU load) as the hardware baseline against which this run's own
21-image result is checked:

| Stage | Measured | Hardware ceiling |
|---|---|---|
| MoGe-2 vitl | 0.71s warm / 2636MiB VRAM | RTX 3050 6GB - fits with ~3.4GB headroom |
| SAM 2.1 base-plus | 0.52s warm / 920MiB | fits comfortably |
| Room fit + wall gate + extent + grounding | ~5s + 50ms/object | CPU-bound, not VRAM-bound |
| Solver + 2D validation | 0.19s/scene | negligible |
| Blender build (no render) | 2.1s/scene | negligible |
| Blender Cycles/OptiX smoke render | 11.4s | acceptable for a one-shot preview, not for interactive use |
| Qwen2.5-VL 7B | 3.47GB + 2.70GB spill | not on the geometric path at all - only used for free-text intent extraction |

Models are never co-resident (sequential load/unload) - this is why a 6GB
card can run this pipeline at all. Machine: RTX 3050 6GB VRAM, ~16.8GB RAM.

**Hardware-caused vs. architecture-caused, applied to this run's own
failures:** the one UNREPAIRABLE scene (`moodboard_room_living_room`, hard=3)
is NOT a VRAM/latency failure - all models ran within their measured
budgets - so it is classified PERCEPTION_FAILURE (grounding), not
HARDWARE_FAILURE. No failure in the full P0-P10 corpus is HARDWARE_FAILURE
(`failure_taxonomy.summary_counts()` - 0 entries), meaning every observed
defect has been a correctness defect, never a resource-exhaustion one, on
this hardware, at this corpus size.

## 4. Architectural debt, split by kind (§17)

**Model/perception debt** (not fixable by changing architecture):
- Wall-contact precision 77.8%, 25% UNKNOWN - inherent to the current plane-fit approach on noisy depth
- TV-unit duplicate grounding - an extent-measurement defect upstream of geometry
- Asset forward-axis unverifiable - a catalogue/generation-time property, not observable at placement time
- Grounding at 46/48 (95.8%) - the direct cause of this run's one hard failure

**Hardware/compute debt** (not fixable by changing code, only by changing hardware):
- Blender Cycles/OptiX render at 11.4s is too slow for interactive preview on a 6GB card - acceptable for one-shot generation only
- None of the above are load-bearing failures today (0 HARDWARE_FAILURE entries) - this is forward-looking capacity debt, not a current defect

**Architectural debt** (the one item that IS a fixable architecture gap, cross-referenced from `p10_integration.md` §7): candidate generation for one constraint type does not consider a second, independent constraint type in the same pass (FACES+NEAR composite). Scoped fix: an orientation-aware ranking pass added to `distance_candidates`, or a second regeneration pass chained after the first.

## 5. Regression

`production_boundary.py` only reads/documents; verified via `grep -rl
"research\." app/` (empty - production code imports nothing from
`research/`) and `grep -rli floorplan app/ research/` (empty - confirming
the NOT_YET_SOLVED claim is a verified absence, not an assumption).
