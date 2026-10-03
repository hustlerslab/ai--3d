# P2-RENDER-002 — Lighting from `LightingSpec` · verification

**2026-09-26 · Hat:** Blender Engineer · **Blender:** 5.2.1 LTS (real) · **Meshy spend: 0**

## Correction C17: already built, never proven

task.md says the typed `LightingSpec` exists but "**interior lights are not used**". Reading the code end to end shows the whole chain has been in place since the **initial commit** (`4d9a40e`):

| Link | Where |
|---|---|
| A preset per mood (sun azimuth/elevation/strength, sky turbidity, exposure, colour temperature) | `app/planning/compiler.py` `LIGHTING_PRESETS` |
| One ceiling area light per room, sized and powered from the room's area, at the preset's colour temperature | `compiler.py`, the `InteriorLight` list passed into `LightingSpec` |
| The spec is carried to Blender, with light positions converted to Blender's axes | `app/blender/manifest.py` `lighting` block |
| Blender builds the sky, the sun, every interior light at its location, and the exposure | `blender/scripts/setup_lighting.py` |

What was missing was the **proof** the task asks for. No code changed; `task.md` is not edited.

## Proof: real renders, real read-back (`tests/test_lighting_spec.py`, 4 real-Blender tests)

The same compiled scene is built twice through the production build (`build_scene.py`): once under **cool daylight** and once under **evening**. The saved `.blend` is then read back from inside Blender.

| Acceptance criterion | Test | Measured |
|---|---|---|
| **Interior lights appear at their specified positions** | `test_every_interior_light_is_built_where_the_spec_puts_it` | 4 lights specified, 4 built, each within 0.0001 m of its spec position, with the right type and power |
| Exposure reaches the render | `test_the_spec_exposure_reaches_the_render` | −0.2 EV (cool daylight) and +0.4 EV (evening), as specified |
| **Changing `LightingSpec` changes the render** | `test_changing_the_lighting_spec_changes_the_render` | **98.4%** of pixels change by more than 10/255 (the visual regression threshold, P1-QA-004, is 0.1%) |
| **"A warm evening scheme and a cool daylight scheme actually look different"** (the task's stated outcome) | `test_a_warm_evening_renders_warmer_than_cool_daylight` | red/blue balance **1.017 → 1.135** |

`render_cool_daylight.png` and `render_evening.png` (the before/after pair) and `measurement.json` are in this folder. I inspected both renders directly: cool daylight shows blue-white walls under a pale sky; evening shows warm peach walls under a dusk sky.

## Mutations (3/3 caught, each restored sha1-identical)

| Mutation in `setup_lighting.py` | Caught by |
|---|---|
| interior lights ignored | position test |
| the lighting spec ignored entirely | position, exposure, change and warmth tests |
| exposure not applied | exposure test |

**Found by the mutations:** with the whole spec ignored, the two renders are identical, and the warmth test at first **still passed**, because render noise put "evening" a fraction ahead. A bare `>` was not enough, so it now requires a margin (0.02, against a measured real gap of 0.118) and catches the mutation on its own.

## Full suite

`class=PRODUCTION-PATH passed=28 failed=0` (+4) — `pytest_production_path.txt`. The MOCK class is unaffected; only a Blender-marked test file was added.

## Honest limit

The sky's own sun intensity and background strength are fixed in `setup_lighting.py` (0.6 and 0.35); only the sun lamp follows `sun_strength`. The spec still changes the render decisively, as measured above, but a finer "sun strength alone" regression is not claimed.
