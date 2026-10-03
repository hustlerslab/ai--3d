# P1-RENDER-002 — Enable and verify raytraced indirect lighting · verification

**2026-09-26 · Hat:** Blender Engineer · **Blender:** 5.2.1 LTS at `D:/Blender/blender.exe` (real) · **Meshy spend: 0**

## The `[UNKNOWN]` (U18), resolved live

Task.md flagged the exact `RaytraceEEVEE` property surface as `[UNKNOWN]` and asked to read it in-process with `dir()`/`help()` before setting anything — not assume. Probed directly inside Blender 5.2.1 LTS:

```
scene.eevee.use_raytracing          bool,  default False
scene.eevee.ray_tracing_method      enum('PROBE','SCREEN'), default 'SCREEN'
scene.eevee.ray_tracing_options.trace_max_roughness    float 0..1, default 0.5
scene.eevee.ray_tracing_options.resolution_scale       STRING enum('1','2','4','8','16'), default '2'
scene.eevee.ray_tracing_options.screen_trace_quality   float, default 0.25
```

**Correction C15:** task.md asked to "record the tracing method, **ray count** and max roughness." Probed live: `RaytraceEEVEE` has no per-ray count the way Cycles does — `ray_tracing_method` picks between screen-space tracing (`SCREEN`, the higher-fidelity default) and probe-only (`PROBE`, the fallback the manual calls out as the low-fidelity path). The closest tunables are `resolution_scale` (trace-buffer resolution) and `screen_trace_quality`. Recorded what actually exists rather than inventing a ray-count field; `task.md` not edited.

**Found while implementing:** `resolution_scale` looks numeric (`'2'`) but is a **string enum**, not an int — setting `opts.resolution_scale = 2` raises `TypeError: expected a string enum, not int`. Caught immediately by a real Blender run before any test was written; fixed to `"2"`.

## Built

| Where | What |
|---|---|
| `blender/scripts/_common.py::apply_raytracing()` | Sets `use_raytracing=True`, `ray_tracing_method="SCREEN"`, `trace_max_roughness=0.5`, `resolution_scale="2"`, `screen_trace_quality=0.25`; **asserts** `use_raytracing`/`ray_tracing_method` actually stuck (same discipline as `build_scene.py`'s colour management) and raises `RuntimeError` naming the mismatch if not; prints `ALLURE_RAYTRACE {...}` with every value, always |
| `blender/scripts/_common.py::configure_engine()` | Calls `apply_raytracing()` on the EEVEE branch only — Cycles is already full path tracing and is untouched |

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Render config records raytracing **on** with named settings | `ALLURE_RAYTRACE {"use_raytracing": true, "ray_tracing_method": "SCREEN", "trace_max_roughness": 0.5, "resolution_scale": "2", "screen_trace_quality": 0.25}` on every EEVEE render's log — `tests/test_raytracing.py::test_raytracing_settings_are_named_and_recorded` |
| Settings are asserted applied (P1-BLENDER-001 discipline) | `apply_raytracing()` re-reads both properties after setting them and raises if either didn't stick; enforced by mutation (below) |

## Real-Blender proof (`tests/test_raytracing.py`, 3 tests, all passing)

- `test_raytracing_is_on_for_every_eevee_render` — a real EEVEE smoke render's log shows raytracing on
- `test_raytracing_settings_are_named_and_recorded` — the exact adopted values, not just "on"
- `test_cycles_render_is_unaffected` — a real Cycles smoke render has **no** `ALLURE_RAYTRACE` line at all

**Mutation (1):** commented out the `apply_raytracing(scene)` call (`sha1` before `c1e0d3ee...`, restored, `sha1` after `c1e0d3ee...` — identical) → both raytracing tests failed (`no ALLURE_RAYTRACE line in log`); the Cycles test correctly kept passing (unaffected either way), confirming it isn't accidentally coupled to the EEVEE change.

## Timing delta and visual difference (measurement, not shipped code)

A small synthetic scene (floor, one cube occluder, one area light, EEVEE 32 samples, 640×360) rendered twice per setting with a discarded warm-up render each (first render pays a fixed shader-compile cost unrelated to raytracing — an early un-warmed measurement showed OFF *slower* than ON, which is that artifact, not a real result):

| | seconds |
|---|---|
| raytracing OFF | 0.180 – 0.201 |
| raytracing ON | 0.240 (both repeats identical) |

**~20–30% render-time overhead on this GPU, on a trivial scene.** Pixel comparison of the two renders: mean absolute difference 0.48/255 across the whole frame, 1.4% of pixels changed by >5/255, max difference 11/255 — a real but modest difference, expected for a scene with a single occluder and one bounce surface. A real interior (walls, furniture, multiple occluders) has far more indirect-light geometry than this synthetic scene and would show a larger difference; that comparison is `before_raytracing_off.png` / `after_raytracing_on.png` in this folder, not re-measured against a full product render on this pass.

## Full suite after the change

`class=PRODUCTION-PATH passed=17 failed=0` (up from 14 — the 3 new raytracing tests) · `class=MOCK passed=1489 failed=1` (same pre-existing CLIP failure, unrelated) — see `pytest_verbose.txt`.

**Outcome:** every EEVEE render (preview stills, panoramas, the walkthrough film) now computes indirect light with actual ray tracing instead of the pre-filtered probe-only fallback Blender's own manual describes as "when visual fidelity is not the primary goal" — the second half of the product's silently-degraded visual promise (P0-RENDER-001 fixed the first, colour management).

**Rollback:** set `RAYTRACE_METHOD`'s call site to skip `apply_raytracing()`, or force `use_raytracing = False` — render time returns to baseline.
