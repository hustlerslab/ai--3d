# Why the renders look dull, and what to change

*Research report · 2026-09-18 · 18 sources · measured against this repo's Blender 5.2.1*

Written for: whoever works on the Blender render lane in this repo.

## Executive summary

The renders are dull for four reasons, and the largest two are bugs rather than
taste. **A colour-management call fails silently and is swallowed**, so every
render comes out of AgX with no contrast look applied at all. **EEVEE's
ray-tracing is off**, which is its documented default and which replaces real
indirect lighting with a light-probe approximation - the flat look. On top of
those, the sky is set to about a third of the brightness an interior needs, and
the preview profile renders 16 samples at 960x540.

None of the four needs a new renderer, a new asset pipeline, or more render
time worth mentioning. The first is a one-line fix. Measured on this machine,
the corner renders take 11 s for four frames; the changes below cost a few
seconds more, not minutes.

---

## 1. The colour transform is failing silently  <- start here

`blender/scripts/build_scene.py:37-41`:

```python
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium Contrast"
except TypeError:
    pass
```

Probed directly against the installed Blender 5.2.1, setting each candidate and
catching the rejection:

| value | accepted by this build |
|---|---|
| `AgX - High Contrast`, `AgX - Very High Contrast`, `AgX - Punchy`, `AgX - Base Contrast`, `None` | yes |
| **`AgX - Medium Contrast`** | **no - TypeError** |

The name comes from an older Blender. The first line succeeds, the second
throws, `except TypeError: pass` discards it, and the look stays at the factory
default. So the intended "medium contrast" has never once been applied.

