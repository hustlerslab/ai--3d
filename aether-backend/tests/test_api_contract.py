"""P1-FRONTEND-003: the API contract, pinned.

1. Every JSON route declares a named response model (not a bare `dict`) and
   serialises through `ContractRoute` (exclude_unset - no invented nulls).
2. The declared contract - every method + path and every schema - matches the
   committed snapshot `tests/contracts/api_contract.json`. Changing a method,
   adding/removing a route, or changing a field fails here.
3. The generated frontend types are exactly what the backend would generate
   now (`scripts/gen_api_types.py --check`).
4. Every endpoint is CALLED, once, against a real app: its status is pinned
   and its body must validate against its model with no undeclared key. 28
   of these routes never returned a success response anywhere else in the
   suite before this file existed.

Regenerate the snapshot only on purpose:
    AETHER_UPDATE_CONTRACT=1 pytest tests/test_api_contract.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import BaseModel, TypeAdapter

from tests.conftest import sign_in_admin

SNAPSHOT = Path(__file__).parent / "contracts" / "api_contract.json"
FIXTURE = Path(__file__).parent / "fixtures" / "golden_project"


# ── the declared contract ───────────────────────────────────────────────────


def _routes():
    from app.api import projects_routes, routes
    from app.auth import routes as auth_routes
    from app.main import app

    out = list(routes.router.routes) + list(projects_routes.router.routes) + \
        list(projects_routes.files_router.routes) + list(auth_routes.router.routes)
    out += [r for r in app.routes if getattr(r, "path", None) == "/" and hasattr(r, "response_model")]
    return out


def _models() -> dict[tuple[str, str], Any]:
    return {(m, r.path): r.response_model for r in _routes() for m in r.methods}


def test_every_json_route_declares_a_named_response_model(env):
    from app.api.contracts import BINARY_ROUTES, ContractRoute

    bare = []
    for r in _routes():
        path = re.sub(r":path}", "}", r.path)
        if path in BINARY_ROUTES:
            continue
        m = r.response_model
        if not (isinstance(m, type) and issubclass(m, BaseModel)):
            bare.append((sorted(r.methods), r.path, m))
    assert not bare, f"routes without a named response model (a bare dict is not a contract): {bare}"


def test_every_api_route_serialises_through_contract_route(env):
    from app.api.contracts import ContractRoute

    loose = [r.path for r in _routes()
             if r.path != "/" and not (isinstance(r, ContractRoute) and r.response_model_exclude_unset)]
    assert not loose, f"routes that would emit nulls for fields they never returned: {loose}"


def test_a_field_a_route_did_not_return_is_absent_not_null(client):
    """The behaviour, on a real route. Without a Meshy key `/credits` returns
    no `balance`; attaching a model without exclude_unset made it grow
    `"balance": null` - a changed contract no other test noticed."""
    data = client.get("/api/credits").json()["data"]
    assert data["available"] is False
    assert "balance" not in data


def _contract() -> dict[str, Any]:
    from app.main import app

    spec = app.openapi()
    ops = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            ok = op.get("responses", {}).get("200", {}).get("content", {})
            schema = ok.get("application/json", {}).get("schema", {})
            ops[f"{method.upper()} {path}"] = schema.get("$ref", "").rsplit("/", 1)[-1] or ("binary" if not ok else "inline")
    schemas = {name: hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()[:16]
               for name, s in spec["components"]["schemas"].items()}
    return {"operations": dict(sorted(ops.items())), "schemas": dict(sorted(schemas.items()))}


def test_contract_matches_the_committed_snapshot(env):
    now = _contract()
    if os.environ.get("AETHER_UPDATE_CONTRACT") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(now, indent=1) + "\n", encoding="utf-8")
        pytest.skip("snapshot rewritten on request (AETHER_UPDATE_CONTRACT=1)")
    was = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    changed_ops = sorted(set(was["operations"].items()) ^ set(now["operations"].items()))
    changed_schemas = sorted(k for k in set(was["schemas"]) | set(now["schemas"])
                             if was["schemas"].get(k) != now["schemas"].get(k))
    assert not changed_ops and not changed_schemas, (
        "the API contract changed. If that was intended, regenerate the snapshot AND the frontend types:\n"
        "  AETHER_UPDATE_CONTRACT=1 pytest tests/test_api_contract.py && python scripts/gen_api_types.py\n"
        f"operations: {changed_ops}\nschemas: {changed_schemas}"
    )


def test_generated_frontend_types_are_up_to_date(env):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen_api_types", Path(__file__).resolve().parents[1] / "scripts" / "gen_api_types.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    from app.main import app

    assert gen.OUT.read_text(encoding="utf-8") == gen.generate(app.openapi()), \
        "aether-frontend/src/generated/api-types.ts is stale: run python scripts/gen_api_types.py"


# ── every endpoint, called ──────────────────────────────────────────────────


#: The status each endpoint answers with in a MOCK environment (no Blender, no
#: Meshy key, no network). Anything but 2xx is a pinned, deliberate refusal,
#: explained here - never an unexplained failure.
EXPECTED: dict[tuple[str, str], int] = {
    # Paid step: refuses without a Meshy key rather than no-op (409 MESHY_NOT_CONFIGURED).
    ("POST", "/api/projects/{project_id}/elements/generate"): 409,
    # Render lane: refuses without Blender (503 BLENDER_NOT_CONFIGURED). The
    # success shapes are called by test_render_endpoints_with_real_blender.
    ("POST", "/api/projects/{project_id}/build"): 503,
    # These check the build exists BEFORE they check Blender: 409 BUILD_REQUIRED.
    ("POST", "/api/projects/{project_id}/preview"): 409,
    ("POST", "/api/projects/{project_id}/walkthrough"): 409,
    ("POST", "/api/projects/{project_id}/film"): 409,
    ("GET", "/api/projects/{project_id}/build"): 404,
    ("GET", "/api/projects/{project_id}/tour"): 404,
    # A light model gets no browser copy, so there is nothing to serve here; the
    # success path (bytes) is fetched by tests/test_file_authorization.py.
    ("GET", "/files/assets-web/{path}"): 404,
}


def _glb(boxes=(((-0.4, 0.0, -0.4), (0.4, 0.9, 0.4)),)) -> bytes:
    """A packed, self-contained GLB of axis-aligned boxes - what an upload is."""
    positions, indices = [], []
    for lo, hi in boxes:
        base = len(positions)
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        positions += [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        for a, b, c, d in quads:
            indices += [(base + a, base + b, base + c), (base + a, base + c, base + d)]
    pos = b"".join(struct.pack("<fff", *p) for p in positions)
    idx = b"".join(struct.pack("<HHH", *f) for f in indices)
    blob = pos + idx + b"\x00" * (-(len(pos) + len(idx)) % 4)
    doc = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
                        {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx)}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3",
             "min": [min(p[i] for p in positions) for i in range(3)],
             "max": [max(p[i] for p in positions) for i in range(3)]},
            {"bufferView": 1, "componentType": 5123, "count": len(indices) * 3, "type": "SCALAR"},
        ],
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\x00") + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def _undeclared(model: Any, body: Any) -> list[str]:
    """Keys the route returned that its model does not declare - at the
    payload level, where the frontend binds."""
    fields = getattr(model, "model_fields", {})
    if "data" in fields and isinstance(body, dict) and "data" in body:
        inner = fields["data"].annotation
        payload = body["data"]
        args = getattr(inner, "__args__", ())
        if isinstance(payload, list) and args and hasattr(args[0], "model_fields"):
            return sorted({k for item in payload for k in item} - set(args[0].model_fields))
        if isinstance(payload, dict) and hasattr(inner, "model_fields"):
            return sorted(set(payload) - set(inner.model_fields))
        return []
    if isinstance(body, dict) and fields:
        return sorted(set(body) - set(fields))
    return []


class Walk:
    def __init__(self, client: TestClient):
        self.client = client
        self.models = _models()
        self.results: dict[tuple[str, str], dict] = {}

    def call(self, method: str, template: str, **kw) -> Any:
        values = kw.pop("values", {})
        client = kw.pop("client", self.client)
        url = template.format(**values)
        resp = client.request(method, url, **kw)
        key = (method, template)
        expected = EXPECTED.get(key, 200)
        record = {"status": resp.status_code, "expected": expected, "problems": []}
        if resp.status_code != expected:
            record["problems"].append(f"status {resp.status_code} != {expected}: {resp.text[:300]}")
        ctype = resp.headers.get("content-type", "")
        body = resp.json() if "application/json" in ctype else None
        model = self.models.get(key) or self.models.get((method, template.replace("{path}", "{path:path}")))
        if 200 <= resp.status_code < 300 and body is not None:
            try:
                TypeAdapter(model).validate_python(body)
            except Exception as exc:  # noqa: BLE001
                record["problems"].append(f"does not validate against {getattr(model, '__name__', model)}: {exc}")
            extra = _undeclared(model, body)
            if extra:
                record["problems"].append(f"undeclared keys {extra}")
        elif body is not None and not (200 <= resp.status_code < 300):
            if not (body.get("success") is False and {"code", "message"} <= set(body.get("error", {}))):
                record["problems"].append(f"error body is not the error envelope: {body}")
        self.results.setdefault(key, record)
        return body


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _fake_polyhaven(monkeypatch, tmp_path: Path) -> None:
    """Poly Haven, without the network: the real ingest pipeline runs on local
    files the fake 'downloads'."""
    from app.providers import polyhaven
    from tests.test_asset_forward_axis import write_boxes_gltf

    model = write_boxes_gltf(tmp_path / "ph_stool.gltf", [((-0.2, 0.0, -0.2), (0.2, 0.7, 0.2))])
    tex = tmp_path / "ph_wood_diff.png"
    Image.new("RGB", (8, 8), (150, 110, 70)).save(tex)

    async def model_files(client, asset_id, resolution="1k"):
        return [polyhaven.RemoteFile(url="local", relative_path=p.name, size=p.stat().st_size)
                for p in (model, model.with_suffix(".bin"))]

    async def texture_files(client, asset_id, resolution="1k"):
        return {"color": polyhaven.RemoteFile(url="local", relative_path=tex.name, size=tex.stat().st_size)}

    async def download(client, files, dest):
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for f in files:
            src = tmp_path / f.relative_path
            (dest / f.relative_path).write_bytes(src.read_bytes())
            out.append(dest / f.relative_path)
        return out

    monkeypatch.setattr(polyhaven, "model_files", model_files)
    monkeypatch.setattr(polyhaven, "texture_files", texture_files)
    monkeypatch.setattr(polyhaven, "download", download)


def test_every_endpoint_answers_with_its_declared_shape(client, monkeypatch, tmp_path):
    from app.jobs import get_runner
    from app.main import app
    from app.supervisor.review import ReviewHandle
    from app.spatial.failures import FailureCategory as FC

    _fake_polyhaven(monkeypatch, tmp_path)
    w = Walk(client)
    idle = get_runner().wait_idle

    # service
    w.call("GET", "/")
    w.call("GET", "/api/health")
    w.call("GET", "/api/credits")
    w.call("GET", "/api/jobs/types")

    # a project, through the mock pipeline
    pid = w.call("POST", "/api/projects", json={"name": "Contract walk"})["project"]["project_id"]
    v = {"project_id": pid}
    w.call("GET", "/api/projects")
    w.call("PATCH", "/api/projects/{project_id}", values=v, json={"description": "2BHK in Pune"})
    files = [("references", (p.name, p.read_bytes(), "image/png")) for p in sorted((FIXTURE / "references").iterdir())]
    w.call("POST", "/api/projects/{project_id}/inputs", values=v,
           data={"description": (FIXTURE / "brief.txt").read_text(encoding="utf-8")}, files=files)
    inputs = w.call("GET", "/api/projects/{project_id}/inputs", values=v)["data"]
    w.call("GET", "/api/projects/{project_id}", values=v)
    w.call("POST", "/api/projects/{project_id}/analyze", values=v, json={})
    assert idle(60)
    analysis = w.call("GET", "/api/projects/{project_id}/analysis", values=v)["data"]
    w.call("PATCH", "/api/projects/{project_id}/analysis", values=v, json={"intent": "warm and calm"})
    room_id = analysis["analysis"]["rooms"][0]["room_id"]
    w.call("POST", "/api/projects/{project_id}/moodboard/rooms/{room_id}/repaint", values={**v, "room_id": room_id})
    assert idle(60)
    w.call("POST", "/api/projects/{project_id}/element-images", values=v, json={})
    assert idle(60)
    w.call("GET", "/api/projects/{project_id}/element-images", values=v)
    w.call("PATCH", "/api/projects/{project_id}/element-images", values=v, json={"decisions": {}})
    w.call("POST", "/api/projects/{project_id}/scene-plan", values=v, json={})
    assert idle(120)
    w.call("POST", "/api/projects/{project_id}/elements/generate", values=v, json={})
    w.call("POST", "/api/projects/{project_id}/assets/resolve", values=v)
    assert idle(60)
    spec = w.call("GET", "/api/projects/{project_id}/scene-spec", values=v)["data"]
    w.call("GET", "/api/projects/{project_id}/provenance", values=v)
    w.call("GET", "/api/projects/{project_id}/provenance/{scene_object_id}",
           values={**v, "scene_object_id": spec["scene"]["objects"][0]["object_id"]})
    ver = w.call("POST", "/api/projects/{project_id}/versions", values=v,
                 json={"label": "Accepted", "accept": True})["data"]["version"]
    vv = {**v, "version_id": ver["version_id"]}
    w.call("GET", "/api/projects/{project_id}/versions", values=v)
    w.call("GET", "/api/projects/{project_id}/versions/{version_id}", values=vv)
    w.call("POST", "/api/projects/{project_id}/versions/{version_id}/restore", values=vv)
    for route in ("build", "preview", "walkthrough", "film"):
        w.call("POST", f"/api/projects/{{project_id}}/{route}", values=v, json={})
    w.call("GET", "/api/projects/{project_id}/build", values=v)
    w.call("GET", "/api/projects/{project_id}/tour", values=v)

    link = w.call("POST", "/api/projects/{project_id}/share", values=v, json={"label": "client"})["data"]
    w.call("GET", "/api/projects/{project_id}/share", values=v)
    w.call("DELETE", "/api/projects/{project_id}/share/{token_id}", values={**v, "token_id": link["token_id"]})

    job = w.call("POST", "/api/projects/{project_id}/jobs", values=v, json={"type": "noop", "params": {}})["job"]
    assert idle(30)
    w.call("GET", "/api/jobs/{job_id}", values={"job_id": job["job_id"]})
    w.call("GET", "/api/projects/{project_id}/jobs", values=v)
    w.call("GET", "/api/projects/{project_id}/events", values=v)
    w.call("GET", "/api/projects/{project_id}/tradeoffs", values=v)
    w.call("GET", "/api/projects/{project_id}/review", values=v)
    item = ReviewHandle().open(project_id=pid, issue="the build reported errors", category=FC.BLENDER_EXECUTION_FAILURE,
                               issue_type="build_errors", entity_ids=[], evidence_refs=[], expected={"ok": True},
                               observed={"errors": ["x"]}, recommendation="accept_as_is",
                               actions=["accept_as_is", "retry_repair", "replan", "cancel"])
    w.call("GET", "/api/projects/{project_id}/reviews", values=v)
    w.call("POST", "/api/projects/{project_id}/reviews/{item_id}/decision", values={**v, "item_id": item["item_id"]},
           json={"action": "accept_as_is"})
    w.call("GET", "/api/projects/{project_id}/repairs", values=v)
    w.call("GET", "/api/projects/{project_id}/outputs", values=v)
    ref = next(i for i in inputs if i["kind"] == "reference")
    w.call("GET", "/files/projects/{project_id}/{path}", values={**v, "path": ref["path"]})

    # scenes, from the seed
    scene = w.call("POST", "/api/scenes", json={"project_id": pid, "from_seed": True})["scene"]
    s = {"scene_id": scene["scene_id"]}
    w.call("GET", "/api/scenes")
    w.call("GET", "/api/scenes/{scene_id}", values=s)
    w.call("GET", "/api/scenes/{scene_id}/validate", values=s)
    obj = next(o for o in scene["objects"] if o["mount"] == "floor")
    op = {"type": "move_object", "object_id": obj["object_id"], "position": obj["position"]}
    w.call("POST", "/api/scenes/{scene_id}/patches/preview", values=s, json={"base_version": scene["version"], "operations": [op]})
    w.call("POST", "/api/scenes/{scene_id}/patches", values=s, json={"base_version": scene["version"], "operations": [op]})
    w.call("POST", "/api/scenes/{scene_id}/undo", values=s)
    w.call("POST", "/api/scenes/{scene_id}/redo", values=s)
    w.call("POST", "/api/scenes/{scene_id}/assets/upgrade", values=s)
    w.call("GET", "/api/scenes/{scene_id}/walkthrough/tour", values=s)
    spawn = w.call("GET", "/api/scenes/{scene_id}/walkthrough/spawn", values=s)["data"]
    w.call("POST", "/api/scenes/{scene_id}/walkthrough/check-position", values=s,
           json={"x": spawn["position"][0], "z": spawn["position"][2]})
    w.call("POST", "/api/scenes/{scene_id}/walkthrough/views", values=s,
           json={"name": "Entry", "position": spawn["position"], "target": spawn["look_at"]})
    w.call("GET", "/api/scenes/{scene_id}/walkthrough/views", values=s)
    first = w.call("POST", "/api/scenes/{scene_id}/design/proposals", values=s, json={"instruction": "add a plant"})
    w.call("POST", "/api/scenes/{scene_id}/design/proposals/{proposal_id}/apply",
           values={**s, "proposal_id": first["proposal"]["proposal_id"]})
    second = client.post(f"/api/scenes/{s['scene_id']}/design/proposals", json={"instruction": "add a lamp"}).json()
    w.call("POST", "/api/scenes/{scene_id}/design/proposals/{proposal_id}/reject",
           values={**s, "proposal_id": second["proposal"]["proposal_id"]})

    # catalog, assets, materials
    items = w.call("GET", "/api/catalog")["data"]
    w.call("GET", "/api/catalog/{asset_id}", values={"asset_id": items[0]["asset_id"]})
    asset = w.call("POST", "/api/assets/upload", files={"file": ("stool.glb", _glb(), "model/gltf-binary")},
                   data={"name": "Contract stool", "semantic_type": "stool", "asset_id": "contract_stool"})["asset"]
    a = {"asset_id": asset["asset_id"]}
    w.call("GET", "/api/assets")
    w.call("GET", "/api/assets/{asset_id}", values=a)
    w.call("POST", "/api/assets/{asset_id}/renormalize", values=a, json={})
    w.call("POST", "/api/assets/ingest/polyhaven",
           json={"source_id": "stool_x", "name": "PH stool", "semantic_type": "stool"})
    # AssetFiles paths are relative to the data dir: normalized/<id>/..., web/<id>/...
    w.call("GET", "/files/assets/{path}", values={"path": asset["files"]["normalized"].split("normalized/", 1)[1]})
    assert not asset["files"].get("web"), "a 12-triangle stool should need no browser copy"
    w.call("GET", "/files/assets-web/{path}", values={"path": asset["files"]["normalized"].split("normalized/", 1)[1]})
    mats = w.call("GET", "/api/materials")["data"]
    w.call("GET", "/api/materials/{material_id}", values={"material_id": mats[0]["material_id"]})
    wood = w.call("POST", "/api/materials/ingest/polyhaven", json={"source_id": "wood_x", "material_id": "contract_wood"})
    # maps are data-dir relative ("materials/<id>/..."); the viewer requests
    # "/files/" + that path (aether-api.ts fileUrl), so the route sees the rest.
    w.call("GET", "/files/materials/{path}", values={"path": wood["material"]["maps"]["color"].split("materials/", 1)[1]})

    # the moodboard reading: the mock pipeline never writes one (scene images
    # are off in tests), so seed it the way the element-first suite does.
    from tests.test_asset_rebind import _project_with_render
    from tests.test_element_first import _plan_with

    from app.jobs import get_job_store
    from app.jobs.schema import JobStatus

    rpid, rctx = _project_with_render(client)
    _plan_with(rctx, monkeypatch, force=False)
    # The helper's job record ran inline above; left QUEUED, the runner would
    # pick it up again after this test's database is gone.
    get_job_store().update(rctx.job.job_id, status=JobStatus.CANCELLED)
    reading = w.call("GET", "/api/projects/{project_id}/scene-reading", values={"project_id": rpid})["data"]["reading"]
    w.call("PATCH", "/api/projects/{project_id}/scene-reading", values={"project_id": rpid},
           json={"decisions": {e["element_id"]: True for e in reading["elements"]}})

    # auth, on a second client so signing out does not end the walk's session
    with TestClient(app) as other:
        creds = {"email": "contract-walk@example.com", "password": "contract-walk-password"}
        w.call("POST", "/api/auth/register", client=other, json=creds)
        w.call("POST", "/api/auth/login", client=other, json=creds)
        w.call("GET", "/api/auth/me", client=other)
        w.call("GET", "/api/auth/session", client=other)
        w.call("POST", "/api/auth/logout-everywhere", client=other)
        w.call("POST", "/api/auth/login", client=other, json=creds)
        w.call("POST", "/api/auth/logout", client=other)

    w.call("DELETE", "/api/projects/{project_id}/inputs/{input_id}", values={**v, "input_id": inputs[0]["input_id"]})
    w.call("DELETE", "/api/projects/{project_id}", values=v)

    report = {f"{m} {p}": r for (m, p), r in sorted(w.results.items(), key=lambda kv: (kv[0][1], kv[0][0]))}
    out = os.environ.get("ALLURE_CONTRACT_REPORT")
    if out:
        Path(out).write_text(json.dumps(report, indent=1), encoding="utf-8")

    problems = {k: r["problems"] for k, r in report.items() if r["problems"]}
    assert not problems, json.dumps(problems, indent=1)[:6000]

    declared = {f"{m} {p}" for m, p in _models() if m != "HEAD"}
    called = set(report)
    never = sorted(k for k in declared - called if "{path:path}" not in k)
    assert not never, f"endpoints the contract walk never called: {never}"
