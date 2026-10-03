# P2-VIEWER-001 — Object selection with identity · verification

**2026-09-26 · Hat:** Frontend Engineer (+ 3D Engineer) · **Meshy spend: 0**

## Found: the viewer was re-laying-out the room

`scene-meshes.tsx` had a `mountOffsetY` rule. It lifted every ceiling piece to `ceiling − height − 0.05` whatever height the scene held, and moved any wall piece stored below 0.2 m to eye level. The compiler stands curtains on the floor (y = 0, mount "wall") and Blender renders them there. **So in every compiled scene with curtains, the viewer floated them 15 cm off the floor.** Measured on a real compiled scene: 3 of 4 wall pieces were moved. The viewer, the Blender render and the render verifier disagreed about the same room.

Checked before removing it: the one scene the app ships ready-made, the seed demo apartment, has no ceiling or wall pieces that depended on the lift, and the compiler already computes correct heights. The rule now lives in one exported function, `objectTransform`, which returns the scene's position, rotation and scale **unchanged**.

## Built

| Where | What |
|---|---|
| `walkthrough3d/components/scene-meshes.tsx` | `objectTransform(obj)`, the scene's transform exactly; the lift is removed |
| `walkthrough3d/components/identity-panel.tsx` (new) | The Inspector's **five answers**: **Name**; **Size** (W × H × D, scale applied); **Material** (the client's own word from their reference, e.g. "Linen", else the style material assigned, else "Not specified"); **Kept or new** ("Yours - kept, not built" / "New - made for this design" / "from the catalogue" / "a simple stand-in shape"); **Origin**, from the provenance chain (P1-IDENTITY-005): "From your photo" **with the photo shown**, "From the moodboard you approved", "Chosen by the planner - not from one of your photos", or an honest "couldn't be traced" |
| `walkthrough3d/api/aether-api.ts` | `getProvenance`, typed from the generated contract and registered in the frontend contract test |
| `walkthrough3d/utils/webgl.ts` + the view | **Degrades with a clear message.** WebGL is probed before the canvas mounts; without it the person reads "This browser or graphics card can't show the 3D view. The 360° tour and the rendered pictures still work." instead of a blank box. A lost graphics context (a laptop running out of GPU memory) shows its own message |
| `walkthrough3d/__fixtures__/compiled-scene.json` | A **real** compiled scene (40 pieces: 29 floor, 7 on-surface, 4 wall), written by the backend's own compiler, so the position test checks what the pipeline actually produces |

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Clicking an object shows all five fields | rendered test: name, size, material, kept or new, and origin all present, with the source photo's thumbnail; no internal id in the visible text |
| **Viewer object positions equal scene positions within float tolerance; the viewer never re-lays-out** | every one of the 40 real compiled pieces is drawn at exactly its scene position, rotation and scale (exact equality, stricter than a tolerance); a dedicated test keeps floor-standing curtains on the floor |
| Loads on a mid-range laptop or degrades with a clear message | WebGL probe tests (present, absent, probe throws) plus the two plain messages. Whether it *loads* on a given laptop is a browser measurement; see Owed |

## Mutations (5/5 caught, each restored sha1-identical)

| Mutation | Caught by |
|---|---|
| the viewer lifts wall pieces again | both position tests |
| the Material row dropped | the five-answers test |
| origin claims a photo it doesn't have | the origin-honesty test |
| WebGL assumed present | the WebGL probe test |
| provenance asked of the wrong route | the frontend contract test (P1-FRONTEND-003) |

## Full

Frontend `tsc` + `next lint` clean, **vitest 142 passed** (+10) · generated types current · no backend code changed.

## Owed

- **Screenshot of a selected object with its chain**, and a load test on a mid-range laptop. Both need the running studio in a signed-in browser, which this agent does not create. Covered by the rendered tests and the real-scene position test.
