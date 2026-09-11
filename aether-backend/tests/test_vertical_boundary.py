"""Adversarial QA for the `vertical` feature.

Written to break the feature, not to confirm it. Five things are pinned:

  1. THE FACTORY BOUNDARY. No `Vertical` member is or can be a factory, no
     brief entry point routes to a compliance code path, and no such code
     path exists anywhere in `app/` (asserted by a scan, so it fails the day
     somebody adds one).
  2. CROSS-REPO DRIFT. The frontend's room-type option values are compared
     against the backend vocabulary for real, by reading the TypeScript. Drift
     is silent at runtime (`RoomHint.type` is a plain `str` and coerce.py
     degrades an unknown value to "other"), so it has to be caught here.
  3. END TO END per vertical on the mock provider, plus the residential
     regression gate.
  4. THE ERROR SURFACES the change introduced, including a real TOCTOU window
     in the PATCH stage gate.
  5. NO NEW TABLE — the honest answer to the RLS question in a codebase with
     no auth layer.

The `xfail(strict=True)` tests are deliberate: they record limits the current
implementation has. They pass (as xfail) today and turn into failures the day
the limit is fixed — at which point delete the marker and keep the assertion.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.projects_routes import OUT_OF_SCOPE_TERMS
from app.intelligence import vocab
from app.projects import ProjectStage, Vertical, get_project_store
from app.projects.layout import project_dir

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_VERTICALS_TS = REPO_ROOT / "aether-frontend" / "src" / "features" / "studio" / "verticals.ts"


@pytest.fixture
def client(env):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _pid(client, **body) -> str:
    r = client.post("/api/projects", json={"name": "probe", **body})
    assert r.status_code == 200, r.text
    return r.json()["project"]["project_id"]


# ════════════════════════════════════════════════════════════════════════
# 1. THE FACTORY BOUNDARY
# ════════════════════════════════════════════════════════════════════════

# Any word that would mean the product had started designing a plant rather
# than an interior. Checked against the enum, every room vocabulary and every
# object vocabulary.
FACTORY_WORDS = (
    "factory", "manufactur", "plant", "warehouse", "workshop", "assembly",
    "production", "machine", "shop_floor", "shopfloor", "forklift", "conveyor",
    "pallet", "racking", "loading_dock", "cnc", "press", "furnace", "boiler",
)


def test_no_vertical_is_or_could_be_a_factory():
    assert [v.value for v in Vertical] == ["residential", "hospitality", "industrial"]
    for v in Vertical:
        assert not any(w in v.value for w in FACTORY_WORDS), v


def test_no_room_or_object_type_in_any_vertical_is_a_factory_space():
    for v in Vertical:
        for rtype in vocab.room_types(v):
            assert not any(w in rtype for w in FACTORY_WORDS), f"{v.value}: room {rtype}"
        for sem in vocab.semantic_types(v):
            # "plant" the pot plant is furnishing, not a manufacturing plant
            if sem == "plant":
                continue
            assert not any(w in sem for w in FACTORY_WORDS), f"{v.value}: object {sem}"
        for tag in vocab.style_tags(v):
            # "industrial" as a *style* tag is the whole point and is allowed;
            # nothing else factory-shaped may appear.
            assert tag == "industrial" or not any(w in tag for w in FACTORY_WORDS), tag
    # the industrial vertical is offices
    assert set(vocab.room_types(Vertical.INDUSTRIAL)) == {
        "open_plan_office", "private_office", "meeting_room", "reception", "breakout", "pantry", "other",
    }


@pytest.mark.parametrize(
    "bad", ["factory", "manufacturing", "FACTORY", "Residential", "residential ", "", None, 3, ["residential"]]
)
def test_unknown_vertical_is_rejected_with_422(client, bad):
    """The status code is Pydantic's request-validation 422, not the guard's."""
    r = client.post("/api/projects", json={"name": "v", "vertical": bad})
    assert r.status_code == 422, f"{bad!r} -> {r.status_code} {r.text}"
    if bad is None:
        return  # on PATCH, null legitimately means "leave the vertical alone"
    pid = _pid(client)
    assert client.patch(f"/api/projects/{pid}", json={"vertical": bad}).status_code == 422


def test_vocab_accessors_raise_on_an_unknown_vertical_rather_than_defaulting():
    for accessor in (vocab.room_types, vocab.room_default_dims, vocab.room_keywords,
                     vocab.style_tags, vocab.semantic_types):
        for bad in ("factory", "manufacturing", "", None, 3):
            with pytest.raises(ValueError):
                accessor(bad)


# ── the guard: what it does catch ───────────────────────────────────────

BLOCKED = [
    "Design the layout of our manufacturing plant in Pune",
    "MANUFACTURING PLANT LAYOUT REQUIRED",                       # casing
    "Design our ManuFacturing Plant",                            # mixed casing
    "   manufacturing facility   ",                              # surrounding whitespace
    "We would like you to plan the factory floor next quarter",   # mid-sentence
    "(machine guarding) for the press area",                     # surrounding punctuation
    "Is this a load-bearing wall we can remove?",
    "Check the load bearing capacity of the mezzanine",
    "Calculate the structural load of the new partition",
    "Make sure the exits meet the fire code, please",
    "Compliance with the Factories Act, 1948 is required",
    "Needs to satisfy the OSH Code",
]

# Legitimate aesthetic work. A guard that blocks any of these is a bug.
ALLOWED = [
    "industrial",
    "loft",
    "exposed brick",
    "warehouse aesthetic",
    "industrial-style cafe",
    "concrete floors",
    "Industrial loft with exposed brick and black steel",
    "A warehouse aesthetic for the living room, lots of wood",
    "Industrial-style cafe, concrete floors, pendant lighting",
    "Loft-style office with exposed brick and factory windows",
    "Warm minimal two-bedroom flat",
    "A boutique hotel lobby, moody and warm",
]


def _entry_points(client, pid, text) -> dict[str, int]:
    """Every route that accepts a free-text brief. Returns {label: status}."""
    return {
        "POST /projects": client.post("/api/projects", json={"name": "p", "description": text}).status_code,
        "PATCH /projects/{id}": client.patch(f"/api/projects/{pid}", json={"description": text}).status_code,
        "POST /projects/{id}/inputs": client.post(
            f"/api/projects/{pid}/inputs", data={"description": text}
        ).status_code,
    }


@pytest.mark.parametrize("brief", BLOCKED)
def test_guard_refuses_at_every_brief_entry_point(client, brief):
    pid = _pid(client)
    for label, status in _entry_points(client, pid, brief).items():
        assert status == 422, f"{label} let through {brief!r}"
    r = client.post("/api/projects", json={"name": "p", "description": brief})
    assert r.json()["error"]["code"] == "OUT_OF_SCOPE"
    # a refused brief leaves no trace: no project, no input, no description file
    assert [p for p in client.get("/api/projects").json()["data"] if p["name"] == "p"] == []
    detail = client.get(f"/api/projects/{pid}").json()["data"]
    assert detail["inputs"] == [] and detail["project"]["description"] == ""
    assert not (project_dir(pid) / "input" / "description.txt").exists()


@pytest.mark.parametrize("brief", ALLOWED)
@pytest.mark.parametrize("vertical", ["residential", "hospitality", "industrial"])
def test_guard_passes_aesthetic_briefs_in_every_vertical(client, brief, vertical):
    pid = _pid(client, vertical=vertical)
    for label, status in _entry_points(client, pid, brief).items():
        assert status == 200, f"{label} wrongly refused {brief!r}"
    assert project_dir(pid).joinpath("input", "description.txt").read_text(encoding="utf-8").strip() == brief


# ── the guard: what it cannot catch ─────────────────────────────────────
#
# OUT_OF_SCOPE_TERMS is a plain lowercase substring scan over ten phrases.
# That buys casing- and position-insensitivity and nothing else. These are the
# evasions it structurally cannot see. They are recorded, not fixed — a
# substring scan is a courtesy filter, and the property that actually keeps
# the product safe is tested by test_no_compliance_logic_anywhere_in_the_backend
# and test_a_bypassed_factory_brief_still_produces_only_interior_rooms below.

KNOWN_EVASIONS = [
    ("double space",        "Design our manufacturing  plant"),
    ("newline separator",   "Design our manufacturing\nplant"),
    ("tab separator",       "Design our manufacturing\tplant"),
    ("non-breaking space",  "Design our manufacturing plant"),
    ("zero-width space",    "Design our manufacturing​ plant"),
    ("hyphen separator",    "Design our manufacturing-plant"),
    ("cyrillic homoglyph",  "Design our manufacturing plаnt"),
    ("fullwidth homoglyph", "Design our ｍanufacturing ｐlant"),
    ("bare 'factory'",      "Design our factory"),
    ("'shop floor'",        "Redesign the shop floor around the CNC"),
    ("'assembly line'",     "Lay out the assembly line"),
    ("'machine guard'",     "Specify machine guard for the press"),
    ("'fire-code' hyphen",  "Must meet the fire-code"),
    ("'egress'",            "Calculate means of egress width"),
    ("'occupancy load'",    "What is the occupancy load of this hall?"),
    ("NFPA / OSHA",         "Comply with NFPA 101 and OSHA"),
    ("'seismic load'",      "Seismic load calculation for the slab"),
]


@pytest.mark.xfail(
    strict=True,
    reason="the guard is a lowercase substring scan over 10 phrases; these evade it by construction",
)
@pytest.mark.parametrize("label,brief", KNOWN_EVASIONS, ids=[label for label, _ in KNOWN_EVASIONS])
def test_known_guard_evasions(client, label, brief):
    """Delete the xfail marker if the guard is ever normalised or widened."""
    assert client.post("/api/projects", json={"name": "p", "description": brief}).status_code == 422


# Fields that carry free text and are never handed to _scope_refusal at all.
UNSCANNED_SURFACES = ["project name", "room hint name", "dimensions room name", "analysis intent"]


@pytest.mark.xfail(
    strict=True,
    reason="_scope_refusal is only applied to `description`; these text fields are never scanned",
)
@pytest.mark.parametrize("surface", UNSCANNED_SURFACES)
def test_brief_text_surfaces_the_guard_never_sees(client, surface):
    factory = "manufacturing plant with machine guarding to the Factories Act"
    if surface == "project name":
        r = client.post("/api/projects", json={"name": factory})
    elif surface == "room hint name":
        r = client.post("/api/projects", json={"name": "p", "room_hints": [{"name": factory, "type": "other"}]})
    elif surface == "dimensions room name":
        pid = _pid(client)
        dims = json.dumps([{"name": factory, "type": "other", "width_m": 10, "length_m": 10}])
        r = client.post(f"/api/projects/{pid}/inputs", data={"dimensions": dims})
    else:  # analysis intent + constraints, written straight into design_analysis.json
        from app.jobs import get_runner

        pid = _pid(client)
        client.post(f"/api/projects/{pid}/inputs", data={"description": "Warm modern flat"})
        client.post(f"/api/projects/{pid}/analyze", json={})
        assert get_runner().wait_idle(90)
        r = client.patch(
            f"/api/projects/{pid}/analysis",
            json={"intent": factory, "constraints": ["fire code compliance", "machine guarding"]},
        )
    assert r.status_code == 422, f"{surface} accepted a factory brief"


def test_a_bypassed_factory_brief_still_produces_only_interior_rooms(client):
    """The invariant that actually matters. Text that slips past the guard is
    just text: the pipeline can only emit room types from the vertical's fixed
    vocabulary, so nothing factory-shaped can come out the other end."""
    from app.jobs import get_runner

    pid = _pid(client, vertical="industrial")
    evasion = "Plan our manufacturing-plant shop floor, assembly line and machine guard zones."
    assert client.post(f"/api/projects/{pid}/inputs", data={"description": evasion}).status_code == 200
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(90)
    analysis = client.get(f"/api/projects/{pid}/analysis").json()["data"]["analysis"]
    assert {r["type"] for r in analysis["rooms"]} <= set(vocab.room_types(Vertical.INDUSTRIAL))
    for room in analysis["rooms"]:
        assert not any(w in room["type"] for w in FACTORY_WORDS), room
    for obj in analysis["spotted_objects"]:
        assert obj["semantic_type"] in vocab.semantic_types(Vertical.INDUSTRIAL)


# ── no compliance code path exists at all ───────────────────────────────

# Concepts this product must never compute. A match is tolerated only when the
# line is a bare string literal or a comment — i.e. refusal text, never logic.
COMPLIANCE_PATTERN = re.compile(
    r"\b(fire[ _-]?code|fire[ _-]?rating|egress|occupancy[ _-]?load|sprinkler|nfpa|osha|"
    r"osh[ _-]code|factories[ _-]act|load[ _-]?bearing|structural[ _-]?load|live[ _-]?load|"
    r"dead[ _-]?load|machine[ _-]?guard\w*|seismic|building[ _-]code|means[ _-]of[ _-]egress|"
    r"fire[ _-]?exit|safety[ _-]?factor)\b",
    re.IGNORECASE,
)
SCANNED_DIRS = ("app", "blender", "scripts")


def _compliance_hits() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for d in SCANNED_DIRS:
        base = BACKEND_ROOT / d
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if COMPLIANCE_PATTERN.search(line):
                    hits.append((str(path.relative_to(BACKEND_ROOT)).replace("\\", "/"), n, line.strip()))
    return hits


def test_no_compliance_logic_anywhere_in_the_backend():
    """Literal-factory and building-compliance work is permanently out of
    scope. This fails the day anyone adds load, fire, egress, occupancy or
    safety-code logic — including inside a vertical branch."""
    offenders = [
        (f, n, line)
        for f, n, line in _compliance_hits()
        # a bare string literal or a comment is refusal copy, not logic
        if not (line.startswith("#") or re.match(r"""^f?["'].*["'],?$""", line))
    ]
    assert offenders == [], f"compliance-shaped code found: {offenders}"


