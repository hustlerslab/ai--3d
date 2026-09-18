"""Which identity key merges the three stools without merging the two beds?

The production key is `room | type | box-centre`. Its own comment says three
bar stools should be "three placements of one stool, one generation", and the
real project shows it buying the stool three times, because three stools along
a counter have three centres. The fix is obvious in outline - take position
out of the key - and dangerous in detail: a key with too little in it merges
two plainly different beds into one (documented), and merging is worse than
buying twice.

So the choice is measured, not argued. Every candidate key is run over the
real project's 26 elements plus golden cases with known ground truth, and
scored on false merges (two different pieces, one key) and false splits (one
piece, two keys). The key with the fewest false merges wins; ties break on
false splits. Never the other way round.

    python -u research/element-first/identity_ablation.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "aether-backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.intelligence.schema import SceneElement                            # noqa: E402
from app.intelligence.scene_reading import shape_key                        # noqa: E402

OUT = Path(__file__).resolve().parent / "identity-ablation.json"
REAL = ROOT / "data" / "projects" / "proj_553cb09794" / "planning" / "scene_reading.json"


# ── candidate keys ───────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def _dims_bucket(el: SceneElement) -> str:
    """Dimensions to the nearest 10 cm, so a 44 cm and a 46 cm stool agree."""
    if not el.dimensions_m:
        return ""
    return "x".join(f"{round(v * 10) / 10:.1f}" for v in el.dimensions_m)


def k1_centre(el: SceneElement) -> str:
    """Experiment 1: production. Position IN the key."""
    return shape_key(el)


def k2_room_type(el: SceneElement) -> str:
    """Experiment 2: position removed, nothing added."""
    return f"{el.room_id}|{el.semantic_type}"


def k3_type_only(el: SceneElement) -> str:
    """Experiment 3: semantic identity across rooms."""
    return el.semantic_type


def k4_room_type_dims(el: SceneElement) -> str:
    """Experiment 4: + dimensions."""
    return f"{el.room_id}|{el.semantic_type}|{_dims_bucket(el)}"


def k5_room_type_dims_visual(el: SceneElement) -> str:
    """Experiment 5: + material + colour."""
    return f"{el.room_id}|{el.semantic_type}|{_dims_bucket(el)}|{_norm(el.material)}|{_norm(el.color)}"


def k5c_conservative(el: SceneElement) -> str:
    """Experiment 5c: as K5, but with NO positive evidence the piece keeps its
    own key. Two same-type pieces in one room that both say nothing about
    material or colour are not known to be the same - and an unknown must not
    merge (spec section 6: "If identity is uncertain: preserve separate
    elements")."""
    if not (_norm(el.material) or _norm(el.color) or _dims_bucket(el)):
        return f"{el.room_id}|{el.semantic_type}|?{el.element_id}"
    return k5_room_type_dims_visual(el)


KEYS = {
    "K1_centre_production": k1_centre,
    "K2_room_type": k2_room_type,
    "K3_type_only": k3_type_only,
    "K4_room_type_dims": k4_room_type_dims,
    "K5_room_type_dims_visual": k5_room_type_dims_visual,
    "K5c_conservative": k5c_conservative,
}


# ── cases with ground truth ──────────────────────────────────────────────
#
# `truth` maps element_id -> canonical group label. Two elements share a label
# iff they are the same physical design and should share one asset.

def _el(eid, room, stype, name="", material="", color="", dims=None, bbox=None) -> SceneElement:
    return SceneElement(element_id=eid, room_id=room, semantic_type=stype, name=name,
                        material=material, color=color, dimensions_m=dims,
                        bbox=bbox or (0.1, 0.1, 0.2, 0.2), check="ok")


def real_project() -> tuple[list[SceneElement], dict[str, str]]:
    """The 26 real elements. Ground truth read off the moodboard rooms: the
    three black bar stools are one design; the two master-bedroom pillows are
    one design; the two beds are in different rooms and are plainly different
    beds (documented); everything else is a singleton."""
    data = json.loads(REAL.read_text(encoding="utf-8"))
    els = [SceneElement.model_validate(e) for e in data["elements"]]
    truth: dict[str, str] = {}
    for el in els:
        if el.room_id == "kitchen" and el.semantic_type == "bar_stool":
            truth[el.element_id] = "kitchen.stool"
        elif el.room_id == "master_bedroom" and el.semantic_type == "pillows":
            truth[el.element_id] = "master.pillow"
        else:
            truth[el.element_id] = el.element_id
    return els, truth


def golden_three_stools() -> tuple[list[SceneElement], dict[str, str]]:
    """Section 24: three identical stools, three positions, ONE element."""
    els = [_el(f"s{i}", "kitchen", "bar_stool", "black bar stool", "plastic", "#111111",
               bbox=(0.1 + 0.3 * i, 0.5, 0.2 + 0.3 * i, 0.8)) for i in range(3)]
    return els, {e.element_id: "stool" for e in els}


def golden_three_chairs_different_upholstery() -> tuple[list[SceneElement], dict[str, str]]:
    """Section 25: similar chairs, different upholstery, MORE than one element."""
    els = [
        _el("c1", "dining", "dining_chair", "dining chair", "linen", "#D8CFC0"),
        _el("c2", "dining", "dining_chair", "dining chair", "velvet", "#2E4A3F"),
        _el("c3", "dining", "dining_chair", "dining chair", "leather", "#5A3A2A"),
    ]
    return els, {"c1": "linen", "c2": "velvet", "c3": "leather"}


def golden_two_beds_two_rooms() -> tuple[list[SceneElement], dict[str, str]]:
    """The documented false merge: one bed per bedroom, plainly different."""
    els = [
        _el("b1", "master_bedroom", "bed", "upholstered bed", "fabric and wood", "#F8F9FA"),
        _el("b2", "second_bedroom", "bed", "bed", "", ""),
    ]
    return els, {"b1": "master", "b2": "second"}


def golden_no_evidence_pair() -> tuple[list[SceneElement], dict[str, str]]:
    """Two same-type pieces, one room, NO attributes on either. Unknown whether
    they are the same. Ground truth: treat as different, because a wrong merge
    costs more than a second generation."""
    els = [_el("n1", "living_room", "side_table", "side table"),
           _el("n2", "living_room", "side_table", "side table")]
    return els, {"n1": "a", "n2": "b"}


def golden_six_matching_chairs() -> tuple[list[SceneElement], dict[str, str]]:
    """Six dining chairs with identical evidence: ONE element, six instances."""
    els = [_el(f"d{i}", "dining", "dining_chair", "oak dining chair", "oak", "#B08D57",
               dims=(0.45, 0.9, 0.5), bbox=(0.05 + 0.15 * i, 0.4, 0.12 + 0.15 * i, 0.7))
           for i in range(6)]
    return els, {e.element_id: "chair" for e in els}


CASES = {
    "real_project": real_project,
    "golden_three_stools": golden_three_stools,
    "golden_chairs_different_upholstery": golden_three_chairs_different_upholstery,
    "golden_two_beds_two_rooms": golden_two_beds_two_rooms,
    "golden_no_evidence_pair": golden_no_evidence_pair,
    "golden_six_matching_chairs": golden_six_matching_chairs,
}


# ── scoring ──────────────────────────────────────────────────────────────

def score(keyfn, els: list[SceneElement], truth: dict[str, str]) -> dict:
    by_key: dict[str, list[str]] = defaultdict(list)
    for el in els:
        by_key[keyfn(el)].append(el.element_id)

    # false merge: a key holding two different truth labels
    false_merges = sum(1 for ids in by_key.values()
                       if len({truth[i] for i in ids}) > 1)
    # false split: a truth label spread over more than one key
    keys_per_truth: dict[str, set[str]] = defaultdict(set)
    for key, ids in by_key.items():
        for i in ids:
            keys_per_truth[truth[i]].add(key)
    false_splits = sum(len(keys) - 1 for keys in keys_per_truth.values())

    truth_groups = len(set(truth.values()))
    return {"groups": len(by_key), "ideal_groups": truth_groups,
            "false_merges": false_merges, "false_splits": false_splits,
            "assets_generated": len(by_key),
            "assets_wasted": max(0, len(by_key) - truth_groups)}


def main() -> int:
    report = {"_about": __doc__.strip().splitlines()[0], "keys": {}, "cases": {}}
    print(f"{'key':28s}" + "".join(f"{c[:20]:>22s}" for c in CASES) + f"{'TOTAL fm/fs':>14s}")
    for kname, keyfn in KEYS.items():
        totals = {"false_merges": 0, "false_splits": 0, "assets_wasted": 0}
        line = f"{kname:28s}"
        for cname, build in CASES.items():
            els, truth = build()
            s = score(keyfn, els, truth)
            report["cases"].setdefault(cname, {})[kname] = s
            for k in totals:
                totals[k] += s[k]
            line += f"{s['false_merges']:>10d}fm{s['false_splits']:>6d}fs   "
        report["keys"][kname] = totals
        line += f"{totals['false_merges']:>7d}/{totals['false_splits']:<5d}"
        print(line)

    # decision rule: fewest false merges, then fewest false splits
    ranked = sorted(report["keys"].items(),
                    key=lambda kv: (kv[1]["false_merges"], kv[1]["false_splits"]))
    report["selected"] = ranked[0][0]
    report["rule"] = "fewest false merges, then fewest false splits; never the reverse"
    print(f"\nselected: {report['selected']}  ({report['rule']})")

    real = report["cases"]["real_project"]
    print(f"real project, assets generated: production {real['K1_centre_production']['assets_generated']}"
          f" -> selected {real[report['selected']]['assets_generated']}"
          f" (ideal {real['K1_centre_production']['ideal_groups']})")

    OUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
