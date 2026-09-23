"""P0-SEC-005 - a person's renders and photographs stop being retrievable by
anyone who guesses a path.

`docs/AUTH_PLAN.md` calls this the largest single hole, and it was: scenes are
JSON and images on DISK, not rows, so no amount of database authorization
reached them. `GET /files/projects/{id}/{path}` had a traversal guard and no
authorization at all, and three `StaticFiles` mounts had neither - a mount is
not a route, so the router-level gate never saw them.

The four criteria, one section each:

  1. Another user's render is not retrievable.
  2. A share-token holder retrieves only that project's tour assets.
  3. Traversal attempts still fail.
  4. The 3D viewer and share page still load their assets.

(4) is what keeps this from being a regression dressed up as a fix.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

ALICE = ("alice@example.com", "alice-password-123")
BOB = ("bob@example.com", "bob-password-123")

PANO = "outputs/web/panos/preview/n01.jpg"


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _register(client, creds):
    email, password = creds
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _project_with_files(client, headers) -> str:
    """A project with a rendered tour AND private material beside it."""
    from app.projects.layout import ensure_layout, project_dir

    pid = client.post("/api/projects", json={"name": "Sharma Residence"}, headers=headers) \
                .json()["project"]["project_id"]
    ensure_layout(pid)
    root = project_dir(pid)

    web = root / "outputs" / "web"
    (web / "panos" / "preview").mkdir(parents=True, exist_ok=True)
    (web / "panos" / "preview" / "n01.jpg").write_bytes(b"pano")
    (web / "tour.json").write_text(json.dumps({
        "tour": {"nodes": [{"id": "n01",
                            "pano_url": f"/files/projects/{pid}/{PANO}"}]},
        "explore": {"scene_id": "scene_probe", "scene_url": "/api/scenes/scene_probe"},
    }), encoding="utf-8")

    # The things a share link must NEVER reach.
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "input" / "description.txt").write_text("the client's brief", encoding="utf-8")
    (root / "blender").mkdir(parents=True, exist_ok=True)
    (root / "blender" / "scene.blend").write_bytes(b"blend")
    return pid


def _share(client, headers, pid) -> str:
    r = client.post(f"/api/projects/{pid}/share", json={}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]


def _seed_asset() -> str:
    """One file in the shared library, where the 3D viewer looks for meshes."""
    from app.assets.registry import get_registry

    root = get_registry().root / "web"
    root.mkdir(parents=True, exist_ok=True)
    (root / "probe.glb").write_bytes(b"glb")
    return "probe.glb"


# ── 1. another user's render is not retrievable ──────────────────────────

def test_a_stranger_cannot_fetch_a_render(client):
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)

    client.cookies.clear()
    assert client.get(f"/files/projects/{pid}/{PANO}").status_code == 401


def test_another_signed_in_user_cannot_fetch_a_render(client):
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    bob = _register(client, BOB)
    assert client.get(f"/files/projects/{pid}/{PANO}", headers=bob).status_code == 403


@pytest.mark.parametrize("path", [
    "input/description.txt",
    "blender/scene.blend",
    "outputs/web/tour.json",
])
def test_nothing_in_a_project_directory_is_readable_by_a_stranger(client, path):
    """The brief, the .blend, the tour package - all of it was open."""
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)

    client.cookies.clear()
    assert client.get(f"/files/projects/{pid}/{path}").status_code == 401


def test_the_owner_can_still_fetch_their_own_files(client):
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    r = client.get(f"/files/projects/{pid}/{PANO}", headers=alice)
    assert r.status_code == 200 and r.content == b"pano"


# ── 2. a share token reaches the tour assets and nothing else ────────────

def test_a_share_token_fetches_the_panoramas(client):
    """Without this the share page renders a tour with no images in it."""
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    token = _share(client, alice, pid)

    client.cookies.clear()
    r = client.get(f"/files/projects/{pid}/{PANO}", params={"k": token})
    assert r.status_code == 200 and r.content == b"pano"


@pytest.mark.parametrize("path", ["input/description.txt", "blender/scene.blend"])
def test_a_share_token_reaches_nothing_outside_outputs_web(client, path):
    """The carve-out is `outputs/web/` - what `preview` publishes - not the
    project directory. A link must not hand over the client's brief."""
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    token = _share(client, alice, pid)

    client.cookies.clear()
    assert client.get(f"/files/projects/{pid}/{path}", params={"k": token}).status_code == 401


def test_a_share_token_for_one_project_reaches_no_other_projects_files(client):
    alice = _register(client, ALICE)
    mine = _project_with_files(client, alice)
    theirs = _project_with_files(client, alice)
    token = _share(client, alice, mine)

    client.cookies.clear()
    assert client.get(f"/files/projects/{theirs}/{PANO}", params={"k": token}).status_code == 401
    assert client.get(f"/files/projects/{mine}/{PANO}", params={"k": token}).status_code == 200


def test_a_revoked_share_token_stops_fetching_files(client):
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    link = client.post(f"/api/projects/{pid}/share", json={}, headers=alice).json()["data"]
    client.delete(f"/api/projects/{pid}/share/{link['token_id']}", headers=alice)

    client.cookies.clear()
    assert client.get(f"/files/projects/{pid}/{PANO}",
                      params={"k": link["token"]}).status_code == 401


