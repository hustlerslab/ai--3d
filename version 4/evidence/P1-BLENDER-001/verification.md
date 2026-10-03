# P1-BLENDER-001 — Harden execution and assert settings · verification

**2026-09-25 · Hat:** Blender Engineer · **Blender:** 5.2.1 LTS at `D:/Blender/blender.exe` (real, on this machine) · **Meshy spend: 0**

## What was already done (confirmed, not re-built)

| Criterion | Evidence |
|---|---|
| A script exception yields a non-zero exit and a classified failure | `blender/scripts/build_scene.py`'s outer `try/except Exception: fail(...)` calls `sys.exit(1)`; `app/blender/runner.py::run()` raises `BlenderError` on that exit code; `app/jobs/runner.py:355-357` classifies every job-failing exception via `classify.from_exception`, which maps any `Blender*` exception name to `FailureCategory.BLENDER_EXECUTION_FAILURE` (`app/supervisor/classify.py:206`) |
| Killing Blender mid-build marks the job failed with captured logs; the API stays up | Already covered by `tests/test_runner_timeout.py::test_blender_timeout_kills_process` (real Blender, real kill) — **passing**, part of this session's PRODUCTION-PATH run |
| `--factory-startup`, list-form args, no `shell=True` | `app/blender/runner.py:98-103` (unchanged) |

## What was missing, and built

**Startup logs the render device; a misconfigured device fails with a named error** — the one real gap.

| Where | What |
|---|---|
| `blender/scripts/_common.py::configure_engine` | Prints `ALLURE_DEVICE engine=<engine> device=<device>` on **every** render (Cycles: `OPTIX`/`CUDA`/`HIP`/`METAL`/`CPU`; EEVEE: always `GPU`, since Blender 5.x EEVEE Next has no CPU path to misconfigure). When `AETHER_REQUIRE_GPU=1` is set and Cycles resolves to `CPU`, raises `RuntimeError("render device misconfigured: ...")` instead of silently rendering slow |
| `app/core/config.py` | `blender_require_gpu: bool = False` — off by default, so a machine with no discrete GPU keeps working; a render fleet turns it on to catch a misconfigured node loudly instead of it just running slow forever |
| `app/blender/runner.py::BlenderRunner.run()` | Passes `AETHER_REQUIRE_GPU=1/0` into the Blender subprocess's environment, read from `settings.blender_require_gpu` at construction |

## Real-hardware proof

This machine has an NVIDIA GPU. Ran `smoke.py` directly through Blender:

```
ALLURE_DEVICE engine=CYCLES device=OPTIX
ALLURE_RESULT {"ok": true, ..., "device": "OPTIX", ...}
```

`tests/test_blender_device.py` (new, 4 tests, all real Blender, all passing):

| Test | What it proves |
|---|---|
| `test_device_is_logged_for_a_real_cycles_render` | A real Cycles smoke render's log contains `ALLURE_DEVICE engine=CYCLES device=<something>` |
| `test_eevee_render_also_logs_its_device` | Same for EEVEE (`device=GPU`) |
| `test_require_gpu_fails_loudly_with_no_gpu_backend` | With `BLENDER_REQUIRE_GPU=1`, a script that simulates "no GPU backend" (monkeypatches `enable_gpu()` to return `"CPU"` — the only way to exercise this on a machine that *does* have a working GPU) raises `BlenderError` whose message names "misconfigured" and "gpu" |
| `test_require_gpu_off_by_default_does_not_fail` | The same simulated no-GPU script succeeds when the setting is off (default) |

**Mutation (1):** commented out the `require_gpu` check in `_common.py` (`sha1` before `b0be963...`, restored, `sha1` after `b0be963...` — identical) → `test_require_gpu_fails_loudly_with_no_gpu_backend` failed with `DID NOT RAISE BlenderError`, confirming the test actually exercises the enforcement path, not just log presence. Restored and re-verified: 11/11 PRODUCTION-PATH tests pass.

## Full suite after the change

`class=PRODUCTION-PATH passed=11 failed=0` (up from 7 before this task — the 4 new device tests) · `class=MOCK passed=1488 failed=1` (same pre-existing CLIP failure, unrelated) — see `pytest_verbose.txt`.

**Outcome:** every Blender render now states which device it used, on the record, not assumed; a fleet that requires GPU catches a misconfigured node the first time it renders, not after someone notices renders are slow.
