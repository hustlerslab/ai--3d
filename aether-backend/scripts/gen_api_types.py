"""P1-FRONTEND-003: generate the frontend's API types from the backend's own
OpenAPI document, so the contract has one source of truth.

    python scripts/gen_api_types.py            # write the file
    python scripts/gen_api_types.py --check    # exit 1 if the committed file is stale (CI)

Output: aether-frontend/src/generated/api-types.ts - an interface per schema,
`API_ENDPOINTS` (every method + path the backend serves, with its response
type), and `ApiResponses` keyed by "METHOD /path". No npm dependency: the
schemas are FastAPI's, the conversion is below.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND.parent / "aether-frontend" / "src" / "generated" / "api-types.ts"
HEADER = (
    "// GENERATED from the backend's OpenAPI document by aether-backend/scripts/gen_api_types.py.\n"
    "// Do not edit by hand: change the response model in app/api/contracts.py and re-run\n"
    "//   python scripts/gen_api_types.py\n"
    "// CI fails if this file differs from what the backend would generate.\n"
)
IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def openapi() -> dict[str, Any]:
    if "AETHER_DATA_DIR" not in os.environ:
        os.environ["AETHER_DATA_DIR"] = tempfile.mkdtemp(prefix="allure-openapi-")
    sys.path.insert(0, str(BACKEND))
    from app.main import app

    return app.openapi()


def name(ref_or_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", ref_or_name.rsplit("/", 1)[-1])


def ts(s: Any) -> str:
    if s is True or s == {}:
        return "unknown"
    if "$ref" in s:
        return name(s["$ref"])
    if "const" in s:
        return json.dumps(s["const"])
    if "enum" in s:
        return " | ".join(json.dumps(v) for v in s["enum"])
    for key in ("anyOf", "oneOf"):
        if key in s:
            parts: list[str] = []
            for sub in s[key]:
                t = ts(sub)
                if t not in parts:
                    parts.append(t)
            return " | ".join(parts)
    if "allOf" in s:
        return " & ".join(ts(x) for x in s["allOf"])
    t = s.get("type")
    if isinstance(t, list):
        return " | ".join(ts({**s, "type": x}) for x in t)
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        if "prefixItems" in s:
            return "[" + ", ".join(ts(x) for x in s["prefixItems"]) + "]"
        inner = ts(s.get("items", {}))
        return f"({inner})[]" if (" | " in inner or " & " in inner) else f"{inner}[]"
    if t == "object" or "properties" in s:
        return obj(s, indent="  ")
    return "unknown"


def obj(s: dict[str, Any], indent: str) -> str:
    props = s.get("properties", {})
    extra = s.get("additionalProperties")
    if not props:
        if isinstance(extra, dict) and extra:
            return f"Record<string, {ts(extra)}>"
        return "Record<string, unknown>"
    return "{\n" + members(s, indent + "  ") + indent + "}"


def members(s: dict[str, Any], indent: str) -> str:
    req = set(s.get("required", []))
    lines = []
    for key, sub in s.get("properties", {}).items():
        k = key if IDENT.match(key) else json.dumps(key)
        lines.append(f"{indent}{k}{'' if key in req else '?'}: {ts(sub)};\n")
    extra = s.get("additionalProperties")
    if extra is True or (isinstance(extra, dict) and not extra):
        lines.append(f"{indent}[key: string]: unknown;\n")
    elif isinstance(extra, dict):
        lines.append(f"{indent}[key: string]: {ts(extra)} | unknown;\n")
    return "".join(lines)


def generate(spec: dict[str, Any]) -> str:
    out = [HEADER, "\n"]
    for raw in sorted(spec.get("components", {}).get("schemas", {})):
        s = spec["components"]["schemas"][raw]
        n = name(raw)
        if s.get("type") == "object" or "properties" in s:
            out.append(f"export interface {n} {{\n{members(s, '  ')}}}\n\n")
        else:
            out.append(f"export type {n} = {ts(s)};\n\n")

    endpoints = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            schema = (op.get("responses", {}).get("200", {}).get("content", {})
                      .get("application/json", {}).get("schema"))
            endpoints.append((method.upper(), path, ts(schema) if schema else "Blob"))
    endpoints.sort(key=lambda e: (e[1], e[0]))

    out.append("/** Every route the backend serves. The frontend contract test calls each\n"
               " * API function against a mocked fetch and fails if its method + path is\n"
               " * not in this list - the class of bug where a PATCH silently became a POST. */\n")
    out.append("export const API_ENDPOINTS = [\n")
    for m, p, r in endpoints:
        out.append(f"  {{ method: {json.dumps(m)}, path: {json.dumps(p)}, response: {json.dumps(r)} }},\n")
    out.append("] as const;\n\n")
    out.append("export interface ApiResponses {\n")
    for m, p, r in endpoints:
        out.append(f"  {json.dumps(f'{m} {p}')}: {r};\n")
    out.append("}\n")
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ns = ap.parse_args()
    text = generate(openapi())
    if ns.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT} is stale: run `python scripts/gen_api_types.py` and commit the result.")
            return 1
        print(f"{OUT} is up to date.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