def test_a_share_token_cannot_write_anything(client):
    """A link is read-only by construction: the capability check refuses any
    method but GET before it even looks the token up."""
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    token = _share(client, alice, pid)

    client.cookies.clear()
    assert client.post(f"/api/projects/{pid}/analyze", params={"k": token},
                       json={}).status_code == 401


# ── 3. traversal still fails ─────────────────────────────────────────────

@pytest.mark.parametrize("attack", [
    "../../../allure.db",
    "../../projects.json",
    "outputs/../../../allure.db",
    "....//....//allure.db",
])
def test_traversal_out_of_a_project_directory_fails(client, attack):
    """Signed in as the OWNER - so a refusal here is the path guard, not the
    authorization gate. Being authorized must not become permission to read the
    whole disk."""
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    r = client.get(f"/files/projects/{pid}/{attack}", headers=alice)
    assert r.status_code in (404, 400), f"{attack} -> {r.status_code}"
    assert b"sqlite" not in r.content.lower()


def _seed_material() -> str:
    from app.materials.registry import get_material_registry

    root = get_material_registry().root / "probe_mat"
    root.mkdir(parents=True, exist_ok=True)
    (root / "color.jpg").write_bytes(b"tex")
    return "probe_mat/color.jpg"


@pytest.mark.parametrize("prefix,seed", [
    ("assets-web", _seed_asset),
    ("materials", _seed_material),
])
def test_the_shared_library_handler_is_actually_reached(client, prefix, seed):
    """Proves the handler RUNS before the next test claims it refused an attack.

    The earlier version of the traversal test below passed without ever
    executing the handler - httpx and Starlette normalise `../` out of a path
    before the request is sent, so the route never matched. It therefore missed
    an ImportError in `material_file` that returned 500 to a real browser.
    A refusal only means something once the code under test has run.
    """
    alice = _register(client, ALICE)
    name = seed()
    r = client.get(f"/files/{prefix}/{name}", headers=alice)
    assert r.status_code == 200, r.text
    assert r.content in (b"glb", b"tex")


@pytest.mark.parametrize("prefix", ["assets", "assets-web", "materials"])
@pytest.mark.parametrize("attack", [
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fallure.db",   # encoded, so nothing normalises it away
    "..%2f..%2f..%2fallure.db",
    "probe/..%2f..%2f..%2fallure.db",
])
def test_traversal_out_of_the_shared_library_fails(client, prefix, attack):
    """Percent-encoded on purpose. A plain `../` never reaches the server."""
    alice = _register(client, ALICE)
    r = client.get(f"/files/{prefix}/{attack}", headers=alice)
    assert r.status_code in (404, 400), f"{prefix}/{attack} -> {r.status_code}"
    assert b"sqlite" not in r.content.lower()


# ── 4. the viewer and the share page still load their assets ─────────────

def test_a_signed_in_user_can_load_library_assets(client):
    """The /3d viewer. These used to be bare StaticFiles mounts the gate could
    not see; they are routes now, and must still serve."""
    alice = _register(client, ALICE)
    name = _seed_asset()
    r = client.get(f"/files/assets-web/{name}", headers=alice)
    assert r.status_code == 200 and r.content == b"glb"


def test_a_share_token_can_load_library_assets(client):
    """The share page's "Explore in 3D" tab draws the same meshes. Without this
    the tab loads an empty room - which P0-SEC-002 actually caused, and this is
    where it gets fixed."""
    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    token = _share(client, alice, pid)
    name = _seed_asset()

    client.cookies.clear()
    assert client.get(f"/files/assets-web/{name}", params={"k": token}).status_code == 200


def test_the_shared_library_is_not_world_readable(client):
    """A Meshy mesh is generated from somebody's moodboard crop, so a sofa in
    here can be as identifying as the photograph it came from."""
    _register(client, ALICE)
    name = _seed_asset()
    client.cookies.clear()
    assert client.get(f"/files/assets-web/{name}").status_code == 401


def test_a_share_token_reaches_the_scene_its_tour_points_at_and_no_other(client):
    """`explore.scene_url` is part of the published package, so the capability
    covers it - and only the scene belonging to that project."""
    from app.auth.authz import SCENE_READ, capability_allows
    from app.db.sqlite import get_db

    alice = _register(client, ALICE)
    pid = _project_with_files(client, alice)
    token = _share(client, alice, pid)
    get_db().execute(
        "INSERT INTO scene_specs(spec_id, project_id, scene_id, version, path, created_at)"
        " VALUES (?,?,?,?,?,?)",
        ("spec_probe", pid, "scene_probe", 1, "x", "2026-09-21T00:00:00Z"),
    )

    assert SCENE_READ.match("/api/scenes/scene_probe")
    assert SCENE_READ.match("/api/scenes/scene_probe/walkthrough/spawn")

    class _Req:
        """The rule is asserted directly: serving the route needs a real scene
        in the store, and this test is about who is ALLOWED, not what exists."""

        method = "GET"
        query_params = {"k": token}

        class url:
            path = "/api/scenes/scene_probe"

    assert capability_allows(_Req()) is True

    class _Other(_Req):
        class url:
            path = "/api/scenes/scene_belonging_to_nobody"

    assert capability_allows(_Other()) is False