def test_the_only_compliance_words_in_the_backend_are_the_refusal_list():
    files = {f for f, _, _ in _compliance_hits()}
    assert files <= {"app/api/projects_routes.py"}, f"regulatory vocabulary leaked into {files}"
    for _, _, line in _compliance_hits():
        # refusal terms and refusal copy only — a comment or a bare literal
        assert re.match(r"""^(#|f?["'])""", line), line


def test_out_of_scope_terms_are_facility_phrases_not_aesthetic_ones():
    """A term like 'industrial' or 'loft' in this list would break every
    legitimate brief; assert the list stays facility-only."""
    for term in OUT_OF_SCOPE_TERMS:
        assert term == term.lower(), term
        assert not any(a in term for a in ("industrial", "loft", "brick", "warehouse", "concrete")), term
    aesthetic = {"industrial", "loft", "exposed brick", "warehouse", "concrete", "brick", "steel", "cafe"}
    assert aesthetic.isdisjoint(set(OUT_OF_SCOPE_TERMS))


# ════════════════════════════════════════════════════════════════════════
# 2. CROSS-REPO ENUM DRIFT
# ════════════════════════════════════════════════════════════════════════
#
# `RoomHint.type` is a plain `str`, and coerce.py degrades an unknown value to
# "other" with no error. Drift between the frontend selector and the backend
# vocabulary therefore produces quietly mis-typed rooms and never a 4xx, so it
# is compared here by reading the actual TypeScript.


