# P0-QA-003 — Evidence: runtime and accuracy baseline

**Completed 2026-09-21.** "We improved placement accuracy" is now provable instead of impressionistic.

---

## Acceptance criteria

| Criterion | Result |
|---|---|
| ≥3 projects measured | ✅ **durations: N=3 projects / N=6 runs.** Accuracy reaches **N=2** — stated, with the reason, below |
| Every figure states N | ✅ every entry carries its own `N`; `N=1` is labelled `single_observation` and never averaged |
| **No single-project figure reported as a rate** | ✅ and the previous baseline's N=1 figures are **retracted in place** across 5 documents |

## Durations — N=3 projects, N=6 runs

Real Blender builds from each project's own manifest, against a **copy** of the data directory.

| Project | objects | rooms | builds (s) |
|---|---:|---:|---|
| `Sample reference run` | 14 | 5 | 39.4, 38.4 |
| `test 1` | 13 | 1 | 35.4, 29.4 |
| `Seed Project` | 8 | 2 | 19.6, 15.8 |

**Total build: N=6, mean 29.66 s, median 32.39 s, range 15.75–39.42, stdev 9.98.**

Per stage (N=6 each): `preview` **16.93 s**, `objects` **5.07 s**, `save` 1.46, `materials` 1.22, `reset` 0.20, `walls` 0.08, `rooms` 0.03, `validate` 0.01, `lighting` 0.01, `camera` 0.00.

Stage means sum to 25.01 s against a 29.66 s mean total. The 4.65 s difference is Blender process startup and exit, which sits outside the timed region — stated rather than smoothed away.

### The `40–60 s` figure is retracted

It was N=1. **No run in this batch reached 40 s.** The measured mean is 29.7 s and the slowest build was 39.4 s.

## Accuracy — N=2, and why not 3

| Project | coverage | placement @1.0 m | @0.5 m | orientation | assets | **composite** |
|---|---:|---:|---:|---:|---:|---:|
| `test 1` | 100% | 91% | 55% | 100% | 100% | **98%** |
| `Sample reference run` | **75%** | 100% | 100% | 100% | 100% | **94%** |
| **spread** | **25.0 pts** | 9.1 | 45.5 | 0 | 0 | 3.9 pts |

**The first project reproduces the documented N=1 figures exactly** — coverage 100%, placement 91%, composite 98%. That is worth knowing: the original measurement was not a fluke *for that project*.

**The second project tells a different story.** Composite **94%**, below the 95% target, because five pieces are unreachable by any camera (`open_win_kitchen.frame-1` and four objects). The harness reports `levers exhausted at 94%` — it did not reach the target and says so.

So **98% was the better of two, not a typical value**, and coverage — the metric that catches missing meshes and pieces buried in walls — swings 25 points between two projects.

### Why accuracy is N=2 and durations are N=3

Accuracy scores a built scene against **the moodboard reading the client approved**. `proj_seed` is a hand-authored demo scene that never went through the pipeline, so there is no approved reading to score it against — it has no `design_analysis.json`, `style_spec.json` or `scene_reading.json`. It can still be *built*, which is why it counts for durations.

Raising accuracy to N=3 requires running a third project end to end from photographs: analyze → moodboard → review → plan. That is real provider spend and a separate measurement; inventing a third data point by scoring a scene against itself would be worse than reporting N=2.

## The exit criterion, answered honestly

> *"until all the models don't reach 95%+ accuracy"*

**Not met at N=2.** One project reaches 98%, the other 94%. At N=2 this cannot honestly be called a rate in either direction — which is precisely the point of measuring N.

## An instrumentation defect found by measuring

`build_scene.py` emitted `ALLURE_STAGE <name> <seconds>` using `Timer.seconds` — **elapsed since start**, a cumulative mark, not a duration. Every consumer read it as a duration, including `app/jobs/handlers/build.py:83`, which prints the stages straight into the project's event feed.

Measured on a real build, the log claimed **`lighting 7.82s`**. Lighting actually took **0.00 s**; the first 7.82 seconds were almost entirely `objects`.

So the product was telling operators something false about where its time went. Fixed at source: `stage()` now records the delta. Verified — the stages now sum **exactly** to the reported total (24.45 s = 24.45 s), which they could not before.

The benchmark also checks for a regression on every run: cumulative marks are monotonically non-decreasing and overshoot the total, so `looks_cumulative()` catches the old behaviour if it returns.

## What was corrected, and where

| Document | Was | Now |
|---|---|---|
| `AUDIT_CODEBASE.md` | `~40–60 s` | 29.7 s mean, N=3/6, retraction noted |
| `TRD.md` ×2 | `40–60 s`; `composite 98%` | measured N=3/6; accuracy N=2 with both results |
| `plan.md` ×3 | same | same |
| `PRD.md` | `40–60 s observed` | measured, N stated |
| `docs/benchmarks/v4_baseline.json` | `measured_pipeline_timings` (all N=1) | `_superseded` field pointing here |

## Cost

**Meshy: 0 credits.** Nothing in this measurement can reach `generate_elements`. Blender and the ray-cast visibility pass cost GPU time only; `placement_loop` re-plans through `scene_plan`, which calls the vision provider — LLM tokens, not credits.

## Artifacts

- `docs/benchmarks/v4_runtime_baseline.json` — the deliverable
- `research/v4_runtime_baseline.py` — the harness, re-runnable
- `acc_proj_a25a006c88.json`, `acc_proj_553cb09794.json` — raw per-project accuracy output
