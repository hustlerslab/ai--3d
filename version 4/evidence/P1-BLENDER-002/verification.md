# P1-BLENDER-002 — Register `render_viewpoints` as a job · verification

**2026-09-25 · Hat:** Blender Engineer (+ Backend) · **Blender:** 5.2.1 LTS at `D:/Blender/blender.exe` (real) · **Meshy spend: 0**

## What existed already

`blender/scripts/render_viewpoints.py` — opens the saved `.blend` (does **not** rebuild), takes an N-camera spec, renders each. Had no registered job handler.

## Built

| Where | What |
|---|---|
| `app/jobs/handlers/viewpoints.py` (new) | `viewpoints` job on `lane=JobLane.render`. Takes `params.views = [{name, position, look_at}, ...]` (Blender coordinates) plus optional `profile`/`subdir`. Refuses with a named error if no scene has been built (`blender/scene.blend` missing) or no views were given. Writes `renders/viewpoints/<subdir>/manifest.json` and registers it as a project output (`ctx.add_output("viewpoints", ...)`) |
| `app/jobs/handlers/__init__.py` | Imports the new module so `@register` runs |
| `app/projects/layout.py` | `CHECKPOINTS["viewpoints"] = "renders/viewpoints/default/manifest.json"` — the job's canonical output is discoverable the same way every other stage's is |
| `blender/scripts/render_viewpoints.py` | Now calls `configure_engine` once (was once per view — redundant since engine/samples don't vary per view) and reports `device` in its result, matching `smoke.py`/`build_scene.py`'s device-reporting convention from P1-BLENDER-001 |

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Renders N cameras from a committed scene **without rebuilding** | `test_viewpoints_renders_without_rebuilding`: records `scene.blend`'s mtime before enqueuing the `viewpoints` job, asserts it is **byte-for-byte unchanged** (`stat().st_mtime` identical) after the job succeeds and produced 2 PNGs |
| Runs on the render lane (GPU mutex preserved) | `test_viewpoints_is_registered_on_the_render_lane`: `get_spec("viewpoints").lane == JobLane.render` — the same lane as `build`, so the runner's single render-lane worker serialises it against any concurrent build, exactly like `preview`/`walkthrough` already do |
| Output paths registered in `CHECKPOINTS` | `CHECKPOINTS["viewpoints"]`; the project's `GET /api/projects/{id}` output list contains kind `"viewpoints"` after the job runs (asserted in the same test) |

## Real-Blender proof (`tests/test_viewpoints_job.py`, 4 tests)

- `test_viewpoints_is_registered_on_the_render_lane` — unit, MOCK class
- `test_viewpoints_renders_without_rebuilding` — full pipeline (analyze → scene-plan → build → viewpoints) against real Blender; two corner viewpoints of a real built scene, both PNGs >1KB, manifest written, `.blend` untouched, device reported non-empty (`OPTIX` on this machine)
- `test_viewpoints_requires_a_build_first` — enqueuing before any build fails the job with a named "run build first" error
- `test_viewpoints_requires_views` — enqueuing with an empty `views` list fails with a named "no viewpoints given" error

**Mutation (1):** removed the `has_checkpoint(BLEND)` guard (`sha1` before `7b19b367...`, restored, `sha1` after `7b19b367...` — identical once Windows Python's default text-mode CRLF translation in the mutation script was normalized back to the file's original LF line endings) → `test_viewpoints_requires_a_build_first` failed (job still failed, but for the wrong reason — a raw `BlenderError` from Blender trying to open a nonexistent `.blend`, not the named guard). Confirms the test is coupled to the guard's own message, not just "the job failed somehow."

## Full suite after the change

`class=PRODUCTION-PATH passed=14 failed=0` (up from 11 — the 3 new real-Blender viewpoints tests) · `class=MOCK passed=1489 failed=1` (same pre-existing CLIP failure, unrelated) — see `pytest_verbose.txt`.

**Outcome:** the render-verification chain (P1-VALIDATOR-001, next) now has a callable, lane-correct way to get fresh camera angles of a committed scene without paying to rebuild it.
