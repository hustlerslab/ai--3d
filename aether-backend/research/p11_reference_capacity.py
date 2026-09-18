"""P11 probe: what is Gemini's REAL capacity for reference images?

`gemini_provider._image_parts` caps references at a hardcoded `limit=6` while
uploads allow 12 (`projects_routes.MAX_REFERENCES`). Unlike every other tuned
constant in `app/core/config.py`, that 6 carries no measurement. This probe
supplies one: it sends the analyze_input payload at increasing reference counts
against the real API and records success, HTTP status, token usage and latency,
so the production default can be set from evidence instead of a guess.

Research only - nothing in `app/` imports this. Read-only on project data;
writes one report to docs/benchmarks/p11_reference_capacity.json.

    python -u research/p11_reference_capacity.py [project_id]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.intelligence.bundle import build_input_bundle  # noqa: E402
from app.intelligence.images import encode_for_gemini  # noqa: E402
from app.intelligence.prompts import analysis_prompt, analysis_schema, gemini_schema  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else "proj_553cb09794"
OUT = ROOT.parent / "docs" / "benchmarks" / "p11_reference_capacity.json"
COUNTS = (6, 8, 10, 12)


def main() -> int:
    settings = get_settings()
    if not settings.gemini_configured:
        print("GEMINI_API_KEY not configured; cannot measure. Aborting.")
        return 2

    bundle = build_input_bundle(PROJECT)
    encoded = []
    for ref in bundle.references:
        e = encode_for_gemini(ref.path, max_side=1024)
        if e is not None:
            encoded.append(e)
    print(f"project {PROJECT}: {len(bundle.references)} references, {len(encoded)} encoded")
    if not encoded:
        print("no encodable references; aborting.")
        return 2

    model = settings.gemini_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    schema = gemini_schema(analysis_schema(bundle.vertical))
    results = []

    with httpx.Client(timeout=settings.gemini_timeout_seconds) as client:
        for n in COUNTS:
            # Repeat the real set when asking for more than the project has: the
            # question is payload capacity, not image variety.
            chosen = [encoded[i % len(encoded)] for i in range(n)]
            parts = [{"text": analysis_prompt(bundle)}]
            parts += [{"inline_data": {"mime_type": m, "data": d}} for m, d in chosen]
            parts.append({"text": f"{n} reference photo(s) attached above."})
            body = {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": schema,
                    "temperature": 0.2,
                },
            }
            payload_mb = len(json.dumps(body).encode()) / 1e6
            t0 = time.perf_counter()
            row = {"n_images": n, "payload_mb": round(payload_mb, 2)}
            try:
                r = client.post(url, params={"key": settings.gemini_api_key.get_secret_value()}, json=body)
                row["latency_s"] = round(time.perf_counter() - t0, 2)
                row["http_status"] = r.status_code
                row["ok"] = r.status_code < 400
                if r.status_code < 400:
                    data = r.json()
                    usage = data.get("usageMetadata", {})
                    row["prompt_tokens"] = usage.get("promptTokenCount")
                    row["output_tokens"] = usage.get("candidatesTokenCount")
                    row["total_tokens"] = usage.get("totalTokenCount")
                    cand = (data.get("candidates") or [{}])[0]
                    row["finish_reason"] = cand.get("finishReason")
                    text = (cand.get("content", {}).get("parts") or [{}])[0].get("text", "")
                    try:
                        parsed = json.loads(text)
                        row["valid_json"] = True
                        row["rooms"] = len(parsed.get("rooms", []))
                        row["spotted_objects"] = len(parsed.get("spotted_objects", []))
                    except Exception:
                        row["valid_json"] = False
                else:
                    row["error"] = r.text[:200].replace("\n", " ")
            except Exception as exc:  # noqa: BLE001
                row["latency_s"] = round(time.perf_counter() - t0, 2)
                row["ok"] = False
                row["error"] = f"{type(exc).__name__}: {exc}"[:200]
            results.append(row)
            print("  ", json.dumps(row))

    ok_counts = [r["n_images"] for r in results if r.get("ok")]
    report = {
        "_about": "P11: measured Gemini capacity for reference images on the analyze_input payload. "
                  "Sets the evidence for the production reference limit, replacing the hardcoded 6.",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "project": PROJECT,
        "references_available": len(bundle.references),
        "counts_tried": list(COUNTS),
        "max_ok": max(ok_counts) if ok_counts else None,
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nmax reference count that succeeded: {report['max_ok']}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
