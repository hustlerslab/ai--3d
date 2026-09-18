"""Phase 1g: turn the generated scenes into an annotated wall-contact dataset.

    python -u research/phase1g/build_dataset.py

Research only. Reads the Phase 1d fixture to carry the 11 historical positives
across unchanged; writes nothing into app/ and does not touch that fixture.

EVERY LABEL BELOW CAME FROM LOOKING AT THE IMAGE, not from the prompt that made
it. The generator's `intent_bias` is recorded in the manifest and was
deliberately ignored here - the probe showed SD 1.5 does not obey spatial
instructions (it was asked for an ottoman alone on the floor and returned a
sectional and a rug), so a label taken from the prompt would be fiction.

GROUND TRUTH RULE, applied to every case:
    POSITIVE  the queried object itself physically contacts a wall
    NEGATIVE  it does not
A wall being visible behind the object is NOT part of the rule. It is recorded
separately, because whether the model keys on it is the whole hypothesis.

CATEGORY, applied only to negatives:
    A   genuinely free-standing: no wall-backed mass immediately behind it at
        similar depth, floor visible around it
    B   free-standing, but a wall-backed object or surface sits immediately
        behind it and overlaps it in the image

EXCLUSIONS, applied before counting: objects leaving the frame, objects whose
rear edge cannot be read, rugs, alcove pieces, architectural fittings, and
anything where "against a wall" is ill-posed. Two whole scenes were rejected:
the generator returned vaulted stone halls for them rather than rooms.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = HERE / "scene_manifest.json"
FIXTURE = ROOT / "tests" / "fixtures" / "relationship_benchmark.json"
DATASET = HERE / "dataset.json"
ANNOTATIONS = HERE / "annotations.json"

# object_id, type, bbox(x1,y1,x2,y2 px in 704x448), category,
# wall_visible, wall_backed_mass_present, occlusion, note
NEG = {
    "s01": [
        ("armchair.0", "armchair", [215, 228, 430, 405], "B", True, True, "none",
         "stands on the rug in open floor; the white built-in media unit behind it "
         "is fixed to the wall and overlaps it in frame"),
    ],
    "s02": [
        ("ottoman.0", "ottoman", [78, 222, 252, 352], "A", True, False, "none",
         "stacked pouf forward of the concrete wall; the floor/wall junction is "
         "visible behind and above its base"),
        ("coffee_table.0", "coffee_table", [268, 212, 492, 318], "A", True, False,
         "none", "black drum table standing clear on the floor, space on all sides"),
    ],
    "s03": [
        ("armchair.0", "armchair", [12, 212, 218, 412], "A", True, False, "none",
         "swivel chair on the rug in front of the glazing, floor visible behind it; "
         "no wall-backed piece behind it"),
        ("armchair.1", "armchair", [368, 198, 568, 412], "B", True, True, "none",
         "second swivel chair standing in front of the wall-fixed television "
         "console, which overlaps it in frame"),
    ],
    "s04": [
        ("chair.0", "chair", [222, 212, 302, 342], "B", True, True, "none",
         "drawn up to a desk built against the side wall; carpet visible around "
         "all four legs"),
    ],
    "s05": [
        ("bench.0", "bench", [68, 243, 278, 378], "B", True, True, "none",
         "upholstered bench at the foot of the bed; the bed is wall-backed and "
         "directly behind it"),
        ("armchair.0", "armchair", [488, 168, 692, 368], "A", True, False, "none",
         "white chair standing on the rug clear of the right wall; the wall/floor "
         "line is visible behind it"),
    ],
    "s06": [
        ("bar_stool.0", "bar_stool", [52, 282, 145, 448], "B", True, True,
         "feet reach the lower frame edge",
         "pulled up to the island; the fitted cabinet run along the back wall and "
         "the island mass are both behind it"),
        ("bar_stool.1", "bar_stool", [162, 285, 252, 448], "B", True, True,
         "feet reach the lower frame edge", "as bar_stool.0"),
        ("bar_stool.2", "bar_stool", [272, 288, 362, 448], "B", True, True,
         "feet reach the lower frame edge", "as bar_stool.0"),
        ("bar_stool.3", "bar_stool", [402, 290, 502, 448], "B", True, True,
         "feet reach the lower frame edge", "as bar_stool.0"),
    ],
    "s07": [
        ("bar_stool.0", "bar_stool", [192, 332, 285, 448], "B", True, True,
         "feet reach the lower frame edge",
         "at the navy island, with the wall-backed counter run beyond it"),
        ("bar_stool.1", "bar_stool", [438, 332, 528, 448], "B", True, True,
         "feet reach the lower frame edge", "as bar_stool.0"),
    ],
    "s08": [
        ("dining_table.0", "dining_table", [112, 272, 442, 432], "A", True, False,
         "none", "table standing in the middle of the floor, clear floor around "
                 "its base on the near and left sides"),
        ("chair.0", "chair", [418, 282, 478, 405], "B", True, True, "none",
         "chair between the table and the sideboard; the sideboard is against the "
         "right wall and directly behind it"),
    ],
    "s09": [
        ("chair.0", "chair", [312, 182, 492, 398], "B", True, True, "none",
         "leather desk chair on a rug, castors clear of the floor-standing "
         "joinery; the desk and shelving behind it are built against the wall"),
    ],
    "s10": [
        ("chair.0", "chair", [32, 278, 112, 368], "B", True, True, "none",
         "task chair at a desk run that follows the window wall"),
        ("chair.1", "chair", [452, 272, 505, 338], "A", True, False,
         "small in frame",
         "task chair at a desk island in the middle of the floor plate, metres "
         "from any wall"),
        ("chair.2", "chair", [368, 268, 412, 322], "A", True, False,
         "small in frame", "as chair.1"),
    ],
    "s11": [
        ("ottoman.0", "ottoman", [228, 288, 352, 392], "A", True, False, "none",
         "pale ottoman in the middle of the carpet, seating island layout"),
        ("armchair.0", "armchair", [248, 232, 332, 322], "A", True, False, "none",
         "armchair in the seating island, walls far in the background"),
        ("armchair.1", "armchair", [502, 262, 658, 432], "A", True, False, "none",
         "timber-framed armchair standing free on the carpet"),
        ("armchair.2", "armchair", [368, 238, 458, 332], "A", True, False, "none",
         "armchair in the seating island"),
    ],
    "s13": [
        ("armchair.0", "armchair", [478, 172, 628, 268], "A", True, False, "none",
         "red leather lounge chair standing free on the boards, floor visible all "
         "round, concrete wall well beyond it"),
    ],
    "s14": [
        ("bench.0", "bench", [368, 272, 562, 398], "B", True, True, "none",
         "white bench at the foot of the bed, floorboards visible under and around "
         "it; the bed behind it is against the wall"),
    ],
    "s15": [
        ("dining_table.0", "dining_table", [228, 192, 548, 402], "A", True, False,
         "none", "butcher block table on castors in the centre of the room, wide "
                 "floor on every side"),
    ],
    "s16": [
        ("dining_table.0", "dining_table", [382, 298, 512, 432], "A", True, False,
         "none", "round cafe table standing in open floor between the window wall "
                 "and the right-hand bench"),
        ("chair.0", "chair", [488, 262, 562, 378], "B", True, True, "none",
         "chair in front of the bench seat that runs along the panelled wall"),
    ],
    "s17": [
        ("chair.0", "chair", [292, 272, 378, 392], "A", True, False, "none",
         "task chair on the yellow carpet at a mid-floor desk cluster; the glass "
         "partition is well beyond it"),
        ("chair.1", "chair", [382, 268, 458, 368], "A", True, False, "none",
         "as chair.0"),
        ("chair.2", "chair", [202, 268, 268, 358], "A", True, False, "none",
         "as chair.0"),
    ],
}

REJECTED = [
    {"scene_id": "s12", "object": "WHOLE SCENE", "reason":
     "the generator returned a vaulted stone hall with arches and columns, not a "
     "lounge. The only movable pieces are a stone bench in a niche and a small "
     "dark box; neither has a readable wall relationship."},
    {"scene_id": "s18", "object": "WHOLE SCENE", "reason":
     "vaulted hall with rows of pews rather than a reception lounge; pieces are "
     "small, low-contrast and cropped at the frame edges."},
    {"scene_id": "s01", "object": "armchair left foreground", "reason":
     "its back sits against the timber wall below the television and the gap, if "
     "any, is not visible; wall contact cannot be settled"},
    {"scene_id": "s02", "object": "round white table right", "reason": "leaves the right frame edge"},
    {"scene_id": "s02", "object": "pale bench behind the drum table", "reason": "occluded by the drum table"},
    {"scene_id": "s04", "object": "bench at the foot of the bed", "reason": "leaves the right frame edge"},
    {"scene_id": "s07", "object": "bar stool, leftmost", "reason": "leaves the left frame edge"},
    {"scene_id": "s13", "object": "coffee table", "reason": "leaves the left frame edge"},
    {"scene_id": "s13", "object": "side table right", "reason": "leaves the right frame edge"},
    {"scene_id": "s08", "object": "foreground chairs", "reason":
     "seat and legs run off the lower frame edge and overlap each other"},
    {"scene_id": "all", "object": "rugs", "reason":
     "a rug lies on the floor and meets walls at its edges; the wall question is "
     "degenerate, and Phase 1d eligibility already excluded rugs"},
]


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    scenes = {s["scene_id"]: s for s in manifest["scenes"]}

    cases, annotations = [], []
    for scene_id, rows in NEG.items():
        scene = scenes[scene_id]
        for object_id, otype, bbox, category, wall_vis, mass, occl, note in rows:
            case_id = f"{scene_id}.{object_id}"
            cases.append({
                "case_id": case_id, "scene_id": scene_id,
                "image_path": scene["path"], "object_id": object_id,
                "object_type": otype, "bbox": bbox, "category": category,
                "ground_truth_against_wall": False,
                "origin": "phase1g", "room_type": scene["room_type"],
            })
            annotations.append({
                "case_id": case_id, "scene_id": scene_id,
                "object_id": object_id, "object_type": otype,
                "category": category, "ground_truth_against_wall": False,
                "wall_visible": wall_vis,
                "wall_backed_mass_present": mass,
                "queried_object_touching_wall": False,
                "visual_occlusion": occl,
                "annotation_notes": note,
            })

    # ── the 11 historical positives, carried across unchanged ──────────
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    preserved = 0
    for room in fixture["rooms"]:
        by_id = {o["id"]: o for o in room["objects"]}
        for truth in room.get("binary_relations", []):
            if (truth["chain"] == "against" and truth["verdict"] == "TRUE"
                    and truth.get("wall") is True):
                obj = by_id[truth["source"]]
                cases.append({
                    "case_id": f"preserved.{obj['id']}",
                    "scene_id": f"hist_{room['room_key']}",
                    "image_path": room["image"], "object_id": obj["id"],
                    "object_type": obj["type"], "bbox": obj["bbox"],
                    "category": None, "ground_truth_against_wall": True,
                    "origin": "preserved_phase1d", "room_type": room["room_type"],
                })
                preserved += 1

    negatives = [c for c in cases if not c["ground_truth_against_wall"]]
    cat = Counter(c["category"] for c in negatives)
    per_scene = defaultdict(Counter)
    for c in negatives:
        per_scene[c["scene_id"]][c["category"]] += 1

    scene_rows = [{"scene_id": sid, "room_type": scenes[sid]["room_type"],
                   "image": scenes[sid]["path"], "seed": scenes[sid]["seed"],
                   "source": "generated by app.providers.local_image (SD 1.5), "
                             "Phase 1g",
                   "negatives": sum(per_scene[sid].values()),
                   "A": per_scene[sid]["A"], "B": per_scene[sid]["B"]}
                  for sid in sorted(NEG)]

    quality = {
        "total_scenes_generated": len(scenes),
        "scenes_contributing_cases": len(NEG),
        "scenes_rejected_whole": sum(1 for r in REJECTED if r["object"] == "WHOLE SCENE"),
        "total_candidate_negatives": len(negatives) + len(REJECTED),
        "valid_negatives": len(negatives),
        "rejected_cases": len(REJECTED),
        "category_A": cat["A"], "category_B": cat["B"],
        "preserved_positives": preserved,
        "scenes_with_A": sum(1 for s in per_scene.values() if s["A"]),
        "scenes_with_B": sum(1 for s in per_scene.values() if s["B"]),
        "scenes_with_both": sum(1 for s in per_scene.values() if s["A"] and s["B"]),
        "max_negatives_from_one_scene": max(sum(s.values()) for s in per_scene.values()),
        "checks": {
            "at_least_8_scenes": len(NEG) >= 8,
            "at_least_25_negatives": len(negatives) >= 25,
            "A_and_B_balanced_within_60_40":
                0.4 <= cat["A"] / max(1, len(negatives)) <= 0.6,
            "neither_category_confined_to_one_scene":
                sum(1 for s in per_scene.values() if s["A"]) > 1
                and sum(1 for s in per_scene.values() if s["B"]) > 1,
            "scene_does_not_determine_category":
                sum(1 for s in per_scene.values() if s["A"] and s["B"]) >= 4,
        },
    }

    DATASET.write_text(json.dumps({
        "_about": "Phase 1g wall-contact benchmark. Negatives are newly generated "
                  "and hand-annotated; the 11 positives are carried across from "
                  "Phase 1d/1e/1f unchanged and are marked origin=preserved_phase1d.",
        "_ground_truth_rule": "POSITIVE = the queried object itself physically "
                              "contacts a wall. NEGATIVE = it does not. A wall "
                              "visible behind the object is not part of the rule.",
        "_category_rule": "A = no wall-backed mass immediately behind at similar "
                          "depth. B = a wall-backed object or surface sits "
                          "immediately behind and overlaps it in frame.",
        "image_size": [704, 448],
        "quality": quality, "scenes": scene_rows, "cases": cases,
    }, indent=2), encoding="utf-8")

    ANNOTATIONS.write_text(json.dumps({
        "_about": "Per-case observational evidence for every Phase 1g negative, "
                  "plus every candidate that was rejected and why. Labels were "
                  "taken from the image, never from the generating prompt.",
        "cases": annotations, "rejected": REJECTED,
    }, indent=2), encoding="utf-8")

    print(f"scenes generated      : {quality['total_scenes_generated']}")
    print(f"scenes contributing   : {quality['scenes_contributing_cases']}")
    print(f"candidate negatives   : {quality['total_candidate_negatives']}")
    print(f"VALID NEGATIVES       : {quality['valid_negatives']}")
    print(f"  category A          : {quality['category_A']}")
    print(f"  category B          : {quality['category_B']}")
    print(f"rejected              : {quality['rejected_cases']} "
          f"({quality['scenes_rejected_whole']} whole scenes)")
    print(f"preserved positives   : {quality['preserved_positives']}")
    print(f"scenes with A / B / both: {quality['scenes_with_A']} / "
          f"{quality['scenes_with_B']} / {quality['scenes_with_both']}")
    print(f"max from one scene    : {quality['max_negatives_from_one_scene']}")
    print("\nchecks:")
    for name, ok in quality["checks"].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\nwrote {DATASET}\nwrote {ANNOTATIONS}")
    return 0 if all(quality["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
