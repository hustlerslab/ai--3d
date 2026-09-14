# research/

Probes that were run, measured and written up — kept as reference, **not part of
the pipeline**. Nothing in `app/` imports from here, and nothing here runs as
part of a job; each file exists so a conclusion in `docs/` can be re-checked
rather than re-argued.

The distinction from `scripts/`: those are operational tools you run to get
something done (wait on a job, backfill a web variant, source the library).
These are records of an experiment.

| file | question it answered | written up in |
|---|---|---|
| `depth_from_scene.py` | Can a depth map be built from the planner's own geometry, with no renderer and no estimator? | ADR-004 |
| `controlnet_probe.py` | Does conditioning generation on that geometry hold the layout, and what does it cost? | ADR-004 |
| `probe_image_to_3d.py` | Does Meshy image-to-3D produce usable meshes from moodboard crops? | ADR-003 §8 |

Each answered its question and stopped. Two of them reached the same wall from
different directions — generated geometry can be made structurally correct and
still not be the client's actual furniture — which is the open product question
in ADR-003 §9.