That matters more than it sounds, because of what AgX is. The Blender manual
describes it as a transform that *"desaturates highly exposed colors to mimic
film's natural response to light"* ([Displays and Views, Blender 5.2
manual](https://docs.blender.org/manual/en/5.2/render/color_management/displays_views.html)).
It is deliberately log-like - a base for grading, not a finished look. CG
Cookie puts it plainly: artists *"struggle to actually get the colors they want
while using it because the default results can look a bit dull"*, and the
desaturation *"is actually an important feature and not a bug"* ([CG
Cookie](https://cgcookie.com/posts/the-secret-to-rendering-vibrant-colors-with-agx-in-blender-is-the-raw-workflow)).

So the pipeline applies a transform designed to be graded afterwards, then does
not grade it, and also fails to apply the contrast curve it thinks it set.

**Two defensible fixes. They are different products, not better and worse.**

*(a) Khronos PBR Neutral.* Available in this build (verified). The manual: *"a
tone mapping transform designed specifically for PBR color accuracy, to get
sRGB colors in the output render that match as faithfully as possible the input
sRGB base color in materials... aimed toward product photography use cases"*.
That is this product: a client picks a sage-green wall and a walnut sideboard
off a moodboard, and the render should show the colour they picked. AgX will
shift it; PBR Neutral is built not to.

```python
scene.view_settings.view_transform = "Khronos PBR Neutral"
```

*(b) Keep AgX, apply a real look.* Better for sunlit hero shots with blown
windows, where AgX's highlight roll-off genuinely beats everything else.

```python
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - High Contrast"   # or "AgX - Punchy"
```

**And stop swallowing the error.** Whichever is chosen, a failed colour
assignment must be reported, not passed over. It hid this for the life of the
project.

---

## 2. EEVEE ray-tracing is off - the flat look

Probed on this build: `scene.eevee.use_raytracing` is **`False`**, and nothing
in `blender/scripts/` ever sets it. Blender's own manual on what that means:
*"When disabled, it is replaced by a faster pipeline that uses pre-filtered
light-probes"* ([Raytracing, Blender 4.2
manual](https://docs.blender.org/manual/en/4.2/render/eevee/render_settings/raytracing.html)).

A Blender Artists walkthrough on interior EEVEE begins with exactly this:
*"The first thing I will do is activate raytracing in the render settings.
Already we are getting a bit of shading on the walls"* ([Correct indoor
lighting in Eevee](https://blenderartists.org/t/correct-indoor-lighting-in-eevee/1587366)).

Also measured off: `use_overscan` is `False`, and
`ray_tracing_options.resolution_scale` is `"2"` (half resolution). Overscan
matters because EEVEE's ray-tracing is screen-space - the manual notes screen
space effects *"disappear when reaching the screen border"*, and overscan is
the documented mitigation.

Concretely, in `_common.configure_engine`:

```python
scene.eevee.use_raytracing = True
scene.eevee.ray_tracing_options.resolution_scale = "1"   # 1:1, was 1:2
scene.eevee.ray_tracing_options.use_denoise = True
scene.eevee.use_overscan = True
scene.eevee.overscan_size = 5.0
scene.eevee.use_fast_gi = True          # cheap bounce fill for rough surfaces
scene.eevee.shadow_ray_count = 2        # default 1; softer, truer contact shadows
scene.eevee.shadow_step_count = 6
```

Per-light, for the sun in `setup_lighting.py`, since jitter is off by default
and is what gives accurate soft shadows from a large light:

```python
sun_data.use_shadow_jitter = True
```

The 4.2 migration notes confirm the default: jitter *"is disabled by default
since shadow map ray tracing can output plausible soft shadows at a much lower
cost"* ([Migration
Process](https://developer.blender.org/docs/release_notes/4.2/eevee_migration/)).
Plausible is not the same as right, and interiors are where the difference
shows.

---

## 3. The room is under-lit, and nothing compensates

`setup_lighting.py` sets the world background strength to **0.35** and the Sky
texture's own `sun_intensity` to **0.6**. Every interior source says that is far
too dim for a room lit through windows:

- iMeshh's archviz walkthrough bumps **world strength to 5** to brighten the
  room while keeping the HDRI for colour ([Make an Interior in Blender Like a
  Pro](https://imeshh.com/blog/make-an-interior-in-blender-like-a-pro-archvis-tutorial-2-im)).
- A Blender StackExchange answer on exactly this symptom: raise **Exposure
  above 0** *or* **world Strength above 1**, *"or you do both"*, and notes that
  a Medium High / High Contrast look beats None ([HDRI lighting too
  dark](https://blender.stackexchange.com/questions/271730/hdri-lighting-too-dark-and-hdr-image-just-acting-odd)).
- The presets in `app/planning/compiler.py` set `exposure_ev` to 0.0 for both
  daylight moods, so nothing compensates.

The physical point, from the same sources: a real interior photographed against
a window is either a dark room with a correctly exposed window, or a correct
room with a blown window. Choosing is the job. Right now it chooses neither and
lands grey.

Starting values, to be tuned by looking:

```python
bg.inputs["Strength"].default_value = 1.2    # was 0.35
sky.sun_intensity = 1.0                      # was 0.6
# and in the presets, lift daylight exposure
"warm_daylight": {..., "exposure_ev": 0.5},
```

## 4. Preview renders at 16 samples, 960x540

`render_preview.PROFILES["preview"]` is `EEVEE, 16 samples, 960x540`. That is
the profile behind every image reviewed so far. With ray-tracing on, samples
matter more, not less. A `review` profile at 64-128 samples and 1280x720 costs
seconds and is what a client should see; `preview` can stay the fast iteration
path.

---

## What was deliberately NOT recommended

**Switching the default to Cycles.** The sources agree it is the photoreal
answer - 256-512 samples with OpenImageDenoise, 4-6 diffuse bounces, indirect
clamp 10 ([Blender Render Settings
2026](https://superrendersfarm.com/article/blender-render-settings-optimization-guide);
[iRender on light
paths](https://medium.com/@irenderofficial/how-to-optimize-light-paths-in-blender-cycles-without-killing-your-lighting-2026-4ab7ef10b28c))
- and `hero_still` already uses it at 256. But the four items above are free and
unfixed, and a Cycles render of a scene with a broken colour look and an
under-lit sky is a slower dull image. Fix the free things first, then measure
whether Cycles is still needed.

**An HDRI instead of the procedural sky.** It is the strongest single upgrade in
the literature - every archviz source prefers it, a 2K Poly Haven file is
enough, and 8K changes nothing but load time. It is not first because it means
shipping or fetching an asset and choosing one per lighting mood, which is a
product decision rather than a settings change. It is the right next step after
the four above.

**Window portals / emissive window planes.** Cycles-specific (portals) or a
material trick (planes). Both are well attested - *"every interior needs
supplemental window-bounce planes"* ([Mustafa
Kurd](https://mustafakurd.com/blog/interior-render-workflow-blender)) - and both
are more work than this round needs.

---

## Suggested order

| # | Change | Effort | Render cost |
|---|---|---|---|
| 1 | Fix the look name; stop swallowing the TypeError | one line | none |
| 2 | Pick the view transform deliberately (PBR Neutral, or AgX + High Contrast) | one line | none |
| 3 | Enable EEVEE ray-tracing, 1:1, overscan, fast GI | ~6 lines | seconds |
| 4 | Sun shadow jitter | one line | seconds |
| 5 | Raise world strength and daylight exposure | 3 values | none |
| 6 | Add a `review` render profile | small | seconds |
| 7 | HDRI world (2K, per mood) | asset + wiring | none |
| 8 | Re-measure, then decide about Cycles | - | - |

Every one of 1-6 lives in `blender/scripts/` or `app/planning/compiler.py`, and
none touches the solver, the asset pipeline, or the reading.

## Sources

1. [Displays and Views - Blender 5.2 manual](https://docs.blender.org/manual/en/5.2/render/color_management/displays_views.html) - definitions of AgX, Filmic, Khronos PBR Neutral; AgX "desaturates highly exposed colors".
2. [Raytracing - Blender 4.2 manual](https://docs.blender.org/manual/en/4.2/render/eevee/render_settings/raytracing.html) - what disabling ray-tracing substitutes; Fast GI parameters.
3. [EEVEE Next release notes, 4.2](https://developer.blender.org/docs/release_notes/4.2/eevee/) - screen-space ray tracing for every BSDF; virtual shadow maps.
4. [EEVEE migration notes, 4.2](https://developer.blender.org/docs/release_notes/4.2/eevee_migration/) - shadow jitter now per-light and off by default.
5. [EEVEE limitations - Blender 4.2 manual](https://docs.blender.org/manual/en/4.2/render/eevee/limitations/limitations.html) - screen-space effects vanish at frame borders; overscan as mitigation.
6. [Light Settings - Blender 4.2 manual](https://docs.blender.org/manual/en/4.2/render/eevee/light_settings.html) - virtual shadow mapping, jitter, resolution limit.
7. [Correct indoor lighting in Eevee - Blender Artists](https://blenderartists.org/t/correct-indoor-lighting-in-eevee/1587366) - practitioner walkthrough: raytracing first, 1:1, jittered shadows, overscan, light probes.
8. [The Secret to Rendering Vibrant Colors with AgX - CG Cookie](https://cgcookie.com/posts/the-secret-to-rendering-vibrant-colors-with-agx-in-blender-is-the-raw-workflow) - why AgX reads dull by design, and what to do about it.
9. [Why Your Blender Renders Look Different - CGEcho](https://cgecho.net/why-your-blender-renders-look-different-the-essential-role-of-tone-mapping/) - tone mapping and export behaviour.
10. [Achieving Realistic Rendering with AGX and Khronos PBR Neutral](https://jayargonaut.com/2024/08/11/achieving-realistic-rendering-with-agx-and-khronos-pbr-neutral-in-blender-4-2/) - practitioner comparison; PBR Neutral reads more saturated.
11. [AgX changes hue - Blender Artists](https://blenderartists.org/t/agx-changes-hue/1527123) - documented hue shift under AgX; PBR Neutral and Filmic as predictable alternatives.
12. [Filmic vs AgX in small archviz - Blender Artists](https://blenderartists.org/t/filmic-vs-agx-in-small-archviz/1415581) - counterpoint: AgX preferred for interiors by some.
13. [Make an Interior in Blender Like a Pro - iMeshh](https://imeshh.com/blog/make-an-interior-in-blender-like-a-pro-archvis-tutorial-2-im) - 2K HDRI sufficiency, world strength ~5, window portals, 250 samples.
14. [Interior render workflow in Blender - Mustafa Kurd](https://mustafakurd.com/blog/interior-render-workflow-blender) - sun 3-5, window bounce planes, 256-512 samples, 12/4/6/8 bounces.
15. [Final render looks so dull [Archviz - Cycles] - Blender Artists](https://blenderartists.org/t/final-render-looks-so-dull-archviz-cycles/1445815) - the same symptom; contrast look, brighter sources, exposure over light strength.
16. [HDRI lighting too dark - Blender StackExchange](https://blender.stackexchange.com/questions/271730/hdri-lighting-too-dark-and-hdr-image-just-acting-odd) - exposure vs world strength, with side-by-side values.
17. [Blender Render Settings: Cycles & Eevee Guide 2026](https://superrendersfarm.com/article/blender-render-settings-optimization-guide) - 256-512 samples + OIDN as the production norm.
18. [How to Optimize Light Paths in Blender Cycles - iRender](https://medium.com/@irenderofficial/how-to-optimize-light-paths-in-blender-cycles-without-killing-your-lighting-2026-4ab7ef10b28c) - bounce budgets, indirect clamp 10, caustics off.

## Methodology

Four searches across colour management, EEVEE Next interior settings, archviz
lighting and Cycles interior settings; 18 sources retained, weighted towards the
Blender manual and developer release notes over tutorials. Every claim about
*this* repo was then verified by probing the installed Blender 5.2.1 directly
rather than trusting a documentation version: the ray-tracing default, the
overscan default, the ray-tracing resolution scale, the available view
transforms, and which AgX looks the build accepts. That last probe is what found
the silently-swallowed `TypeError`, which no amount of reading would have.

**Not measured:** none of the changes above has been applied or rendered yet, so
the improvement is predicted, not demonstrated. The corner-render harness in
`research/placement_loop.py` renders four views in about 11 s and is the natural
way to prove it - render once before, once after.
