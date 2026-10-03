"""P1-FRONTEND-004: design versions.

Journey 9 (task.md §30): accept a design, try a variation, discard it - the
accepted design comes back byte-identical. Plus the reason versions are their
own table rather than a pointer into the scene store: that store is an undo
stack, and ordinary editing can evict an accepted design from it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from app.jobs import get_job_store, get_runner
from app.jobs.schema import JobStatus
from app.projects import get_project_store
from app.projects.versions import canonical, content_hash
from app.scene.store import get_store
from tests.test_asset_rebind import _fake_vendor, _project_with_render, client  # noqa: F401
from tests.test_element_first import _fresh_ctx, _plan_with


def _planned(client) -> str:  # noqa: F811
    from tests.test_golden_project import _seed_project

    pid = _seed_project(client)
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(60)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(120)
    return pid


def _live(pid):
    return get_store().load(get_project_store().get(pid).scene_ids[-1])


def _move_something(client, pid, dx=0.25, nth=0) -> None:  # noqa: F811
    """A real, legal edit: a small move of the `nth` floor piece that has one
    the patch validator accepts (it rightly refuses one that hits a wall).
    Distinct `nth` values move distinct pieces, so a sequence of edits can
    never walk back onto an earlier design."""
    scene = _live(pid)
    url = f"/api/scenes/{scene.scene_id}/patches"
    movable = 0
    for obj in (o for o in scene.objects if o.mount == "floor"):
        x, y, z = obj.position
        for pos in ([x + dx, y, z], [x - dx, y, z], [x, y, z + dx], [x, y, z - dx]):
            body = {"base_version": scene.version,
                    "operations": [{"type": "move_object", "object_id": obj.object_id, "position": pos}]}
            if client.post(f"{url}/preview", json=body).json().get("valid"):
                if movable < nth:
                    movable += 1
                    break
                r = client.post(url, json=body)
                assert r.status_code == 200, r.text
                return
    raise AssertionError("no legal move found in the planned scene")


def _row_sha(version_id: str) -> str:
    from app.db import get_db

    text = get_db().query("SELECT snapshot FROM design_versions WHERE version_id = ?", (version_id,))[0]["snapshot"]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_journey_9_the_accepted_design_survives_an_experiment_byte_identical(client):  # noqa: F811
    pid = _planned(client)
    accepted = client.post(f"/api/projects/{pid}/versions", json={"label": "Accepted", "accept": True}).json()["data"]["version"]
    saved = client.get(f"/api/projects/{pid}/versions/{accepted['version_id']}").json()["data"]["snapshot"]
    row_before = _row_sha(accepted["version_id"])

    # the experiment: move a piece, save it as a second version
    _move_something(client, pid)
    trial = client.post(f"/api/projects/{pid}/versions", json={"label": "Wider walkway"}).json()["data"]["version"]
    assert trial["content_sha256"] != accepted["content_sha256"]

    # discard it: make the accepted design current again
    r = client.post(f"/api/projects/{pid}/versions/{accepted['version_id']}/restore")
    assert r.status_code == 200, r.text

    live = _live(pid)
    assert canonical(live) == canonical(saved), "the live design is byte-identical to the accepted one"
    assert content_hash(live) == accepted["content_sha256"]
    assert _row_sha(accepted["version_id"]) == row_before, "the stored version itself never changed"

    again = client.get(f"/api/projects/{pid}/versions/{accepted['version_id']}").json()["data"]["snapshot"]
    assert again == saved

    listed = client.get(f"/api/projects/{pid}/versions").json()["data"]
    current = {v["label"]: v["is_current"] for v in listed["versions"]}
    assert current == {"Accepted": True, "Wider walkway": False}
    assert listed["unsaved_changes"] is False
    assert [v["accepted"] for v in listed["versions"]] == [True, False]


def test_two_versions_coexist_and_either_can_be_made_current(client):  # noqa: F811
    pid = _planned(client)
    a = client.post(f"/api/projects/{pid}/versions", json={"label": "A"}).json()["data"]["version"]
    _move_something(client, pid)
    b = client.post(f"/api/projects/{pid}/versions", json={"label": "B"}).json()["data"]["version"]

    for target, other in ((a, b), (b, a), (a, b)):
        client.post(f"/api/projects/{pid}/versions/{target['version_id']}/restore")
        listed = {v["version_id"]: v["is_current"] for v in client.get(f"/api/projects/{pid}/versions").json()["data"]["versions"]}
        assert listed == {target["version_id"]: True, other["version_id"]: False}
        assert content_hash(_live(pid)) == target["content_sha256"]


def test_an_edit_after_saving_shows_as_unsaved_changes(client):  # noqa: F811
    pid = _planned(client)
    client.post(f"/api/projects/{pid}/versions", json={"label": "A"})
    _move_something(client, pid)
    listed = client.get(f"/api/projects/{pid}/versions").json()["data"]
    assert listed["unsaved_changes"] is True
    assert not any(v["is_current"] for v in listed["versions"])


def test_restoring_the_current_version_commits_nothing(client):  # noqa: F811
    pid = _planned(client)
    a = client.post(f"/api/projects/{pid}/versions", json={}).json()["data"]["version"]
    before = _live(pid).version
    r = client.post(f"/api/projects/{pid}/versions/{a['version_id']}/restore").json()["data"]
    assert r["scene_version"] == before == _live(pid).version


def test_the_undo_history_alone_would_have_lost_the_accepted_design(client, monkeypatch):  # noqa: F811
    """The correction behind the design (C16): the scene store keeps only
    MAX_HISTORY snapshots and truncates on commit-after-undo. Shrink the cap
    to 3, edit four times: the accepted snapshot is gone from the store's
    history - and the version still restores it byte-identically."""
    from app.scene import store as scene_store

    pid = _planned(client)
    accepted = client.post(f"/api/projects/{pid}/versions", json={"accept": True}).json()["data"]["version"]
    monkeypatch.setattr(scene_store, "MAX_HISTORY", 3)
    for i in range(4):
        _move_something(client, pid, dx=0.1, nth=i)

    record = get_store()._load_record(_live(pid).scene_id)
    assert all(content_hash(s) != accepted["content_sha256"] for s in record["history"]), \
        "the undo history no longer holds the accepted design"

    client.post(f"/api/projects/{pid}/versions/{accepted['version_id']}/restore")
    assert content_hash(_live(pid)) == accepted["content_sha256"]


def test_versions_are_immutable_and_outlive_the_project(client):  # noqa: F811
    from app.db import get_db

    pid = _planned(client)
    v = client.post(f"/api/projects/{pid}/versions", json={"accept": True}).json()["data"]["version"]
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        get_db().execute("UPDATE design_versions SET label = 'edited' WHERE version_id = ?", (v["version_id"],))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        get_db().execute("DELETE FROM design_versions WHERE version_id = ?", (v["version_id"],))

    assert client.delete(f"/api/projects/{pid}").status_code == 200
    kept = get_db().query("SELECT version_id FROM design_versions WHERE project_id = ?", (pid,))
    assert [r["version_id"] for r in kept] == [v["version_id"]]


def test_saving_before_there_is_a_design_is_refused(client):  # noqa: F811
    pid = client.post("/api/projects", json={"name": "Empty"}).json()["project"]["project_id"]
    r = client.post(f"/api/projects/{pid}/versions", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SCENE_REQUIRED"
    assert client.get(f"/api/projects/{pid}/versions/ver_nope").status_code == 404


def test_saving_and_restoring_are_recorded_as_events(client):  # noqa: F811
    pid = _planned(client)
    a = client.post(f"/api/projects/{pid}/versions", json={"accept": True}).json()["data"]["version"]
    _move_something(client, pid)
    client.post(f"/api/projects/{pid}/versions/{a['version_id']}/restore")
    types = [e.event_type for e in get_job_store().list_events(pid, limit=5000)]
    assert "design.version_saved" in types and "design.version_restored" in types


def test_re_running_after_an_edit_generates_nothing_new_for_unchanged_pieces(client, monkeypatch):  # noqa: F811
    """Criterion 3: an edit, a new version, a restore - and generation run
    again after each - spends nothing on pieces that did not change."""
    from app.jobs.handlers import generate_elements as gen

    pid, ctx = _project_with_render(client)
    _plan_with(ctx, monkeypatch, force=False)
    # the helper's job record ran inline; left QUEUED the runner would re-run it
    get_job_store().update(ctx.job.job_id, status=JobStatus.CANCELLED)
    reading = client.get(f"/api/projects/{pid}/scene-reading").json()["data"]["reading"]
    client.patch(f"/api/projects/{pid}/scene-reading", json={"decisions": {e["element_id"]: True for e in reading["elements"]}})
    calls = _fake_vendor(monkeypatch)

    def generate():
        g = _fresh_ctx(pid, "generate_elements")
        try:
            gen.generate_elements(g)
        finally:
            g.close()

    generate()
    first = calls["submit"]
    assert first > 0, "the approved pieces were generated once"

    accepted = client.post(f"/api/projects/{pid}/versions", json={"accept": True}).json()["data"]["version"]
    _move_something(client, pid)
    client.post(f"/api/projects/{pid}/versions", json={"label": "moved"})
    generate()
    assert calls["submit"] == first, "an edit that moved a piece generated nothing new"

    client.post(f"/api/projects/{pid}/versions/{accepted['version_id']}/restore")
    generate()
    assert calls["submit"] == first, "restoring the accepted design generated nothing new"


def test_a_restored_version_becomes_the_baseline_check_scene_compares_against(client):  # noqa: F811
    """check_scene flags pieces missing from the committed scene against the
    plan snapshot on disk (QA-003 row 8: an unexplained removal goes to a
    person). A saved version the person chose to restore - one without a
    piece they removed on purpose - must become that baseline, or restoring
    it would be escalated as missing furniture."""
    from app.projects.layout import project_dir

    pid = _planned(client)
    client.post(f"/api/projects/{pid}/versions", json={"label": "Full", "accept": True})
    scene = _live(pid)
    gone = next(o for o in scene.objects if o.mount == "floor")
    r = client.post(f"/api/scenes/{scene.scene_id}/patches", json={
        "base_version": scene.version, "operations": [{"type": "remove_object", "object_id": gone.object_id}]})
    assert r.status_code == 200, r.text
    lean = client.post(f"/api/projects/{pid}/versions", json={"label": "Without it"}).json()["data"]["version"]

    def missing_after_restoring(version) -> list:
        client.post(f"/api/projects/{pid}/versions/{version['version_id']}/restore")
        on_disk = json.loads((project_dir(pid) / "planning" / "scene_spec.json").read_text(encoding="utf-8"))
        assert content_hash(on_disk) == version["content_sha256"], "the chosen version is the baseline"
        check = get_runner().enqueue(pid, "check_scene", {})
        assert get_runner().wait_idle(60)
        return get_job_store().get(check.job_id).result["missing_objects"]

    full = client.get(f"/api/projects/{pid}/versions").json()["data"]["versions"][0]
    # "Without it" is already live: nothing to commit, but choosing it still sets the baseline
    assert missing_after_restoring(lean) == [], "a version the person chose is not reported as missing furniture"
    # and through a real commit, both ways
    assert missing_after_restoring(full) == []
    assert missing_after_restoring(lean) == []
