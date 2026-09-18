"""Phase 0f: what repetition threshold should abort a generation?

    python research/phase0f_threshold.py

Offline. No GPU, no Ollama, no network - it replays two REAL captured failures
byte for byte and asks, for each candidate threshold: where would the abort have
fired, and how much of the real answer had arrived by then?

The threshold must satisfy two things at once:

  * fire early enough to save the ~190s the loop costs, and
  * never fire before every DISTINCT object has been seen, or the guard would
    throw away content the model correctly found.

The second is the one that decides it. A threshold that saves 95% of the time
but drops a sofa is worse than no guard.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CASES = [("scene read", FIXTURES / "truncated_scene_read.txt", "elements"),
         ("object plan", FIXTURES / "truncated_object_plan.txt", "items")]
THRESHOLDS = (2, 3, 5, 10)


def fingerprint(obj: dict):
    """Identical to the rule `salvage_elements` already dedupes on."""
    return (obj.get("object_key")
            or (obj.get("semantic_type"), json.dumps(obj.get("bbox"))))


def walk(text: str, key: str):
    """Yield (char_offset, parsed_object) as each complete {...} closes.

    Mirrors the streaming case: the detector only ever sees a prefix of the
    answer, so it must decide on objects as they arrive.
    """
    start = text.find(f'"{key}"')
    if start < 0:
        return
    opening = text.find("[", start)
    if opening < 0:
        return
    depth, buf = 0, ""
    for offset, ch in enumerate(text[opening + 1:], start=opening + 1):
        if ch == "{":
            depth += 1
        if depth:
            buf += ch
        if ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    yield offset, json.loads(buf)
                except json.JSONDecodeError:
                    pass
                buf = ""


def main() -> int:
    for label, path, key in CASES:
        if not path.is_file():
            print(f"{label}: MISSING {path}")
            continue
        text = path.read_text(encoding="utf-8")
        objects = list(walk(text, key))
        distinct_total = len({fingerprint(o) for _, o in objects})

        # Where did the LAST new distinct object arrive? An abort before this
        # point loses content; an abort after it is pure saving.
        seen, last_new_at = set(), 0
        for offset, obj in objects:
            fp = fingerprint(obj)
            if fp not in seen:
                seen.add(fp)
                last_new_at = offset

        print(f"\n=== {label} - {path.name} ===")
        print(f"  {len(text):,} chars | {len(objects)} objects | {distinct_total} distinct")
        print(f"  last NEW object arrived at char {last_new_at:,} "
              f"({100 * last_new_at / len(text):.1f}% through the response)")
        print(f"  {'thresh':>6} {'fires at':>10} {'% of text':>10} {'distinct by then':>17} {'lost':>5}")
        for threshold in THRESHOLDS:
            counts: dict = {}
            seen_now, fired_at, distinct_at_fire = set(), None, 0
            for offset, obj in objects:
                fp = fingerprint(obj)
                seen_now.add(fp)
                counts[fp] = counts.get(fp, 0) + 1
                if counts[fp] >= threshold:
                    fired_at, distinct_at_fire = offset, len(seen_now)
                    break
            if fired_at is None:
                print(f"  {threshold:>6} {'never':>10} {'-':>10} {distinct_total:>17} {0:>5}")
                continue
            lost = distinct_total - distinct_at_fire
            print(f"  {threshold:>6} {fired_at:>10,} {100 * fired_at / len(text):>9.1f}% "
                  f"{distinct_at_fire:>17} {lost:>5}"
                  + ("   <-- LOSES CONTENT" if lost else ""))
    print("\nA threshold is only usable where `lost` is 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
