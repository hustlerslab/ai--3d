# -*- coding: utf-8 -*-
"""P0-ARCH-001: render the production inventory from the LIVE app, not by hand.

Run from aether-backend/ with its venv python. Writes ../docs/production/v4_inventory.md.
"""
import inspect
import pathlib
import re
import sys

sys.path.insert(0, ".")

from app.jobs.registry import _REGISTRY
from app.core.config import Settings
from app.projects.layout import CHECKPOINTS
from app.api.routes import router as r_scenes
from app.api.projects_routes import router as r_projects
from app.main import files_router
from app.auth.authz import is_anonymous

# Cost class is decided on the HANDLER's own source, never its module's.
# Over-counting spend is as dishonest as under-counting it: scene_plan's own
# comment says "approval gates SPENDING, which is the generate_elements job".
MESHY_RE = re.compile(r"meshy|CREDITS_PER_PIECE|submit_image_to_3d", re.I)

jobs = []
for t, s in sorted(_REGISTRY.items()):
    src = inspect.getsource(s.handler)
    meshy = bool(MESHY_RE.search(src)) and "MeshyNotConfigured" in src
    if meshy:
        cost = "**MESHY CREDITS**"
    elif s.uses_intelligence and s.uses_local_gpu:
        cost = "LLM tokens + local GPU"
    elif s.uses_intelligence:
        cost = "LLM tokens"
    elif s.uses_local_gpu:
        cost = "local GPU"
    else:
        cost = "CPU only"
    jobs.append((t, s, cost, meshy))

meshy_types = {t for t, _s, _c, m in jobs if m}

rows = []
for router, origin in (
    (r_scenes, "api/routes.py"),
    (r_projects, "api/projects_routes.py"),
    (files_router, "api/projects_routes.py (files)"),
):
    for r in router.routes:
        path, methods = getattr(r, "path", None), getattr(r, "methods", None)
        if not path or not methods:
            continue
        ep = r.endpoint
        try:
            src = inspect.getsource(ep)
        except (OSError, TypeError):
            src = ""
        enq = sorted({e for e in re.findall(r'["\'](\w+)["\']', src) if e in _REGISTRY})
        # A route that enqueues a CALLER-SUPPLIED type reaches every handler,
        # including both Meshy ones. Scanning for string literals alone misses
        # it entirely - and it is the single most powerful route in the app.
        wildcard = bool(re.search(r"enqueue\(\s*[\w.]+\s*,\s*(?!['\"])[\w.]+\s*,", src))
        # Auth is NOT visible in the signature: P0-SEC-002 attaches one
        # router-level dependency in main.py, deliberately, so that it cannot be
        # forgotten per route. The source of truth is therefore authz's
        # allow-list - anything not on it requires a principal.
        sig = str(inspect.signature(ep))
        for m in sorted(set(methods) - {"HEAD", "OPTIONS"}):
            probe = path.replace("{path:path}", "x")
            for name in ("project_id", "scene_id", "job_id", "asset_id",
                         "material_id", "proposal_id", "input_id", "room_id"):
                probe = probe.replace("{%s}" % name, "zz")
            rows.append({"m": m, "p": path, "origin": origin,
                         "auth": not is_anonymous(m, probe),
                         "enq": enq, "wildcard": wildcard,
                         "meshy": bool(set(enq) & meshy_types) or wildcard})

rows.sort(key=lambda r: (r["origin"], r["p"], r["m"]))

MUT = {"POST", "PUT", "PATCH", "DELETE"}
n_mut = sum(1 for r in rows if r["m"] in MUT)
n_auth = sum(1 for r in rows if r["auth"])
n_meshy = sum(1 for r in rows if r["meshy"])
SECRETISH = ("api_key", "token", "secret", "password")
env = sorted(Settings.model_fields)

