# P16 — Production Wiring: Reference to 3D Scene

P11 to P15 each proved a capability. P16 asks whether the product reaches them:
can a real person upload a photograph and see the result of that work in the
real application?

The answer is mostly yes, and the audit found the pipeline was already
connected. The work was not wiring it — it was closing four defects that sat
between a correct backend and an honest user experience.

Stack unchanged and frozen: Gemini, Meshy, the Allure Spatial Engine, Blender.

---

## 1. The authoritative production path

There are nine backend-triggering actions in the Studio. The one that means
"generate my 3D scene" is `runRender`, behind the button labelled **Generate 3D
space**. It fires two jobs in sequence and then reads the tour package.

```
Studio "Generate 3D space"
  -> POST /api/projects/{id}/build        job: build    -> scene.blend + preview
  -> POST /api/projects/{id}/preview      job: preview  -> panoramas + tour.json
  -> GET  /api/projects/{id}/tour
```

Everything before it is preparation, in this order: `analyze` produces the
moodboard, `scene-plan` produces the scene, `elements/generate` buys meshes from
Meshy, then a forced `scene-plan` re-plans so the purchased meshes are actually
used. `walkthrough` and `film` are post-hoc quality upgrades of an existing
result.

Nothing chains automatically. Every step is a separate client-initiated POST,
and each returns a job id the frontend polls at `GET /api/jobs/{job_id}`.

---

## 2. P11 to P15 were already in the production path

This was the audit's most useful finding, and it meant P16 had far less to build
than expected. The production `scene_plan` handler already calls all four:

| Phase | Call | Where |
|---|---|---|
| P11 / P15 | `classify_references` | `scene_plan.py:124`, reached from `:279` |
| P12 | `apply_intents_to_plan` | `scene_plan.py:343` |
| P11 | `resolve_all` | `scene_plan.py:425` |
| P13 | `visual_intent_fidelity` | `scene_plan.py:427` |

P14's rendering contract reaches production through `build_manifest`, which
`scene_plan` does *not* call — the `build` and `walkthrough` handlers do, at
`build.py:55` and `tour.py:209`. That is correct: the manifest is the executor's
input, not the planner's output.

P15's prompt needed no wiring at all. It lives in
`reference_classification_prompt`, the single canonical location the Gemini
provider already calls, so improving it improved production the moment it
landed.

---

## 3. The four defects P16 fixed

**A demo apartment could be shown as the client's own design.** The 3D viewer
defaults `sceneId` to `scene_seed_apartment`, and the Studio passed
`sceneId ?? undefined` — so a project that reached the Experience step with no
scene of its own rendered the seed demo flat, unlabelled and indistinguishable
from the user's work. The Studio now renders the viewer only with a real scene
id, and says plainly when there is none. The standalone `/3d` route keeps its
demo default, which is what that route is for.

**A failed generation was displayed beside the previous success.** `runRender`
cleared nothing before starting, so a failed build left the last successful
preview image and tour on screen next to a red failure panel. It now drops the
previous render first.

**A failed re-plan advanced the user to a stale scene.** `confirmAndPlan` called
`next()` unconditionally, and the next step renders the 3D plan keyed on
`sceneId` — which still held the *previous* plan. The user was shown an old
scene as the result of a run that had just failed. It now stays put, keeping the
failure and its retry button in view.

**Double-clicking Generate queued the work twice.** There was no duplicate guard
anywhere: every route called `enqueue` unconditionally. On the render lane the
duplicates merely serialised, but the `ai` lane has two workers, so two
concurrent `scene_plan` jobs for one project wrote the same planning files.

The fix is a short guard in `JobRunner.enqueue`, the single point all ten routes
funnel through, plus one new store query. If a job of the same type is already
`QUEUED`, `RUNNING` or `RETRYING` for that project, the existing job is returned.
The client polls a job id, so it cannot tell the difference and ends up watching
the run that is really happening. It is deliberately in-flight only: a finished
job never blocks a re-run, so `force` and genuine retries are untouched.

---

## 4. A security defect found while running the pipeline

The live run's own logs exposed it. The Gemini provider sent its key as a query
parameter, and `httpx` logs whole URLs at INFO — so **every** generate call
wrote the live API key in clear text into the job and server logs.

The key now travels in the `x-goog-api-key` header, which is the documented form
and which nothing logs. A regression test asserts the key is absent from the
request URL and present in the header.

This was pre-existing, not introduced by P16. It is the kind of thing only a
real run surfaces.

---

## 5. Observability

The per-project `events` table already recorded stage and status. What was
missing was the server-side half, so a log file alone could not follow one
generation. Each job now logs one line on start and one on its terminal
transition:

```
job.start     project=proj_e6b5a80307 job=job_c080bb46b9 type=scene_plan lane=ai attempt=1/2
job.succeeded project=proj_e6b5a80307 job=job_c080bb46b9 type=scene_plan ms=6433 scene_id=scene_f605d7cbba scene_version=1
job.failed    project=... job=... type=... attempt=2/2 ms=... reason=...
```

Ids only. No brief text, no prompt, no image, no key. A test asserts the brief
never appears in the log stream.

---

