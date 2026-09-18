"""Phase 10: audit every registry asset's spatial metadata against its mesh.

    python -u research/spatial_engine/asset_audit.py

Research only. Reads the registry and the normalised GLBs; writes one JSON.

WHAT IS CHECKED, PER ASSET, AND FROM WHAT. The registry record claims
dimensions, a mount type and a normalisation (metres, +Y up, -Z forward,
bottom-centre pivot). The normalised GLB is re-measured with the production
measurer and the two are compared:

    dimensions      record vs measured size, per axis
    origin          bottom-centre pivot: min y ~ 0, x/z centre ~ 0
    scale           the measured size must be furniture-sized in metres
    bounding box    finite, non-degenerate
    mount vs family the record's mount must agree with the vocab's placement
    rotation        NOT verifiable from a mesh alone: whether -Z is the front
                    is a semantic fact. Recorded as unverified, never assumed.

An asset with a hard issue is rejected from the spatial engine's point of view.
The registry itself is not modified.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.assets import gltf                                           # noqa: E402
from app.assets.registry import get_registry                          # noqa: E402
from app.core.config import get_settings                              # noqa: E402
from app.intelligence import vocab as V                               # noqa: E402

OUT = HERE / "asset_audit_results.json"

DIM_TOLERANCE_M = 0.02          # record vs measured, per axis
PIVOT_TOLERANCE_M = 0.02        # bottom-centre pivot
MIN_SIZE_M, MAX_SIZE_M = 0.03, 8.0
MOUNT_FOR_PLACEMENT = {"floor": "floor", "wall": "wall", "ceiling": "ceiling",
                       "on_surface": "surface"}


def audit_one(rec) -> dict:
    issues = []
    data_dir = get_settings().data_dir
    path = data_dir / rec.files.normalized if rec.files.normalized else None
    entry = {"asset_id": rec.asset_id, "semantic_type": rec.semantic_type, "mount": rec.mount,
             "record_dims_m": [round(v, 4) for v in rec.dimensions],
             "normalization_strategy": rec.normalization.strategy,
             "source_provider": rec.source.provider, "license": rec.source.license,
             "registry_valid": rec.valid, "existing_issues": [i.model_dump() for i in rec.validation]}
    if path is None or not path.exists():
        issues.append({"code": "MISSING_NORMALIZED_FILE", "severity": "hard",
                       "message": f"normalized file not found: {rec.files.normalized}"})
        entry.update(issues=issues, accepted=False)
        return entry
    try:
        doc = gltf.load(path)
        m = gltf.measure(doc)
    except Exception as exc:                                       # noqa: BLE001
        issues.append({"code": "UNREADABLE", "severity": "hard", "message": str(exc)[:200]})
        entry.update(issues=issues, accepted=False)
        return entry

    size = m.size
    entry["measured_size_m"] = [round(v, 4) for v in size]
    entry["measured_bbox_min_m"] = [round(v, 4) for v in m.bbox_min]
    entry["measured_bbox_max_m"] = [round(v, 4) for v in m.bbox_max]
    if m.has_nan or any(s <= 0 for s in size):
        issues.append({"code": "DEGENERATE_BBOX", "severity": "hard",
                       "message": "NaN or zero-extent bounding box"})
    dims_err = [abs(size[i] - rec.dimensions[i]) for i in range(3)]
    entry["dims_error_m"] = [round(v, 4) for v in dims_err]
    if max(dims_err) > DIM_TOLERANCE_M:
        issues.append({"code": "DIMENSIONS_MISMATCH", "severity": "hard",
                       "message": f"record {entry['record_dims_m']} vs measured "
                                  f"{entry['measured_size_m']}"})
    cx, cy, cz = m.center
    pivot_err = {"x": round(abs(cx), 4), "y": round(abs(m.bbox_min[1]), 4), "z": round(abs(cz), 4)}
    entry["pivot_error_m"] = pivot_err
    if max(pivot_err.values()) > PIVOT_TOLERANCE_M:
        issues.append({"code": "PIVOT_NOT_BOTTOM_CENTRE", "severity": "hard",
                       "message": f"centre ({cx:.3f}, min-y {m.bbox_min[1]:.3f}, {cz:.3f})"})
    if max(size) > MAX_SIZE_M or (max(size) < 0.2 and min(size) < MIN_SIZE_M):
        issues.append({"code": "SCALE_SUSPECT", "severity": "hard",
                       "message": f"largest extent {max(size):.2f} m"})
    canonical = V.canonical_type(rec.semantic_type, rec.semantic_type)
    expected = MOUNT_FOR_PLACEMENT.get(V.placement_for(canonical, canonical))
    entry["vocab_placement"] = expected
    if expected and expected != rec.mount:
        issues.append({"code": "MOUNT_DISAGREES_WITH_VOCAB", "severity": "warn",
                       "message": f"record mount '{rec.mount}' vs vocab '{expected}'"})
    entry["forward_axis"] = "UNVERIFIED: -Z assumed by normalisation; not checkable from geometry"
    entry["triangles"] = m.triangles
    entry["issues"] = issues
    entry["accepted"] = not any(i["severity"] == "hard" for i in issues)
    return entry


def main() -> int:
    recs = get_registry().list()
    rows = [audit_one(r) for r in recs]
    by_issue = {}
    for r in rows:
        for i in r["issues"]:
            by_issue[i["code"]] = by_issue.get(i["code"], 0) + 1
    summary = {"total": len(rows), "accepted": sum(1 for r in rows if r["accepted"]),
               "rejected": sum(1 for r in rows if not r["accepted"]),
               "by_issue": by_issue,
               "by_mount": {m: sum(1 for r in rows if r["mount"] == m)
                            for m in sorted({r["mount"] for r in rows})},
               "by_provider": {p: sum(1 for r in rows if r["source_provider"] == p)
                               for p in sorted({r["source_provider"] for r in rows})},
               "licenses": sorted({r["license"] for r in rows}),
               "tolerances": {"dims_m": DIM_TOLERANCE_M, "pivot_m": PIVOT_TOLERANCE_M}}
    OUT.write_text(json.dumps({"_about": "Phase 10 asset spatial audit. Registry untouched.",
                               "summary": summary, "assets": rows}, indent=2), encoding="utf-8")
    print(f"assets {summary['total']}  accepted {summary['accepted']}  rejected {summary['rejected']}")
    print(f"issues {by_issue}")
    print(f"mounts {summary['by_mount']}  providers {summary['by_provider']}")
    print(f"licenses {summary['licenses']}")
    for r in rows:
        if r["issues"]:
            print(f"  {r['asset_id']:44} {r['semantic_type']:14} "
                  + "; ".join(f"{i['code']}" for i in r["issues"]))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