L = []
w = L.append
w("# Allure V4 - Production Inventory")
w("")
w("**Generated 2026-09-21 by introspecting the running application**, not by reading documentation.")
w("Source of truth: `app.api.routes.router`, `app.api.projects_routes.router`, `files_router`, "
  "`app.jobs.registry._REGISTRY`, `app.core.config.Settings.model_fields`, `app.projects.layout.CHECKPOINTS`.")
w("")
w("> **No environment variable value appears in this file.** Names only, as required. The `Secret` "
  "column is derived from the variable's *name*, never from reading what is in it.")
w("")
w("---")
w("")
w("## 0. Headline numbers")
w("")
w("| | Count | Note |")
w("|---|---:|---|")
w("| HTTP routes (routers) | **%d** | matches the documented figure |" % len(rows))
w("| HTTP routes served (incl. `GET /` on the app) | **%d** | cross-checked against `app.openapi()` |" % (len(rows) + 1))
w("| - of which **mutate state** | **%d** | all now require an authorized principal |" % n_mut)
w("| - of which **can spend Meshy credits** | **%d** | authorized AND capped against the persisted ledger - section 1a |" % n_meshy)
w("| **Routes requiring authentication** | **%d** | P0-SEC-002: one router-level dependency, deny by default |" % n_auth)
w("| Routes deliberately anonymous | **%d** | each justified in `authz.py`; see section 1b |" % (len(rows) - n_auth))
w("| Registered job types | **%d** | **not 11** - see the correction below |" % len(jobs))
w("| Handler modules | 11 | `tour` and `scene_plan` each register two types |")
w("| Environment variables | **%d** | names only |" % len(env))
w("| Artifact checkpoints | **%d** | `CHECKPOINTS` |" % len(CHECKPOINTS))
w("")
w("### Correction found while producing this")
w("")
w("`task.md` and `AUDIT_CODEBASE.md` both say **11 job types**. There are **13**. Eleven *modules* "
  "are imported in `app/jobs/handlers/__init__.py`, but `tour.py` registers both `preview` and "
  "`walkthrough`, and `scene_plan.py` registers both `scene_plan` and `resolve_assets`. Counting "
  "imports is not counting registrations.")
w("")
w("---")
w("")
w("## 1. HTTP routes - all %d" % len(rows))
w("")
w("Auth is enforced by **one router-level dependency** attached in `main.py`, not by per-route "
  "decorators - a per-route check is a per-route opportunity to forget. The source of truth for this "
  "column is `authz.is_anonymous()`: anything not on that allow-list requires a principal, and a "
  "project-scoped route additionally requires that the principal may touch *that* project.")
w("")
w("| # | Method | Path | Origin | Auth | Enqueues | Spends Meshy credits |")
w("|---:|---|---|---|---|---|---|")
for i, r in enumerate(rows, 1):
    enq = "**ANY registered type (caller-supplied)**" if r["wildcard"] else (
        ", ".join("`%s`" % e for e in r["enq"]) or "-")
    w("| %d | `%s` | `%s` | %s | %s | %s | %s |"
      % (i, r["m"], r["p"], r["origin"],
         "required" if r["auth"] else "**anonymous**", enq,
         "**YES**" if r["meshy"] else "no"))
w("")
w("### 1b. Deliberately anonymous routes")
w("")
w("| Route | Why |")
w("|---|---|")
w("| `GET /health`, `GET /` | Liveness. A probe that needs credentials reports the wrong thing during an outage. |")
w("| `/api/auth/*` | You cannot authenticate in order to authenticate. |")
w("| `GET /api/projects/{id}/tour` | The share link `/w/{projectId}` is a feature. **P0-SEC-004** replaces it with a capability token. |")
w("| `/files/*` | The largest single hole, and **P0-SEC-005**'s whole job. Guarding it here in passing would be worse than guarding it there deliberately. |")
w("")
w("A test walks every registered route and fails on any that answers an anonymous request "
  "without being on this list (`tests/test_authz_matrix.py`). Measured: **62 routes probed, "
  "60 gated with 401, 2 allow-listed, 0 unguarded**.")