## 6. The real end-to-end run

One real photograph — the sage sofa on a dark wood frame, the case P15 showed
the model reads correctly — through the real routes, live Gemini and the real
Blender binary. The data directory was isolated, with its asset and material
folders junctioned to the real library so the run saw the real 58-asset registry
without writing into anyone's project data.

| Stage | Result | Seconds |
|---|---|---|
| upload | 0 rejected | 0.06 |
| analyze | SUCCEEDED | 6.21 |
| scene_plan | SUCCEEDED | 6.48 |
| build (Blender) | SUCCEEDED | 12.72 |
| **total** | | **25.47** |

What the reference produced, live:

```
frame_finish      dark wood
color_words       sage green, dark brown
upholstery        fabric
pattern           tufted
descriptors       tufted back, tufted seat, wooden armrests, crossed side panels, ...
```

The traceability chain, every link over the real API:

```
in_cfe1902649  (uploaded reference)
  -> di_1cc56006607dcbec  (design intent, exact_object, sofa)
  -> obj_8a26302ca8       (scene object, source_intent_ids names the intent)
  -> ph_sofa_02           (asset chosen by the ladder)
  -> build_manifest.json  (visual + finish blocks)
  -> scene.blend          (12,156,890 bytes)
```

`scene.blend`, the preview PNG and the manifest all returned HTTP 200 from the
file route after the job reported success. Nothing pointed at a file that
vanished.

---

## 7. What the user would actually see, honestly

This is the part worth reading slowly, because "the pipeline works" and "the
picture is right" are different claims.

**Rendered.** The sofa is placed as the solver decided, wearing colour `#7FA695`
— the sage green read off the client's own photograph — over the `fabric_linen`
registry material. Those two channels carry reference intent all the way to
pixels.

**Not rendered.** The frame finish did not reach Blender. The manifest records
it faithfully:

```json
{"frame_finish": "dark wood", "frame_material": "veneer_oak",
 "material_regions": 1, "source": "stated", "state": "metadata_only",
 "reason": "the asset has a single material region; a frame finish would repaint the whole piece"}
```

Extraction was correct, the resolver ran, and the executor declined — because
`ph_sofa_02` is one of the 48 single-region assets out of 58. This is the P14
ceiling behaving exactly as measured, stated in the manifest rather than hidden.

**Still wrong where P15 said it was wrong.** `frame_material` reads `veneer_oak`
for "dark wood". P16 did not fix that, and this run does not claim otherwise.
Had the asset been multi-region, the frame would have rendered in light oak
against a dark wood reference.

So the truthful summary for this reference: the client's colour and fabric
survive to the render; the frame finish survives to the manifest and stops
there, with a written reason.

---

## 8. Verification

| Suite | Result |
|---|---|
| Backend | 883 passed, 9 skipped, 30 xfailed |
| Backend, P16 file only, with Blender | 22 passed |
| Frontend (vitest) | 26 passed |
| Frontend typecheck (`tsc --noEmit`) | clean |
| Frontend lint (eslint) | no warnings or errors |
| Frontend build (`next build`) | compiled, 7 routes |

883 is the 863 P15 baseline plus 22 new P16 tests, of which 2 skip without
`BLENDER_PATH`. No existing test was modified.

Regression: P11 10/10, P12 10/10, P13 10/10, P14 11/11, P15 51/51. Frozen P4 to
P10 unchanged and still deterministic — 30/30 constraint, 40/40 candidate, 22/22
scene, 12/12 repair, 10/10 clearance, P10 system success rate 1.0.

The build was run with `NEXT_DIST_DIR` pointed at a separate directory, because
`next dev` and `next build` otherwise share `.next` and a build underneath a
live dev server corrupts what that server is serving. `next.config.ts` now reads
that variable, defaulting to `.next` so nothing changes unless asked.

---

## 9. Remaining production gaps

These are real and unfixed. None was introduced by P16.

1. **No authentication on any route**, including `DELETE /api/projects/{id}` and
   the credit-spending `POST /elements/generate`. CORS restricts origins; that is
   not access control.
2. **`POST /api/projects/{id}/jobs` runs any registered handler with any
   params**, bypassing every route-level precondition — the Blender check, the
   analysis check, and the Meshy per-project spend clamp.
3. **Absolute host paths leak to the client** through `job.log_path` on every job
   row and through the `output` block inside `build_manifest.json`.
4. **Upload size is enforced after the whole body is buffered**, so twelve
   concurrent 25 MB uploads are 300 MB resident before any limit applies.
5. **`/api/assets/upload` joins a client-supplied filename and an unsanitised
   `asset_id` into a path** — the one genuine traversal candidate in the
   codebase.
6. **A running job is orphaned in the UI by a browser refresh.** The backend
   keeps working and the job completes, but the job handle is not persisted, so
   the user sees no progress until their next explicit action.
7. **`ProjectStage` transitions are unguarded UPDATEs** and `STAGE_ORDER` is dead
   code, so re-running `analyze` drags a COMPLETED project back to ANALYZING.
8. **Restarting the backend recreates `proj_seed`** via `ensure_seed` in the app
   lifespan. Benign, but a deleted seed project reappears.
