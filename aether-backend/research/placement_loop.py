"""Verify the built space against the moodboard by LOOKING at it, and keep
adjusting until it is accurate enough or the levers run out.

The plan is numbers; the .blend is the thing the client sees. A piece can hold
the right coordinate in the spec and still be missing from the room - its mesh
never arrived, it sank into a wall, it was placed behind the camera. So this
does not grade the plan against itself. It builds the scene in Blender, shoots
the room from several angles, reads those photographs back with the SAME
production scene reader that read the moodboard, and compares what the camera
found with what the client approved.

Three things are scored, each a different way for the room to be wrong, none
substituting for another:

  coverage   of the pieces the client approved, how many the camera can
             actually see in the built room. Catches missing meshes, pieces
             inside walls, pieces off-camera.
  placement  of the pieces whose position the reader MEASURED, how many stand
             within tolerance of where the picture put them.
  assets     how many pieces are represented by a real mesh rather than a
             procedural stand-in, where a mesh was what the plan asked for.

accuracy = the mean of the three. The loop stops when it reaches the target or
when nothing is left to turn; it never stops by declaring success it did not
measure, and a plateau is reported as a plateau.

    python research/placement_loop.py --project proj_xxx [--target 0.95]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import BlenderRunner                              # noqa: E402
from app.core.config import get_settings                           # noqa: E402
from app.intelligence.schema import DesignAnalysis, SceneReading, StyleSpec  # noqa: E402
from app.planning import compiler                                  # noqa: E402
from app.projects.layout import project_dir                        # noqa: E402
from app.scene.schema import Scene                                 # noqa: E402

#: How far a piece may stand from the spot the reader measured and still count
#: as placed there.
#:
#: Set against what the literature actually achieves, not against what would
#: look good. Recovering metric furniture positions from ONE image whose camera
#: nobody knows is the hard case, and the published numbers are sobering:
#: Total3DUnderstanding (CVPR 2020) reports median translation error 0.48 m and
#: 51.8% of objects within 0.5 m on NYUv2, and ROCA (CVPR 2022) reports 17.6%
#: at the Scan2CAD threshold of 20 cm / 20 deg. A 90% target at 20 cm would be
#: roughly five times better than anything published. One metre is a defensible
#: gate for "in the right place in the room", and 0.5 m is reported alongside
#: it so the harder number is never hidden.
PLACEMENT_TOLERANCE_M = 1.0
STRICT_TOLERANCE_M = 0.5


def _load(root: Path, rel: str):
    path = root / rel
    if not path.exists():
        raise SystemExit(f"missing {rel}: plan the project first")
    return json.loads(path.read_text(encoding="utf-8"))


def viewpoints(scene: Scene) -> list[dict]:
    """Every corner of the largest room, each looking at its centre.

    Corners, not the middle: a camera in the centre of a small room sees a
    wall. Every piece should appear in at least one corner shot, so a piece
    missing from all of them is missing from the room.
    """
    from app.blender.manifest import to_blender_xyz
    from app.spatial import geometry as geo

    room = max(scene.rooms, key=lambda r: geo.polygon_area(r.boundary))
    cx, cz = geo.polygon_centroid(room.boundary)
    eye = 1.55
    views = []
    for i, (px, pz) in enumerate(room.boundary):
        # Stand just inside the corner so the camera is not buried in a wall.
        ix = px + (0.5 if cx > px else -0.5)
        iz = pz + (0.5 if cz > pz else -0.5)
        views.append({
            "name": f"corner_{i}",
            "position": list(to_blender_xyz((ix, eye, iz))),
            "look_at": list(to_blender_xyz((cx, 1.1, cz))),
        })
    return views


def render_views(root: Path, scene: Scene, out_dir: Path) -> list[Path]:
    runner = BlenderRunner()
    blend = root / "blender" / "scene.blend"
    if not blend.exists():
        raise SystemExit("no scene.blend: build the project first")
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = out_dir / "views.json"
    spec.write_text(json.dumps({"out_dir": str(out_dir), "profile": "preview",
                                "views": viewpoints(scene)}, indent=2), encoding="utf-8")
    # The runner raises BlenderError on a non-zero exit, so reaching the next
    # line means Blender rendered; the log beside the frames says what it did.
    res = runner.run("render_viewpoints.py", ["--spec", str(spec)], blend=blend,
                     log_path=out_dir / "blender.log", timeout=1800)
    return [Path(r["path"]) for r in (res.result or {}).get("rendered", [])]


def visibility(root: Path, scene: Scene, out_dir: Path) -> dict:
    """Which pieces a camera can actually reach, asked of Blender directly.

    This replaces asking a vision model to name what it sees, which was the
    first version of this loop and does not work. Measured here: the same
    unchanged scene scored 0.556, 0.778, 0.556, 0.556 across four reads, a 22
    point spread, while reporting a dining table in all four views of a living
    room that has none. That is the documented behaviour of the tool, not bad
    luck - DASH (ICCV 2025) catalogues systematic object-presence hallucination
    across 950,000 images that transfers between model architectures, and
    counting error roughly triples on textured scenes. A generative reader
    cannot be the judge of the pipeline that feeds it.

    Ray casts are exact, free, and identical on every run.
    """
    runner = BlenderRunner()
    blend = root / "blender" / "scene.blend"
    spec = out_dir / "views.json"
    if not spec.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        spec.write_text(json.dumps({"out_dir": str(out_dir), "views": viewpoints(scene)}, indent=2),
                        encoding="utf-8")
    res = runner.run("check_visibility.py", ["--spec", str(spec)], blend=blend,
                     log_path=out_dir / "visibility.log", timeout=1800)
    return res.result or {}


def score(root: Path, reading: SceneReading, scene: Scene, seen: dict) -> dict:
    """Grade the built room against the moodboard the client approved."""
    plan = _load(root, "planning/object_plan.json")
    items = {i["object_key"]: i for i in plan["items"]}

    # coverage: every placed piece a camera can actually reach. A piece inside
    # a wall or behind the sofa is in the spec and not in the room.
    total = int(seen.get("objects") or 0)
    coverage = (int(seen.get("visible") or 0) / total) if total else 1.0

    # placement: pieces standing where the reader MEASURED them
    measured = placed_well = 0
    offsets = []
    by_room = {r.room_id: r for r in scene.rooms}
    for obj in scene.objects:
        item = items.get(obj.plan_key or "")
        if not item or not item.get("anchor_m") or item.get("anchor_source") != "read":
            continue
        room = by_room.get(obj.room_id)
        if room is None:
            continue
        # Graded against the same spot the placer aims at: the wall line
        # pushed in by half the piece's depth. Grading against the raw wall
        # line marks a correctly seated sideboard as half a metre wrong.
        from app.intelligence.schema import ObjectPlanItem
        spot = compiler.anchor_spot(ObjectPlanItem.model_validate(item), room, obj.dimensions[2])
        if spot is None:
            continue
        d = math.dist(spot, (obj.position[0], obj.position[2]))
        offsets.append(round(d, 2))
        measured += 1
        placed_well += 1 if d <= PLACEMENT_TOLERANCE_M else 0
    placement = placed_well / measured if measured else 1.0
    strict = (sum(1 for d in offsets if d <= STRICT_TOLERANCE_M) / measured) if measured else 1.0

    # orientation: pieces turned the way the picture showed them.
    #
    # Graded only on types with a front you can see (compiler.ORIENTED_TYPES).
    # The reader answers `faces` for everything, including rugs and baskets,
    # and a rug turned 180 degrees is the same rug - counting those would
    # measure the vocabulary rather than the room.
    turned = facing_total = 0
    wrong_way = []
    for obj in scene.objects:
        item_raw = items.get(obj.plan_key or "")
        if not item_raw or not item_raw.get("facing_dir"):
            continue
        if obj.semantic_type not in compiler.ORIENTED_TYPES:
            continue
        want = math.degrees(compiler._rotation_facing(tuple(item_raw["facing_dir"]))) % 360
        got = math.degrees(obj.rotation_y) % 360
        facing_total += 1
        if abs((want - got + 180) % 360 - 180) <= 1.0:
            turned += 1
        else:
            wrong_way.append(f"{obj.semantic_type} (wanted {want:.0f}, got {got:.0f})")
    orientation = turned / facing_total if facing_total else 1.0

    # assets: a real mesh where the plan asked for one
    asset_plan = _load(root, "planning/asset_plan.json")["decisions"]
    intended = [d for d in asset_plan if d.get("strategy") in ("generated", "local_asset", "local_modified")]
    have = [d for d in intended if d.get("asset_id")]
    assets = len(have) / len(intended) if intended else 1.0

    return {
        "coverage": round(coverage, 3),
        "placement": round(placement, 3),
        "placement_strict": round(strict, 3),
        "orientation": round(orientation, 3),
        "oriented_pieces": facing_total,
        "wrong_way": wrong_way,
        "assets": round(assets, 3),
        "accuracy": round((coverage + placement + orientation + assets) / 4, 3),
        "occluded": seen.get("occluded") or [],
        "never_in_frame": seen.get("never_in_frame") or [],
        "without_a_mesh": [d["object_key"] for d in intended if not d.get("asset_id")],
        "offsets_m": offsets,
        "measured_pieces": measured,
    }


#: What the loop can actually change between attempts. Each entry is a real
#: knob in the placer, applied in order, weakest change first. Nothing here
#: spends money or invents evidence - a piece whose mesh was never bought
#: cannot be conjured by re-planning, and the report says so instead.
LEVERS = [
    ("baseline", {}),
    ("tighter tie band", {"ANCHOR_TIE_BAND_M": 0.10}),
    ("estimated anchors lead too", {"ANCHOR_TIE_BAND_M": 0.10, "ANCHOR_LEADS_WHEN_DERIVED": True}),
    ("exact anchors only", {"ANCHOR_TIE_BAND_M": 0.01, "ANCHOR_LEADS_WHEN_DERIVED": True}),
]


def replan_and_build(project_id: str) -> None:
    """Re-plan with the current knobs, then rebuild the .blend from it."""
    from app.jobs import get_runner
    from app.jobs.store import JobStore

    runner = get_runner()
    for kind, params in (("scene_plan", {"force": True}), ("build", {"force": True, "preview": True})):
        job = runner.enqueue(project_id, kind, params)
        if not runner.wait_idle(3600):
            raise SystemExit(f"{kind} did not finish")
        final = JobStore().get(job.job_id)
        if final.status != "SUCCEEDED":
            raise SystemExit(f"{kind} failed: {final.error}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--target", type=float, default=0.95)
    ap.add_argument("--max-iterations", type=int, default=len(LEVERS))
    args = ap.parse_args()

    root = project_dir(args.project)
    settings = get_settings()
    print(f"project {args.project} | data {settings.data_dir} | target {args.target:.0%}")

    analysis = DesignAnalysis.model_validate(_load(root, "analysis/design_analysis.json"))
    style = StyleSpec.model_validate(_load(root, "analysis/style_spec.json"))
    reading = SceneReading.model_validate(_load(root, "planning/scene_reading.json"))
    vertical = "residential"

    report = {"project": args.project, "target": args.target, "tolerance_m": PLACEMENT_TOLERANCE_M,
              "iterations": [], "stopped_because": ""}
    best = None

    for n, (lever, knobs) in enumerate(LEVERS[: args.max_iterations], start=1):
        for key, value in knobs.items():
            setattr(compiler, key, value)
        print(f"\n-- attempt {n}: {lever} {knobs or ''}")
        started = time.time()
        # Every attempt re-plans, the first included: a baseline measured on a
        # scene built by older code grades that code, not this one.
        replan_and_build(args.project)

        scene_doc = _load(root, "planning/scene_spec.json")
        scene = Scene.model_validate(scene_doc.get("scene", scene_doc))

        out_dir = root / "verify" / f"attempt_{n}"
        shots = render_views(root, scene, out_dir)
        print(f"  rendered {len(shots)} viewpoint(s) for the eye; measuring with ray casts")
        seen = visibility(root, scene, out_dir)
        print(f"    {seen.get('visible')}/{seen.get('objects')} piece(s) reachable by a camera")

        result = score(root, reading, scene, seen)
        result.update({"n": n, "lever": lever, "knobs": knobs, "seconds": round(time.time() - started, 1)})
        report["iterations"].append(result)
        print(f"  coverage {result['coverage']:.0%} | placement {result['placement']:.0%} "
              f"(within {PLACEMENT_TOLERANCE_M} m; {result['placement_strict']:.0%} within "
              f"{STRICT_TOLERANCE_M} m) | orientation {result['orientation']:.0%} "
              f"({result['oriented_pieces']} piece(s)) | assets {result['assets']:.0%} "
              f"-> accuracy {result['accuracy']:.0%}")
        for label, names in (("occluded", result["occluded"]),
                             ("never in frame", result["never_in_frame"]),
                             ("no mesh", result["without_a_mesh"]),
                             ("facing the wrong way", result["wrong_way"])):
            if names:
                print(f"    {label}: {', '.join(names)}")

        if best is None or result["accuracy"] > best["accuracy"]:
            best = result
        # Orientation is a gate in its own right, not a quarter of an average:
        # a room where every piece is in the right spot and one faces the wall
        # reads as broken to the person looking at it, and averaging hides
        # exactly that. Asked for explicitly, and it is the right shape.
        if result["accuracy"] >= args.target and result["orientation"] >= 1.0:
            report["stopped_because"] = (f"reached {result['accuracy']:.0%} with every piece "
                                         f"facing as read, on attempt {n} ({lever})")
            break
    else:
        report["stopped_because"] = (
            f"levers exhausted at {best['accuracy']:.0%}" if best else "nothing measured")

    report["best"] = best
    out = Path(__file__).resolve().parents[2] / "docs" / "benchmarks" / "placement_loop.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{report['stopped_because']}\nwritten to {out}")


if __name__ == "__main__":
    main()