def _frontend_source(name: str = "verticals.ts") -> str:
    path = FRONTEND_VERTICALS_TS.with_name(name)
    if not path.exists():
        pytest.skip(f"frontend checkout not present at {path}")
    return path.read_text(encoding="utf-8")


def _parse_ts_record(source: str, name: str) -> dict[str, list[str]]:
    """Pull `const NAME: Record<Vertical, readonly string[]> = { ... };` out of
    the TypeScript. Deliberately dumb — if the shape changes this fails loudly
    rather than silently matching nothing."""
    block = re.search(rf"const {name}\s*:[^=]*=\s*\{{(.*?)\n\}};", source, re.DOTALL)
    assert block, f"could not find `const {name}` in verticals.ts"
    out: dict[str, list[str]] = {}
    for key, values in re.findall(r"^\s*(\w+)\s*:\s*\[(.*?)\],\s*$", block.group(1), re.MULTILINE):
        out[key] = re.findall(r'"([^"]+)"', values)
    assert out, f"parsed no entries out of {name}"
    return out


def test_frontend_room_type_options_match_the_backend_vocabulary():
    ts = _parse_ts_record(_frontend_source(), "ROOM_TYPES")
    assert set(ts) == {v.value for v in Vertical}, "frontend ROOM_TYPES keys drifted from the Vertical enum"
    for vertical in Vertical:
        # "other" is the coercion sink; the UI deliberately does not offer it
        backend = set(vocab.room_types(vertical)) - {"other"}
        frontend = set(ts[vertical.value])
        assert frontend == backend, (
            f"{vertical.value}: frontend-only {sorted(frontend - backend)}, "
            f"backend-only {sorted(backend - frontend)}"
        )


