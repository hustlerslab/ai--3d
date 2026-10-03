"""P2-RENDER-001: audit every asset and material already in the library.

Two reports, neither of which changes anything:

- assets: each registry asset's NORMALIZED file checked with the same
  `material_workflow` rule ingestion now applies - specular-glossiness (not
  metallic-roughness) is a failure; a material with no metallic-roughness
  values is a warning (glTF defaults would render it as bare metal);
- materials: every registry material that has a roughness MAP, with its
  stored roughness. Since P2-RENDER-001 that value is the factor the map is
  multiplied by (glTF semantics); new scans get 1.0, but a scan registered
  before the change keeps what it had (0.8 unless set), and so now renders a
  little glossier than its scan. This lists them so a person decides.

    python scripts/audit_material_workflow.py
    python scripts/audit_material_workflow.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assets import gltf  # noqa: E402
from app.assets.registry import get_registry  # noqa: E402
from app.assets.validation import material_workflow  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.materials.registry import get_material_registry  # noqa: E402


def audit() -> dict:
    data_dir = get_settings().data_dir
    assets = []
    for record in sorted(get_registry().list(), key=lambda r: r.asset_id):
        path = data_dir / record.files.normalized if record.files.normalized else None
        row = {"asset_id": record.asset_id, "file": record.files.normalized or ""}
        if path is None or not path.is_file():
            row["result"] = "unreadable"
        else:
            issues = material_workflow(gltf.load(path))
            row["result"] = "fail" if any(i.severity == "hard" for i in issues) else (
                "warn" if issues else "ok")
            row["issues"] = [i.message for i in issues]
        assets.append(row)
    mapped = [{"material_id": m.material_id, "roughness_factor": m.roughness,
               "review": m.roughness != 1.0}
              for m in sorted(get_material_registry().list(), key=lambda m: m.material_id)
              if m.maps.roughness]
    return {"assets": assets, "mapped_materials": mapped,
            "summary": {"assets": len(assets),
                        "fail": sum(1 for a in assets if a["result"] == "fail"),
                        "warn": sum(1 for a in assets if a["result"] == "warn"),
                        "unreadable": sum(1 for a in assets if a["result"] == "unreadable"),
                        "mapped_materials_to_review": sum(1 for m in mapped if m["review"])}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path, help="write the report here")
    ns = ap.parse_args()
    report = audit()
    if ns.json:
        ns.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for a in report["assets"]:
        if a["result"] != "ok":
            print(f"{a['result']:>10}  {a['asset_id']}  {'; '.join(a.get('issues', []))}")
    for m in report["mapped_materials"]:
        if m["review"]:
            print(f"    review  {m['material_id']}  roughness factor {m['roughness_factor']} (1.0 = as scanned)")
    print(json.dumps(report["summary"]))
    return 1 if report["summary"]["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
