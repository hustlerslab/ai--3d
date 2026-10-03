"""P1-QA-001 release gate: a release may not ship on MOCK evidence alone.

Reads the per-class JSON reports written by the test runs
(`ALLURE_TEST_REPORT=<file> pytest -m <class>`) and fails unless:

  * class=MOCK ran, with no failures and no errors;
  * class=REAL-PROVIDER ran - at least one live test PASSED - with no failures.

A REAL-PROVIDER run in which every provider was skipped (no keys) did not run,
and the gate says so. Results are reported per class and never summed.

    python scripts/release_gate.py mock.json real.json [production.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def merge(paths: list[str]) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    for p in paths:
        data = json.loads(Path(p).read_text("utf-8"))
        for cls, counts in data.get("classes", {}).items():
            row = merged.setdefault(cls, {"passed": 0, "failed": 0, "error": 0, "skipped": 0})
            for k in row:
                row[k] += int(counts.get(k, 0))
    return merged


def check(classes: dict[str, dict[str, int]]) -> list[str]:
    problems = []
    mock = classes.get("MOCK", {})
    if not sum(mock.values()):
        problems.append("class=MOCK did not run")
    elif mock.get("failed") or mock.get("error"):
        problems.append(f"class=MOCK failed={mock.get('failed')} error={mock.get('error')}")
    real = classes.get("REAL-PROVIDER", {})
    if not real.get("passed"):
        problems.append("class=REAL-PROVIDER did not run (no live test passed - skipped providers do not count)")
    elif real.get("failed") or real.get("error"):
        problems.append(f"class=REAL-PROVIDER failed={real.get('failed')} error={real.get('error')}")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    classes = merge(argv)
    for cls in ("MOCK", "REAL-PROVIDER", "PRODUCTION-PATH"):
        c = classes.get(cls)
        print(f"class={cls} " + (" ".join(f"{k}={v}" for k, v in c.items()) if c and sum(c.values())
                                 else "did not run"))
    problems = check(classes)
    for p in problems:
        print(f"RELEASE GATE: {p}")
    print("RELEASE GATE: " + ("FAIL" if problems else "PASS"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