def test_frontend_default_room_type_is_valid_for_its_vertical():
    source = _frontend_source()
    ts_rooms = _parse_ts_record(source, "ROOM_TYPES")
    block = re.search(r"const DEFAULT_ROOM_TYPE\s*:[^=]*=\s*\{(.*?)\n\};", source, re.DOTALL)
    assert block, "could not find `const DEFAULT_ROOM_TYPE` in verticals.ts"
    defaults = dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"', block.group(1)))
    assert set(defaults) == {v.value for v in Vertical}
    for vertical, rtype in defaults.items():
        assert rtype in ts_rooms[vertical]
        assert rtype in vocab.room_types(Vertical(vertical)), f"{vertical} default {rtype!r} unknown to the backend"


def test_frontend_vertical_union_matches_the_backend_enum():
    m = re.search(r"export type Vertical\s*=\s*([^;]+);", _frontend_source("types.ts"))
    assert m, "frontend no longer declares `export type Vertical`"
    assert re.findall(r'"([^"]+)"', m.group(1)) == [v.value for v in Vertical]


def test_frontend_vertical_option_values_match_the_backend_enum():
    source = _frontend_source()
    values = re.findall(r'\{\s*value:\s*"([^"]+)"', source)
    assert values == [v.value for v in Vertical], f"VERTICAL_OPTIONS drifted: {values}"