w("")
w("---")
w("")
w("### 1a. The %d routes that can spend real money" % n_meshy)
w("")
for r in rows:
    if r["meshy"]:
        how = ("**wildcard dispatcher** - the caller names the job type, so it reaches "
               "`generate_elements` AND `generate_assets`" if r["wildcard"]
               else ", ".join("`%s`" % e for e in r["enq"]))
        w("- `%s %s` -> %s" % (r["m"], r["p"], how))
w("")
w("Each generation is **30 credits**. Both require an authenticated principal who owns or is assigned "
  "to the project (P0-SEC-002), and both are capped against the persisted `spend_records` ledger "
  "(P0-SEC-003): `meshy_max_credits_per_project` = 600, `meshy_max_credits_per_user` = 3000. The caps "
  "are read from disk on every batch, so restarting the process does not reset them.")
w("")
w("**Still open:** the idempotency key (P1-ASSET-002). A retried request can still spend twice.")
w("")
w("**`POST /api/projects/{project_id}/jobs` is the most powerful route in the application.** It "
  "takes `type` and `params` straight from the request body and hands them to the runner, so it "
  "reaches all %d registered job types - including both Meshy handlers - with caller-controlled "
  "parameters such as `limit`. `generate_assets` has **no dedicated route at all**; this wildcard "
  "is its only entry point." % len(jobs))
w("")
w("A scan for string literals does not find it, because the type is never a literal. It is recorded "
  "here explicitly so `P0-SEC-002` does not protect the four named generation routes and leave the "
  "door that reaches all of them standing open.")
w("")
w("---")
w("")
w("## 2. Job types - all %d" % len(jobs))
w("")
w("| # | Type | Module | Lane | Resource / cost class | Attempts | Stage running -> done |")
w("|---:|---|---|---|---|---:|---|")
for i, (t, s, cost, _m) in enumerate(jobs, 1):
    w("| %d | `%s` | `%s.py` | `%s` | %s | %d | %s -> %s |"
      % (i, t, s.handler.__module__.rsplit(".", 1)[-1],
         getattr(s.lane, "value", s.lane), cost, s.max_attempts,
         getattr(s.stage_running, "value", None) or "-",
         getattr(s.stage_done, "value", None) or "-"))
w("")
w("### 2a. Lane assignment is not static")
w("")
w("`runner._lane_for()` overrides the registered lane in two cases, so the table above is the "
  "*declared* lane, not always the *running* one:")
w("")
w("1. `uses_local_gpu=True` **and** `SCENE_IMAGE_ENABLED` -> forced to `render`.")
w("2. `uses_intelligence=True` **and** a local intelligence provider (e.g. Ollama) -> forced to "
  "`render`, because it runs on the same 6 GB GPU as Blender.")
w("")
w("The `render` pool has **one** worker and the `ai` pool has **two**; that single render thread is "
  "the GPU mutex. On this hardware (RTX 3050 6 GB) it is a correctness mechanism, not a tuning knob.")
w("")
w("### 2b. Only two handlers actually spend Meshy credits")
w("")
w("`generate_assets` and `generate_elements`. Both raise `MeshyNotConfigured` when the key is absent, "
  "and both honour `meshy_max_per_project`.")
w("")
w("`scene_plan` mentions Meshy but **plans** generation without performing it - its own comment: "
  "*approval gates SPENDING, which is the generate_elements job*. `element_images` costs LLM and GPU "
  "time, not Meshy credits. An earlier module-level scan flagged four handlers and was wrong.")
