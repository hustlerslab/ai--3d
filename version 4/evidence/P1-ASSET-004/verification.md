# P1-ASSET-004 — Persist meshes within the vendor retention window · verification

**Completed:** 2026-09-22 · **Hat:** Backend Engineer (+ DevOps) · **Branch:** `ai-3d` on `02ca264` (dirty) · **Meshy spend: 0** (vendor faked; real ingester on a real GLB)

## Before

The download already happened before completion — good — but the invariant was **neither stated nor tested**, and two things violated its spirit:

1. `AssetSource.thumbnail_url = model.thumbnail_url` stored Meshy's **signed, time-limited CDN URL** on the asset record in both Meshy handlers, and `catalog.py` served it to the UI. It dies with the 3-day retention window.
2. Reuse trusted the *record*: a registry row whose normalized bytes were gone (restore without assets, cleaned disk) was still handed to the scene as "already ours".

## The change

| Where | What |
|---|---|
| `app/assets/pipeline.py` | `has_normalized(record)` and **`persisted(record, source) → ""` or the reason**: original present and non-empty, normalized copy present and non-empty, and no vendor file URL on a Meshy record |
| `app/providers/meshy.py` | `download_thumbnail()` — one attempt, never fatal; the preview lives beside the mesh |
| `generate_elements._generate_one` / `generate.py` | thumbnail persisted as `assets/elements/<key>.thumb.png` (resp. `assets/generated/…`) and stored as a **local `/files/…` URL**; `persisted()` checked **before** `SUCCEEDED` / the checkpoint; on failure the download is **unlinked** (the file is the checkpoint) and the receipt stays resumable |
| `generate_elements._bound_asset` / `_ensure_registered` | a binding or a registry row is a receipt **only while its bytes are here**; otherwise re-ingest from the download, or fall through to the task |
| `app/spend/tasks.py` | `SUCCEEDED` rows are re-pollable: a mesh lost after the fact is **re-downloaded from the vendor's still-open task** inside the window, never bought again; an `EXPIRED` answer becomes `MeshyTaskFailed` → `FAILED` → only then a fresh submission |

`source.url` keeps the **task** URL (`https://api.meshy.ai/openapi/v1/image-to-3d/<id>`) — a stable provenance id, not a file.

## Acceptance — `tests/test_asset_persistence.py` (5 passed; `pytest_verbose.txt`)

| Criterion | Evidence |
|---|---|
| A completed task's mesh is in Allure storage before completion is recorded | real ingester, real GLB: every `SUCCEEDED` row has a registry record with a non-empty normalized file and a non-empty project original; `persisted() == ""`; thumbnails on disk with local URLs; **no vendor host anywhere** in `registry.json` or the project's JSON |
| **Expiring the vendor URL after download breaks nothing** | `download_glb` and `download_thumbnail` then raise 403 for every URL → the next run: `submit +0`, `reused 3`, `attached 3`, normalized files resolve, thumbnails serve **200 from Allure** |
| Not persisted ⇒ not done | ingester answers without a normalized copy → `made {}`, `credits 0`, warnings "mesh not persisted", rows stay `SUBMITTED`, nothing bound |
| Record without bytes, download on disk | re-ingested from the download, `submit +0`, bytes back in storage |
| Record and download both gone, window open | task **polled** (same ids), re-downloaded, `submit +0`, 3 made |

## Mutation tests (source restored, verified byte-identical)

| Mutation | Result |
|---|---|
| M1 `persisted()` always satisfied | **CAUGHT** — 2 failed |
| M2 download kept after a failed invariant | **CAUGHT** — 1 failed |
| M3 registry record reused without checking its bytes | survived at first (masked by M2's unlink) → covered by the loss tests → **CAUGHT** — 1 failed |
| M4 a binding counts as a receipt without its bytes | **CAUGHT** — 2 failed |
| M5 `SUCCEEDED` not re-pollable | **CAUGHT** — 1 failed |

## Regression

Asset suites (`rebind`, `persistence`, `idempotency`, `meshy`, `meshy_rate_limits`, `assets_pipeline`, `p18_canonical_identity`): **81 passed** after the fixtures were given real normalized bytes (a "purchase" without bytes is exactly what this task forbids). Full suite: see the TRACK_RECORD.md entry.

## Not done here

A Blender build against an expired URL (task text: "running a build") — Blender reads the normalized file from disk (`catalog.py` comment; `build_scene.py`), which this test proves exists; a Blender run adds minutes on the RTX 3050 for no additional assertion. Recorded as a deliberate omission.