def test_an_unknown_room_type_really_does_degrade_silently():
    """Why the drift check above has to exist: nothing rejects a bad type."""
    from app.intelligence.coerce import coerce_analysis
    from app.intelligence.schema import InputBundle
    from app.projects.schema import RoomHint

    RoomHint(name="Lobby", type="totally_made_up")  # a plain str: accepted, no error
    bundle = InputBundle(project_id="p", vertical=Vertical.HOSPITALITY)
    analysis = coerce_analysis({"rooms": [{"name": "Lobby", "type": "living_room"}]}, bundle, [], "test")
    # "living_room" is not in the hospitality vocabulary and is silently "other"
    assert analysis.rooms[0].type == "other"


# ════════════════════════════════════════════════════════════════════════
# 3. END TO END PER VERTICAL (mock provider; no keys, no Blender)
# ════════════════════════════════════════════════════════════════════════

E2E_BRIEFS = {
    "residential": "Warm modern 3BHK in Pune with a master bedroom, a kitchen and a study.",
    "hospitality": (
        "A 40-key boutique hotel in Goa. The lobby should feel warm and moody, the restaurant "
        "seats 80 covers, and there is a cocktail bar off the reception."
    ),
    "industrial": "A loft studio floor for 120 desks with exposed brick, two meeting rooms and a pantry.",
}
E2E_EXPECT = {
    "residential": {"living_room", "kitchen", "master_bedroom", "bedroom"},
    "hospitality": {"hotel_lobby", "restaurant_floor", "bar", "reception"},
    "industrial": {"open_plan_office", "meeting_room", "pantry"},
}


@pytest.mark.parametrize("vertical", ["residential", "hospitality", "industrial"])
def test_pipeline_end_to_end_per_vertical(client, vertical):
    from app.jobs import get_runner

    pid = _pid(client, name=vertical, vertical=vertical)
    assert client.post(f"/api/projects/{pid}/inputs", data={"description": E2E_BRIEFS[vertical]}).status_code == 200
    job = client.post(f"/api/projects/{pid}/analyze", json={}).json()["job"]
    assert get_runner().wait_idle(90)
    assert client.get(f"/api/jobs/{job['job_id']}").json()["data"]["job"]["status"] == "SUCCEEDED"

    analysis = client.get(f"/api/projects/{pid}/analysis").json()["data"]["analysis"]
    types = {r["type"] for r in analysis["rooms"]}
    assert types <= set(vocab.room_types(Vertical(vertical))), f"{vertical} produced foreign rooms: {types}"
    assert E2E_EXPECT[vertical] <= types, f"{vertical} missing {E2E_EXPECT[vertical] - types}"

    assert client.post(f"/api/projects/{pid}/scene-plan", json={}).status_code == 200
    assert get_runner().wait_idle(180)
    spec = client.get(f"/api/projects/{pid}/scene-spec")
    assert spec.status_code == 200, spec.text
    data = spec.json()["data"]
    assert data["violations"] == []
    assert data["scene"]["objects"]
    plan_types = {i["semantic_type"] for i in data["object_plan"]["items"]}
    assert plan_types <= set(vocab.semantic_types(Vertical(vertical)))


def test_a_hospitality_project_cannot_produce_a_bedroom(client):
    from app.jobs import get_runner

    pid = _pid(client, name="hotel", vertical="hospitality")
    client.post(f"/api/projects/{pid}/inputs", data={"description": E2E_BRIEFS["hospitality"]})
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(90)
    client.post(f"/api/projects/{pid}/scene-plan", json={})
    assert get_runner().wait_idle(180)

    assert "bedroom" not in vocab.room_types(Vertical.HOSPITALITY)
    for name in ("analysis/design_analysis.json", "planning/object_plan.json"):
        path = project_dir(pid) / name
        assert path.exists(), name
        blob = json.dumps(json.loads(path.read_text(encoding="utf-8")))
        assert "bedroom" not in blob.replace("bedside_table", ""), name

    # even an explicit residential room hint is coerced out of a hospitality plan
    pid2 = _pid(client, vertical="hospitality", room_hints=[{"name": "Master", "type": "master_bedroom"}])
    client.post(f"/api/projects/{pid2}/inputs", data={"description": "a small hotel"})
    client.post(f"/api/projects/{pid2}/analyze", json={})
    assert get_runner().wait_idle(90)
    rooms = client.get(f"/api/projects/{pid2}/analysis").json()["data"]["analysis"]["rooms"]
    assert {r["type"] for r in rooms} <= set(vocab.room_types(Vertical.HOSPITALITY))
    assert all(r["type"] != "master_bedroom" for r in rooms)