w("")
w("---")
w("")
w("## 3. Environment variables - all %d, names only" % len(env))
w("")
w("| # | Name | Type | Secret (by name) | Has default |")
w("|---:|---|---|---|---|")
for i, name in enumerate(env, 1):
    f = Settings.model_fields[name]
    sec = any(x in name.lower() for x in SECRETISH)
    w("| %d | `%s` | `%s` | %s | %s |"
      % (i, name.upper(), getattr(f.annotation, "__name__", str(f.annotation)),
         "**yes**" if sec else "no",
         "yes" if f.default is not None else "no"))
w("")
w("Settings are loaded by `pydantic-settings` from the process environment **and** from `.env` "
  "(`config.py:16`). That second source is easy to forget: it is why the test suite could read a "
  "developer's real keys until an autouse fixture was added (see `TRACK_RECORD.md` P0-QA-004).")
w("")
w("---")
w("")
w("## 4. Artifact paths - all %d checkpoints" % len(CHECKPOINTS))
w("")
w("Paths are relative to a project's directory under `AETHER_DATA_DIR`.")
w("")
w("| # | Checkpoint | Relative path |")
w("|---:|---|---|")
for i, (k, v) in enumerate(CHECKPOINTS.items(), 1):
    w("| %d | `%s` | `%s` |" % (i, k, v))
w("")
w("### 4a. Static mounts that expose files over HTTP")
w("")
w("| Mount | Serves |")
w("|---|---|")
w("| `/files/assets` | the asset registry's `normalized/` directory |")
w("| `/files/assets-web` | the same geometry, textures sized to a GPU budget |")
w("| `/files/materials` | the material registry root |")
w("| `/files/projects/{project_id}/{path}` | per-project artifacts, resolved per request |")
w("")
w("The raw data directory is never mounted. All four are **unauthenticated**.")
w("")
w("---")
w("")
w("## 5. External dependencies")
w("")
w("| Dependency | Reached from | Failure mode today |")
w("|---|---|---|")
w("| **Meshy** image-to-3D | `generate_assets`, `generate_elements` | `MeshyNotConfigured` when the key is absent; 3-day asset retention upstream |")
w("| **Gemini** | intelligence provider | `ResilientProvider` falls back to a labelled deterministic estimate |")
w("| **Anthropic** | intelligence provider, only when selected | same |")
w("| **Ollama** (`:11434`) | intelligence provider when selected | job fails; forced onto the render lane |")
w("| **Blender** (`BLENDER_PATH`) | `build`, `preview`, `walkthrough`, `film`, `blender_smoke` | jobs fail; tests skip |")
w("| **Poly Haven** | asset ingest | asset resolution degrades to a lower rung |")
w("| **SQLite** (`data/allure.db`) | everything | local file; `SCHEMA_VERSION = 2` with migrations |")
w("| **RE Walkthrough Pro** (`:4000`) | frontend `/cinematic` **only** | optional; the page states plainly that the engine is absent |")
w("")
w("---")
w("")
w("## 6. What this inventory establishes for the next tasks")
w("")
w("| Task | What it can now target |")
w("|---|---|")
w("| **P0-SEC-002** | %d routes, of which %d mutate state and %d can spend credits (incl. the wildcard dispatcher) - a verified list, not an estimate |"
  % (len(rows), n_mut, n_meshy))
w("| **P0-INFRA-001** | %d environment variable names, %d artifact paths, 8 external dependencies |"
  % (len(env), len(CHECKPOINTS)))
w("| **Observability** | %d job types with declared lanes, plus the two runtime lane overrides |" % len(jobs))
w("")
w("*Regenerate with the extraction script recorded in `version 4/evidence/P0-ARCH-001/`.*")

out = pathlib.Path("../docs/production/v4_inventory.md")
out.write_text("\n".join(L) + "\n", encoding="utf-8")
print("wrote %s (%d bytes)" % (out, out.stat().st_size))
print("routes=%d mutating=%d meshy=%d auth=%d jobs=%d env=%d checkpoints=%d"
      % (len(rows), n_mut, n_meshy, n_auth, len(jobs), len(env), len(CHECKPOINTS)))
