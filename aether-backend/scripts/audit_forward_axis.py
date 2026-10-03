"""P1-ASSET-005: measure the forward axis of every asset in the registry.

Reads each record's ORIGINAL file - the bytes as delivered, before the ingest
yaw was baked in - and reports the yaw the ingest heuristic would store next
to the yaw the record carries. The registry is not touched: this is the
report that says whether the assets already in the library agree with the
measurement, and which ones a renormalize would turn.

    python scripts/audit_forward_axis.py            # table on stdout
    python scripts/audit_forward_axis.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assets import gltf, orientation  # noqa: E402
from app.assets.registry import get_registry  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="write the per-asset report here")
    args = parser.parse_args()

    data_dir = get_settings().data_dir
    rows = []
    for record in sorted(get_registry().list(), key=lambda r: r.asset_id):
        original = data_dir / record.files.original if record.files.original else None
        row = {
            "asset_id": record.asset_id,
            "semantic_type": record.semantic_type,
            "provider": record.source.provider,
            "stored_yaw": record.normalization.yaw_offset,
            "stored_source": record.normalization.yaw_source,
            "rule": orientation.FACING_RULE.get(record.semantic_type, ""),
        }
        if original is None or not original.is_file():
            row["measured_yaw"] = None
            row["note"] = "original missing"
        else:
            try:
                row["measured_yaw"] = orientation.measure_forward_yaw(gltf.load(original), record.semantic_type)
            except Exception as exc:                        # noqa: BLE001
                row["measured_yaw"] = None
                row["note"] = f"unreadable: {exc}"
        measured = row.get("measured_yaw")
        row["agrees"] = measured is not None and abs(measured - row["stored_yaw"]) < 1e-6
        rows.append(row)

    print(f"{'asset_id':<40} {'type':<14} {'prov':<9} {'rule':<9} {'stored':>8} {'measured':>9}  agrees")
    for r in rows:
        m = "   -    " if r["measured_yaw"] is None else f"{math.degrees(r['measured_yaw']):7.1f}°"
        print(f"{r['asset_id']:<40} {r['semantic_type']:<14} {r['provider']:<9} {r['rule'] or '-':<9} "
              f"{math.degrees(r['stored_yaw']):7.1f}° {m:>9}  {'yes' if r['agrees'] else 'NO'}"
              f"{('  ' + r['note']) if r.get('note') else ''}")

    with_rule = [r for r in rows if r["rule"]]
    disagree = [r for r in with_rule if r["measured_yaw"] is not None and not r["agrees"]]
    print(f"\n{len(rows)} assets · {len(with_rule)} with a facing rule · "
          f"{len(disagree)} where the measurement disagrees with the stored yaw")

    if args.json:
        args.json.write_text(json.dumps({"assets": rows, "summary": {
            "total": len(rows), "with_facing_rule": len(with_rule), "disagree": len(disagree),
        }}, indent=2), "utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