def test_residential_is_the_default_and_needs_no_client_change(client):
    """A client that predates the feature sends no `vertical` and must get the
    same residential behaviour it always had."""
    from app.jobs import get_runner

    pid = _pid(client, name="legacy client")
    assert client.get(f"/api/projects/{pid}").json()["data"]["project"]["vertical"] == "residential"
    client.post(f"/api/projects/{pid}/inputs", data={"description": E2E_BRIEFS["residential"]})
    client.post(f"/api/projects/{pid}/analyze", json={})
    assert get_runner().wait_idle(90)
    rooms = client.get(f"/api/projects/{pid}/analysis").json()["data"]["analysis"]["rooms"]
    assert {r["type"] for r in rooms} == {"living_room", "kitchen", "master_bedroom", "bedroom"}
    dims = {r["type"]: (r["width_m"], r["length_m"]) for r in rooms}
    assert dims["living_room"] == (6.0, 4.6) and dims["kitchen"] == (3.8, 3.0)


# ════════════════════════════════════════════════════════════════════════
# 4. ERROR HANDLING ON THE NEW / CHANGED SURFACES
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/projects/proj_missing"),
        ("patch", "/api/projects/proj_missing"),
        ("post", "/api/projects/proj_missing/inputs"),
        ("post", "/api/projects/proj_missing/analyze"),
        ("post", "/api/projects/proj_missing/scene-plan"),
        ("get", "/api/projects/proj_missing/analysis"),
        ("patch", "/api/projects/proj_missing/analysis"),
        ("get", "/api/projects/proj_missing/inputs"),
    ],
)
def test_a_missing_project_is_a_clean_404_on_every_touched_route(client, method, path):
    call = getattr(client, method)
    r = call(path) if method == "get" else call(path, json={})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code}"
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_vertical_is_locked_once_the_project_leaves_created(client):
    pid = _pid(client)
    assert client.patch(f"/api/projects/{pid}", json={"vertical": "industrial"}).status_code == 200
    get_project_store().set_stage(pid, ProjectStage.ANALYZING)
    r = client.patch(f"/api/projects/{pid}", json={"vertical": "residential"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "VERTICAL_LOCKED"
    # a no-op resend and an unrelated field must still work
    assert client.patch(f"/api/projects/{pid}", json={"vertical": "industrial"}).status_code == 200
    assert client.patch(f"/api/projects/{pid}", json={"name": "Renamed"}).status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["data"]["project"]["vertical"] == "industrial"


def test_patch_vertical_stage_gate_has_no_toctou_window(client, monkeypatch):
    """The route does `current = store.get(...)`, compares `current.stage`, then
    calls `store.update(...)` in a *different* transaction. A stage change that
    lands in that window (a concurrent POST /inputs, or an analyze job starting)
    is not seen, and the vertical is changed on a project that has already left
    CREATED. The interleaving is forced deterministically here, not raced.
    """
    from app.projects.store import ProjectStore

    pid = _pid(client)
    original = ProjectStore.update

    def racing_update(self, project_id, **kwargs):
        # a concurrent transition landing between the route's read and its write
        if self.get(project_id).stage == ProjectStage.CREATED:
            self.set_stage(project_id, ProjectStage.INPUT_RECEIVED)
        return original(self, project_id, **kwargs)

    monkeypatch.setattr(ProjectStore, "update", racing_update)
    r = client.patch(f"/api/projects/{pid}", json={"vertical": "hospitality"})
    stage = client.get(f"/api/projects/{pid}").json()["data"]["project"]["stage"]
    assert r.status_code == 409, f"vertical changed after the project reached {stage}"


def test_empty_and_whitespace_briefs_are_accepted_and_never_refused(client):
    for text in ("", "   ", "\n\t "):
        assert client.post("/api/projects", json={"name": "p", "description": text}).status_code == 200
    pid = _pid(client)
    # an empty description must not create a phantom input record
    r = client.post(f"/api/projects/{pid}/inputs", data={"description": "   "})
    assert r.status_code == 200 and r.json()["inputs"] == []
    # ...and analysing with no content at all is a clean 422, not a crash
    r = client.post(f"/api/projects/{pid}/analyze", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_INPUTS"


def test_an_enormous_brief_is_rejected(client):
    """A multi-megabyte description is accepted, lowercased in full by the
    scope guard, written to disk and stored in SQLite. Nothing bounds it."""
    huge = "warm modern flat. " * 250_000  # ~4.5 MB
    r = client.post("/api/projects", json={"name": "huge", "description": huge})
    assert r.status_code in (413, 422), f"accepted a {len(huge)} byte brief"


def test_malformed_dimensions_is_a_clean_422(client):
    pid = _pid(client)
    for bad in ("not json", "[1,2,3]", '[{"width_m": "wide"}]', '"a string"', "null"):
        r = client.post(f"/api/projects/{pid}/inputs", data={"dimensions": bad})
        assert r.status_code == 422, f"{bad!r} -> {r.status_code}"
        assert r.json()["error"]["code"] == "INVALID_DIMENSIONS"


@pytest.mark.xfail(
    strict=True,
    reason="pre-existing (predates the vertical work): a JSON object iterates to zero rooms instead of failing",
)
def test_a_json_object_in_dimensions_is_rejected_not_silently_treated_as_no_rooms(client):
    """`json.loads("{}")` iterates over zero keys, so the list comprehension in
    add_inputs succeeds with an empty list. The malformed payload is accepted
    with 200, an input record claiming `rooms: 0` is written, and — worse —
    `store.update(room_hints=[])` WIPES any room hints the project already had.
    """
    pid = _pid(client, room_hints=[{"name": "Living", "type": "living_room", "width_m": 6, "length_m": 4}])
    r = client.post(f"/api/projects/{pid}/inputs", data={"dimensions": "{}"})
    assert r.status_code == 422, (
        f"accepted a malformed dimensions object; room_hints are now "
        f"{client.get(f'/api/projects/{pid}').json()['data']['project']['room_hints']}"
    )


def test_no_hard_coded_secrets_or_vendor_endpoints_in_the_vertical_code():
    """Nothing this feature touched may carry a key, a token or a vendor URL."""
    suspects = re.compile(
        r"(sk-[A-Za-z0-9]{8,}|AIza[A-Za-z0-9_\-]{10,}|api[_-]?key\s*=\s*[\"'][^\"'\s]{8,}[\"']|"
        r"secret\s*=\s*[\"'][^\"'\s]{6,}[\"']|Bearer\s+[A-Za-z0-9._\-]{12,})",
        re.IGNORECASE,
    )
    for rel in ("app/api/projects_routes.py", "app/projects/schema.py", "app/projects/store.py",
                "app/db/sqlite.py", "app/intelligence/vocab.py", "app/intelligence/bundle.py",
                "app/intelligence/coerce.py", "app/intelligence/schema.py", "app/catalog/catalog.py"):
        text = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
        assert not suspects.search(text), f"possible secret in {rel}"
        assert "http://" not in text and "https://" not in text, f"vendor endpoint hard-coded in {rel}"


# ════════════════════════════════════════════════════════════════════════
# 5. NO NEW TABLE (the "RLS" question, answered for a repo that has none)
# ════════════════════════════════════════════════════════════════════════


def test_the_vertical_change_added_a_column_and_no_new_table():
    """There is no auth layer and no RLS in this codebase — there is nothing to
    apply a row policy to. The reviewable claim is the narrow one: the feature
    added exactly one column to `projects` and created no table, so it opens no
    new data surface."""
    import inspect

    from app.db.sqlite import MIGRATIONS, SCHEMA, SCHEMA_VERSION, _v2_project_vertical

    assert SCHEMA_VERSION == 2
    assert [v for v, _ in MIGRATIONS] == [2]
    tables = sorted(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", "\n".join(SCHEMA)))
    assert tables == ["analyses", "events", "inputs", "jobs", "meta", "outputs", "projects", "scene_specs"]

    src = inspect.getsource(_v2_project_vertical)
    assert "_add_column" in src or "ADD COLUMN" in src
    for forbidden in ("CREATE TABLE", "DROP", "DELETE FROM", "GRANT", "POLICY"):
        assert forbidden not in src.upper(), forbidden


# ════════════════════════════════════════════════════════════════════════
# 6. SWAP-INTERFACE REGRESSION — the parts test_verticals.py does not prove
# ════════════════════════════════════════════════════════════════════════
#
# tests/test_verticals.py pins the three Protocol signatures and exercises a
# `FakeVendorProvider` — but that fake calls `vocab.room_default_dims(
# bundle.vertical)`, i.e. it is written against the NEW helper API. It
# therefore proves the signatures are stable; it does not prove that a
# provider written before the feature still works. These do.


class VerticalObliviousProvider:
    """A provider from before the feature: it implements the Protocol, reads
    nothing but `bundle.description`, and has never heard of a vertical."""

    name = "oblivious_vendor"

    def analyze_input(self, bundle):
        from app.intelligence.schema import DesignAnalysis, RoomAnalysis

        return DesignAnalysis(
            intent=bundle.description[:80] or "brief",
            rooms=[RoomAnalysis(room_id="living_room", name="Living Room", type="living_room",
                                width_m=6.0, length_m=4.6)],
            provider=self.name,
        )

    def create_style_spec(self, analysis, bundle):
        from app.intelligence.schema import StyleSpec

        return StyleSpec(name="modern_warm", tags=["modern", "warm"], palette=["#FFFFFF"], provider=self.name)

    def plan_objects(self, analysis, style, bundle):
        from app.intelligence.schema import ObjectPlan

        return ObjectPlan(rooms=[r.room_id for r in analysis.rooms], provider=self.name)


def test_a_provider_that_never_reads_the_vertical_still_runs(env):
    """The swap contract that matters: nothing in the pipeline requires a
    provider to know a vertical exists."""
    import inspect

    from app.intelligence.mock_provider import MockProvider
    from app.intelligence.provider import IntelligenceProvider, ResilientProvider
    from app.intelligence.schema import InputBundle

    for name in ("analyze_input", "create_style_spec", "plan_objects"):
        mine = list(inspect.signature(getattr(VerticalObliviousProvider, name)).parameters)
        theirs = list(inspect.signature(getattr(IntelligenceProvider, name)).parameters)
        assert mine == theirs, name

    provider = ResilientProvider(VerticalObliviousProvider(), MockProvider(), allow_fallback=False)
    for vertical in Vertical:
        bundle = InputBundle(project_id="p", description="a space", vertical=vertical)
        analysis = provider.analyze_input(bundle)
        style = provider.create_style_spec(analysis, bundle)
        plan = provider.plan_objects(analysis, style, bundle)
        assert analysis.provider == plan.provider == "oblivious_vendor"


@pytest.mark.xfail(
    strict=True,
    reason="RoomAnalysis.type is a plain str; the vertical is enforced by the JSON schema and coerce.py, "
           "never on a Protocol provider's returned objects",
)
def test_a_vendor_provider_cannot_return_a_room_outside_its_vertical(env):
    """Honest limit on 'a hospitality project cannot produce a bedroom': that
    holds for the mock and for any provider whose raw JSON goes through
    coerce.py. A provider returning typed objects directly is not filtered."""
    from app.intelligence.schema import InputBundle

    bundle = InputBundle(project_id="p", description="hotel", vertical=Vertical.HOSPITALITY)
    analysis = VerticalObliviousProvider().analyze_input(bundle)
    assert {r.type for r in analysis.rooms} <= set(vocab.room_types(Vertical.HOSPITALITY))


@pytest.mark.xfail(
    strict=True,
    reason="the vertical work deleted these module constants instead of deprecating them",
)
@pytest.mark.parametrize(
    "module,name",
    [("vocab", "ROOM_TYPES"), ("vocab", "ROOM_KEYWORDS"), ("vocab", "ROOM_DEFAULT_DIMS"),
     ("vocab", "SEMANTIC_TYPES"), ("vocab", "STYLE_TAGS"),
     ("prompts", "ANALYSIS_SCHEMA"), ("prompts", "STYLE_SCHEMA")],
)
def test_the_shared_helper_constants_a_pre_feature_provider_used_still_exist(module, name):
    """The Protocol itself is unchanged (app/intelligence/provider.py is
    byte-identical to the previous commit), but the helper module that both
    in-tree providers import lost these public names. An out-of-tree provider
    that used them breaks on import. Scope the swap-interface claim to the
    Protocol, not to `app.intelligence` as a whole."""
    import importlib

    assert hasattr(importlib.import_module(f"app.intelligence.{module}"), name)


def test_no_route_was_added_and_no_authorization_surface_widened(client):
    """The feature added no endpoint: `vertical` is a field on two existing
    request bodies. Every project route is still reachable by project id alone —
    that is pre-existing and unchanged, not something this change introduced."""
    from app.main import app

    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert not any("vertical" in p for p in paths), paths
    pid = _pid(client, vertical="hospitality")
    assert client.get(f"/api/projects/{pid}").status_code == 200
