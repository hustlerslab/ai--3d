"""P0-SEC-004 - sharing stays effortless without making every project public.

The four acceptance criteria, one section each:

  1. A share link opens the tour with no account.
  2. It grants NO access beyond the tour package.
  3. Revoking breaks the link.
  4. Guessing a project id does not grant access.

(4) is the one that changed. Before this task the project id WAS the
capability: anyone who saw an id in a URL, a log or a support email could read
that project's tour, and the owner could neither rotate the id nor revoke it.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

ALICE = ("alice@example.com", "alice-password-123")
BOB = ("bob@example.com", "bob-password-123")


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


def _project_with_tour(client, headers) -> str:
    """A project whose tour package exists on disk, as `preview` leaves it."""
    from app.projects.layout import ensure_layout, project_dir

    pid = client.post("/api/projects", json={"name": "Sharma Residence"}, headers=headers) \
                .json()["project"]["project_id"]
    ensure_layout(pid)
    web = project_dir(pid) / "outputs" / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "tour.json").write_text(
        json.dumps({"nodes": [{"id": "living_room", "pano_url": "/files/x.jpg", "yaw": 0}]}),
        encoding="utf-8",
    )
    return pid


def _share(client, headers, pid, **body):
    r = client.post(f"/api/projects/{pid}/share", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── 1. a share link opens the tour with no account ───────────────────────

def test_a_share_link_opens_the_tour_with_no_account(client):
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    link = _share(client, alice, pid, label="For the Sharmas")

    client.cookies.clear()                              # nobody at all
    r = client.get(f"/api/projects/{pid}/tour", params={"k": link["token"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["nodes"][0]["id"] == "living_room"


def test_the_link_the_owner_is_given_is_the_one_that_works(client):
    """The `url` field is what gets pasted into a message. If it does not work
    verbatim, the feature does not work."""
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    url = _share(client, alice, pid)["url"]

    assert url.startswith(f"/w/{pid}?k=")
    token = url.split("?k=", 1)[1]
    client.cookies.clear()
    assert client.get(f"/api/projects/{pid}/tour", params={"k": token}).status_code == 200


def test_the_owner_can_still_open_their_own_tour_while_signed_in(client):
    """Minting a link must not be a precondition for looking at your own work."""
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    assert client.get(f"/api/projects/{pid}/tour", headers=alice).status_code == 200


# ── 2. it grants no access beyond the tour package ───────────────────────

@pytest.mark.parametrize("suffix", [
    "", "/inputs", "/analysis", "/jobs", "/events", "/outputs", "/scene-spec",
    "/element-images", "/scene-reading", "/share",
])
def test_a_share_token_unlocks_nothing_but_the_tour(client, suffix):
    """The holder is a stranger with a link, not a member of the project."""
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    token = _share(client, alice, pid)["token"]

    client.cookies.clear()
    r = client.get(f"/api/projects/{pid}{suffix}", params={"k": token})
    assert r.status_code == 401, f"/projects/{{id}}{suffix} was reachable with a tour link"


def test_a_share_token_cannot_spend_money(client):
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    token = _share(client, alice, pid)["token"]

    client.cookies.clear()
    assert client.post(f"/api/projects/{pid}/elements/generate",
                       params={"k": token}).status_code == 401
    assert client.post(f"/api/projects/{pid}/jobs", params={"k": token},
                       json={"type": "generate_elements", "params": {}}).status_code == 401


def test_a_share_token_cannot_mint_more_share_tokens(client):
    """Otherwise one forwarded link becomes an unrevocable supply of links."""
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    token = _share(client, alice, pid)["token"]

    client.cookies.clear()
    assert client.post(f"/api/projects/{pid}/share", params={"k": token},
                       json={}).status_code == 401


def test_only_someone_who_may_see_the_project_can_mint_a_link(client):
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    bob = _register(client, BOB)

    assert client.post(f"/api/projects/{pid}/share", json={}, headers=bob).status_code == 403
    client.cookies.clear()
    assert client.post(f"/api/projects/{pid}/share", json={}).status_code == 401


# ── 3. revoking breaks the link ──────────────────────────────────────────

def test_revoking_breaks_the_link(client):
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    link = _share(client, alice, pid)

    client.cookies.clear()
    assert client.get(f"/api/projects/{pid}/tour", params={"k": link["token"]}).status_code == 200

    r = client.delete(f"/api/projects/{pid}/share/{link['token_id']}", headers=alice)
    assert r.status_code == 200 and r.json()["data"]["revoked"] is True

    client.cookies.clear()
    assert client.get(f"/api/projects/{pid}/tour",
                      params={"k": link["token"]}).status_code == 401


def test_revoking_one_link_leaves_the_others_working(client):
    """A link per recipient is the whole point: cutting off one builder must
    not cut off the client."""
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    first = _share(client, alice, pid, label="builder")
    second = _share(client, alice, pid, label="client")

    client.delete(f"/api/projects/{pid}/share/{first['token_id']}", headers=alice)

    client.cookies.clear()
    assert client.get(f"/api/projects/{pid}/tour", params={"k": first["token"]}).status_code == 401
    assert client.get(f"/api/projects/{pid}/tour", params={"k": second["token"]}).status_code == 200


def test_revoking_twice_is_not_an_error(client):
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    link = _share(client, alice, pid)

    client.delete(f"/api/projects/{pid}/share/{link['token_id']}", headers=alice)
    again = client.delete(f"/api/projects/{pid}/share/{link['token_id']}", headers=alice)
    assert again.status_code == 200 and again.json()["data"]["revoked"] is False


def test_a_revoked_link_stays_listed(client):
    """"It stopped working on the 3rd" is what people ask. A list that forgets
    revoked links cannot answer."""
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    link = _share(client, alice, pid, label="builder")
    client.delete(f"/api/projects/{pid}/share/{link['token_id']}", headers=alice)

    links = client.get(f"/api/projects/{pid}/share", headers=alice).json()["data"]["links"]
    row = next(x for x in links if x["token_id"] == link["token_id"])
    assert row["active"] is False and row["revoked_at"] and row["label"] == "builder"


def test_an_expired_link_stops_working(client):
    """Forced rather than waited for."""
    from app.auth.capability import _hash
    from app.db.sqlite import get_db

    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    link = _share(client, alice, pid, expires_in_days=30)

    get_db().execute(
        "UPDATE capability_tokens SET expires_at = '2020-01-01T00:00:00Z' WHERE token_hash = ?",
        (_hash(link["token"]),),
    )
    client.cookies.clear()
    assert client.get(f"/api/projects/{pid}/tour", params={"k": link["token"]}).status_code == 401


# ── 4. guessing a project id does not grant access ───────────────────────

def test_the_project_id_alone_no_longer_opens_the_tour(client):
    """THE change this task makes.

    Before P0-SEC-004 this returned 200 to anyone holding the id - and an id is
    not a secret: it travels in URLs, logs and support emails, and the owner
    can neither rotate nor revoke it.
    """
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)

    client.cookies.clear()
    assert client.get(f"/api/projects/{pid}/tour").status_code == 401


@pytest.mark.parametrize("bad", ["", "not-a-token", "k", "../../etc/passwd", "x" * 64])
def test_a_wrong_token_is_refused_the_same_way_as_no_token(client, bad):
    """A different answer for "wrong token" than for "no token" would be an
    oracle for guessing."""
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)

    client.cookies.clear()
    assert client.get(f"/api/projects/{pid}/tour", params={"k": bad}).status_code == 401


def test_a_token_for_one_project_does_not_open_another(client):
    """The token is validated against the project in the same query, so there
    is no branch where the wrong project can be returned and then rejected by a
    caller who forgets to check."""
    alice = _register(client, ALICE)
    mine = _project_with_tour(client, alice)
    theirs = _project_with_tour(client, alice)
    token = _share(client, alice, mine)["token"]

    client.cookies.clear()
    assert client.get(f"/api/projects/{theirs}/tour", params={"k": token}).status_code == 401
    assert client.get(f"/api/projects/{mine}/tour", params={"k": token}).status_code == 200


def test_two_links_are_never_the_same(client):
    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    tokens = {_share(client, alice, pid)["token"] for _ in range(5)}
    assert len(tokens) == 5
    assert all(len(t) >= 40 for t in tokens), "a short token is a guessable token"


def test_the_token_itself_is_never_stored(client):
    """A database leak must not hand over working share links."""
    from app.db.sqlite import get_db

    alice = _register(client, ALICE)
    pid = _project_with_tour(client, alice)
    token = _share(client, alice, pid)["token"]

    stored = [r["token_hash"] for r in get_db().query("SELECT token_hash FROM capability_tokens")]
    assert stored and token not in stored
    assert all(len(h) == 64 for h in stored), "expected sha256 hex"
