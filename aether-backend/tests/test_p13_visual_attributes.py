"""P13: the client's words reach the scene object and the manifest.

P12 carried reference intent into the plan; these assert the last hop - that
colour words, pattern, frame finish and descriptors survive onto `SceneObject`
and across the executor boundary, and that persistence, patching and re-planning
do not quietly drop them.

PRESERVED is not RENDERED. What Blender can actually paint is a separate axis,
asserted against `VISUAL_ATTRIBUTE_CONTRACT` rather than assumed.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import sign_in_admin
from PIL import Image

from app.blender.manifest import build_manifest
from app.jobs import get_runner
from app.planning.intent_fidelity import ExecutorSupport, VISUAL_ATTRIBUTE_CONTRACT
from app.projects.layout import project_dir
from app.scene.patches import Patch, UpdateObjectOp, commit_patch
from app.scene.schema import ObjectVisual, SceneObject
from app.scene.store import get_store

BRIEF = "Two bedroom flat: living room, master bedroom, kids room, kitchen. Warm and calm."
RICH = "exact_sage_linen_quilted_contemporary_sofa_dark_walnut_frame.jpg"


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield sign_in_admin(c)


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (150, 160, 140)).save(buf, "JPEG")
    return buf.getvalue()


def _planned(client, filenames: list[str]) -> tuple[str, str]:
    pid = client.post("/api/projects", json={"name": "p13"}).json()["project"]["project_id"]
    files = [("references", (fn, _jpeg(), "image/jpeg")) for fn in filenames]
    assert client.post(f"/api/projects/{pid}/inputs", data={"description": BRIEF},
                       files=files).status_code == 200
    assert client.post(f"/api/projects/{pid}/analyze", json={}).status_code == 200
    assert get_runner().wait_idle(180)
    job = client.post(f"/api/projects/{pid}/scene-plan", json={}).json()["job"]
    assert get_runner().wait_idle(300)
    polled = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]
    assert polled["status"] == "SUCCEEDED", polled.get("error")
    return pid, polled["result"]["scene_id"]


def _sofa(scene_id: str) -> SceneObject:
    scene = get_store().load(scene_id)
    return next(o for o in scene.objects if o.semantic_type == "sofa")


def test_every_stated_attribute_reaches_the_scene_object(client):
    """The four that stopped at the plan before P13, plus the two that did not."""
    _pid, scene_id = _planned(client, [RICH])
    visual = _sofa(scene_id).visual

    assert visual.color_words, "colour words stopped at the plan before P13"
    assert visual.pattern == "quilted"
    assert "walnut" in visual.frame_finish
    assert visual.descriptors
    assert visual.material == "linen"
    assert visual.source_intent_ids, "the object must name the intent that shaped it"


def test_the_manifest_row_mirrors_the_scene_object(client):
    """The executor boundary carries the same block, not a lossy copy."""
    pid, scene_id = _planned(client, [RICH])
    scene = get_store().load(scene_id)
    manifest = build_manifest(scene, project_id=pid, project_root=project_dir(pid), preview=False)
    sofa = _sofa(scene_id)
    row = next(o for o in manifest["objects"] if o["id"] == sofa.object_id)

    assert row["visual"] == sofa.visual.model_dump()
    # The two RESOLVED channels the executor actually paints are untouched.
    assert row["color"] == sofa.color
    assert row["material_overrides"] == dict(sofa.material_overrides)


def test_a_planner_only_object_adds_nothing_to_the_manifest(client):
    """No `visual` key at all for objects no reference shaped, so every
    pre-P13 scene still produces a byte-identical manifest."""
    pid, scene_id = _planned(client, ["style_japandi_palette.jpg"])
    scene = get_store().load(scene_id)
    manifest = build_manifest(scene, project_id=pid, project_root=project_dir(pid), preview=False)

    assert scene.objects, "the planner still furnishes the flat"
    assert all(o.visual.is_empty() for o in scene.objects)
    assert all("visual" not in row for row in manifest["objects"])


def test_attributes_survive_save_and_reload(client):
    _pid, scene_id = _planned(client, [RICH])
    before = _sofa(scene_id).visual.model_dump()
    reloaded = get_store().load(scene_id)
    after = next(o for o in reloaded.objects if o.semantic_type == "sofa")
    assert after.visual.model_dump() == before


def test_patching_another_field_leaves_the_visual_block_alone(client):
    _pid, scene_id = _planned(client, [RICH])
    sofa = _sofa(scene_id)
    before = sofa.visual.model_dump()

    store = get_store()
    patch = Patch(scene_id=scene_id, base_version=store.load(scene_id).version,
                  operations=[UpdateObjectOp(object_id=sofa.object_id, color="#123456")],
                  source="user")
    after = commit_patch(store, patch)
    obj = next(o for o in after.objects if o.object_id == sofa.object_id)

    assert obj.color == "#123456"
    assert obj.visual.model_dump() == before


def test_a_scene_stored_before_p13_still_loads():
    """Backward compatibility: no `visual` key at all must not raise."""
    old = SceneObject.model_validate({"semantic_type": "sofa", "room_id": "r",
                                      "position": [0, 0, 0], "dimensions": [2, 0.8, 0.9]})
    assert old.visual.is_empty()
    assert isinstance(old.visual, ObjectVisual)


def test_re_planning_keeps_one_object_and_the_same_attributes(client):
    pid, scene_id = _planned(client, [RICH])
    first = _sofa(scene_id).visual.model_dump()

    job = client.post(f"/api/projects/{pid}/scene-plan", json={"force": True}).json()["job"]
    assert get_runner().wait_idle(300)
    result = client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]["result"]
    scene = get_store().load(result["scene_id"])
    sofas = [o for o in scene.objects if o.semantic_type == "sofa"]

    assert len(sofas) == 1, "re-planning must not duplicate the client's piece"
    assert sofas[0].visual.model_dump() == first


def test_the_executor_contract_never_claims_more_than_blender_does():
    """`apply_materials.for_object` paints one registry material plus one hex
    tint, always. P14 added a CONDITIONAL tier for the two attributes that have
    a real mechanism but only on some objects; everything else stays metadata."""
    always = {k for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()
              if v.executor is ExecutorSupport.PRESERVED_AND_RENDERED}
    conditional = {k for k, v in VISUAL_ATTRIBUTE_CONTRACT.items()
                   if v.executor is ExecutorSupport.CONDITIONALLY_RENDERED}
    assert always == {"color_hex", "material", "upholstery"}
    assert conditional == {"frame_finish", "descriptors"}
    for name in ("pattern", "color_words"):
        assert VISUAL_ATTRIBUTE_CONTRACT[name].executor is ExecutorSupport.PRESERVED_METADATA_ONLY
    for contract in VISUAL_ATTRIBUTE_CONTRACT.values():
        assert contract.how, "a limit or a mechanism must say why"


def test_visual_attributes_carry_no_geometry():
    """The block is descriptive evidence; the solver keeps every coordinate."""
    fields = set(ObjectVisual.model_fields)
    for banned in ("position", "rotation", "rotation_y", "scale", "dimensions", "x", "y", "z",
                   "transform", "wall_id"):
        assert banned not in fields


def test_the_fidelity_report_breaks_survival_down_per_attribute(client):
    pid, _scene_id = _planned(client, [RICH])
    fidelity = json.loads(
        (project_dir(pid) / "planning" / "visual_intent_fidelity.json").read_text(encoding="utf-8"))

    by_attribute = {row["attribute"]: row for row in fidelity["survival"]}
    assert set(by_attribute) == set(VISUAL_ATTRIBUTE_CONTRACT)
    for name in ("pattern", "frame_finish", "color_words", "descriptors"):
        row = by_attribute[name]
        assert row["stated"] >= 1, f"{name} was stated by the reference"
        assert row["rate"] == 1.0, f"{name} did not reach the scene"
    # Preservation is never reported as rendering.
    assert by_attribute["pattern"]["executor"] == "preserved_metadata_only"
