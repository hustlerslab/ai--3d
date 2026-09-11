"""Vertical-aware vocabulary, prompts and the vendor-swap contract.

Three things are pinned here:
  1. residential output is unchanged by the vertical work (the regression gate);
  2. a hospitality or office project can never be handed a residential room;
  3. a provider written against today's IntelligenceProvider protocol still
     works, unmodified, for a project in a vertical that did not exist when
     it was written — the vertical rides inside InputBundle, not in the
     method signatures.
"""
from __future__ import annotations

import inspect

import pytest

from app.intelligence import vocab
from app.intelligence.mock_provider import MockProvider
from app.intelligence.prompts import analysis_prompt, analysis_schema, objects_prompt, style_prompt, style_schema
from app.intelligence.provider import IntelligenceProvider, ResilientProvider
from app.intelligence.schema import DesignAnalysis, InputBundle, ObjectPlan, RoomAnalysis, StyleSpec
from app.projects import Vertical
from tests.test_intelligence import client  # noqa: F401  (fixture)

HOTEL_BRIEF = (
    "A 40-key boutique hotel in Goa. The lobby should feel warm and moody, the restaurant "
    "seats 80 covers, and there is a cocktail bar off the reception."
)
OFFICE_BRIEF = "A loft studio floor for 120 desks with exposed brick, two meeting rooms and a pantry."


# ── 1. the residential regression gate ───────────────────────────────────


def test_residential_vocabulary_is_byte_identical():
    assert vocab.room_types(Vertical.RESIDENTIAL) == [
        "living_room", "bedroom", "master_bedroom", "kids_bedroom", "kitchen",
        "dining_room", "bathroom", "study", "balcony", "entry", "other",
    ]
    assert vocab.room_default_dims(Vertical.RESIDENTIAL)["living_room"] == (6.0, 4.6)
    assert len(vocab.style_tags(Vertical.RESIDENTIAL)) == 22
    assert vocab.style_tags(Vertical.RESIDENTIAL)[0] == "modern"
    assert "boutique_hotel" not in vocab.style_tags(Vertical.RESIDENTIAL)
    # the domestic semantic list must not have grown a contract piece
    assert "banquette" not in vocab.semantic_types(Vertical.RESIDENTIAL)
    assert vocab.semantic_types(Vertical.RESIDENTIAL)[-1] == "other"


def test_unknown_vertical_fails_loudly():
    for bad in ("manufacturing", "", None, 3):
        with pytest.raises(ValueError):
            vocab.room_types(bad)
    with pytest.raises(ValueError):
        vocab.style_tags("retail")


# ── 2. the two new verticals ─────────────────────────────────────────────


def test_hospitality_rooms_are_commercial_scale():
    dims = vocab.room_default_dims(Vertical.HOSPITALITY)
    assert dims["hotel_lobby"] == (12.0, 9.0)
    assert dims["restaurant_floor"] == (14.0, 10.0)
    assert dims["guest_room"] == (4.5, 6.0)
    # every listed room type has a plausible commercial size
    for rtype in vocab.room_types(Vertical.HOSPITALITY):
        w, l = dims[rtype]
        assert w * l >= 20.0, rtype
    assert vocab.room_default_dims(Vertical.INDUSTRIAL)["open_plan_office"] == (16.0, 10.0)


def test_bhk_regex_does_not_fire_on_a_hotel_brief():
    assert vocab.brief_counts(HOTEL_BRIEF, Vertical.HOSPITALITY) == {"keys": 40, "covers": 80}
    assert vocab.brief_counts(OFFICE_BRIEF, Vertical.INDUSTRIAL) == {"desks": 120}
    assert vocab.brief_counts("2BHK in Pune", Vertical.RESIDENTIAL) == {"bedrooms": 2}
    # a hospitality brief must not produce bedrooms at all
    assert "bedrooms" not in vocab.brief_counts("two bedroom suite hotel", Vertical.HOSPITALITY)


def test_hospitality_analysis_has_no_residential_rooms(env):
    bundle = InputBundle(project_id="p", description=HOTEL_BRIEF, vertical=Vertical.HOSPITALITY)
    analysis = MockProvider().analyze_input(bundle)
    types = {r.type for r in analysis.rooms}
    assert types <= set(vocab.room_types(Vertical.HOSPITALITY))
    assert "bedroom" not in types
    assert {"hotel_lobby", "restaurant_floor", "bar", "reception"} <= types
    assert len(analysis.rooms) < 40, "40 keys must not become 40 rooms"
    assert "boutique_hotel" in analysis.keywords


def test_industrial_is_offices_not_a_factory(env):
    bundle = InputBundle(project_id="p", description=OFFICE_BRIEF, vertical=Vertical.INDUSTRIAL)
    analysis = MockProvider().analyze_input(bundle)
    types = {r.type for r in analysis.rooms}
    assert types <= set(vocab.room_types(Vertical.INDUSTRIAL))
    assert {"open_plan_office", "meeting_room", "pantry"} <= types
    assert "industrial" in analysis.keywords


def test_schema_enums_are_what_constrain_the_provider():
    for vertical in Vertical:
        rooms = analysis_schema(vertical)["properties"]["rooms"]["items"]["properties"]["type"]["enum"]
        assert rooms == vocab.room_types(vertical)
        assert style_schema(vertical)["properties"]["tags"]["items"]["enum"] == vocab.style_tags(vertical)
    hospitality_rooms = analysis_schema(Vertical.HOSPITALITY)["properties"]["rooms"]["items"]["properties"]["type"]
    assert "bedroom" not in hospitality_rooms["enum"]


def test_prompts_carry_the_vertical_from_the_bundle():
    bundle = InputBundle(project_id="p", description=HOTEL_BRIEF, vertical=Vertical.HOSPITALITY)
    prompt = analysis_prompt(bundle)
    assert "hotel lobby 11-14 m" in prompt and "banquet_hall" in prompt
    assert "modern apartment" not in prompt
    analysis = MockProvider().analyze_input(bundle)
    style = MockProvider().create_style_spec(analysis, bundle)
    assert "boutique_hotel" in style_prompt(analysis, bundle, [])
    assert "bar_counter" in objects_prompt(analysis, style, bundle)


# ── 3. the vendor-swap contract ──────────────────────────────────────────


class FakeVendorProvider:
    """A provider written against the protocol exactly as it stands today:
    three methods, each taking the bundle and nothing else. It was never
    told about verticals — it reads the one the bundle carries."""

    name = "fake_vendor"

    def analyze_input(self, bundle: InputBundle) -> DesignAnalysis:
        rooms = [
            RoomAnalysis(room_id=rtype, name=vocab.ROOM_LABELS[rtype], type=rtype, width_m=w, length_m=l)
            for rtype, (w, l) in list(vocab.room_default_dims(bundle.vertical).items())[:3]
        ]
        return DesignAnalysis(intent=bundle.description[:80], rooms=rooms, provider=self.name)

    def create_style_spec(self, analysis: DesignAnalysis, bundle: InputBundle) -> StyleSpec:
        tags = vocab.style_tags(bundle.vertical)[-2:]
        return StyleSpec(name="_".join(tags), tags=tags, palette=vocab.STYLE_PALETTES[tags[0]], provider=self.name)

    def plan_objects(self, analysis: DesignAnalysis, style: StyleSpec, bundle: InputBundle) -> ObjectPlan:
        return ObjectPlan(rooms=[r.room_id for r in analysis.rooms], provider=self.name)


def test_provider_protocol_signatures_are_unchanged():
    """The swap surface itself. If a vertical ever leaks into one of these
    signatures every vendor integration has to be rewritten, so pin them."""
    sigs = {
        name: str(inspect.signature(getattr(IntelligenceProvider, name)))
        for name in ("analyze_input", "create_style_spec", "plan_objects")
    }
    assert sigs == {
        "analyze_input": "(self, bundle: 'InputBundle') -> 'DesignAnalysis'",
        "create_style_spec": "(self, analysis: 'DesignAnalysis', bundle: 'InputBundle') -> 'StyleSpec'",
        "plan_objects": "(self, analysis: 'DesignAnalysis', style: 'StyleSpec', bundle: 'InputBundle') -> 'ObjectPlan'",
    }


def test_a_provider_written_for_the_old_protocol_serves_a_hospitality_project(env):
    """The fake implements only the three protocol methods and is touched by
    none of the vertical work; it must still run a hospitality project."""
    for name in ("analyze_input", "create_style_spec", "plan_objects"):
        assert inspect.signature(getattr(FakeVendorProvider, name)) == inspect.signature(
            getattr(IntelligenceProvider, name)
        )

    provider = ResilientProvider(FakeVendorProvider(), MockProvider(), allow_fallback=False)
    bundle = InputBundle(project_id="p", description=HOTEL_BRIEF, vertical=Vertical.HOSPITALITY)

    analysis = provider.analyze_input(bundle)
    style = provider.create_style_spec(analysis, bundle)
    plan = provider.plan_objects(analysis, style, bundle)

    assert provider.name == "fake_vendor" and analysis.provider == "fake_vendor"
    assert {r.type for r in analysis.rooms} <= set(vocab.room_types(Vertical.HOSPITALITY))
    assert style.tags == ["boutique_hotel", "brasserie"]
    assert plan.rooms == [r.room_id for r in analysis.rooms]


def test_analyze_job_records_the_vertical_for_cost_measurement(client, tmp_path):  # noqa: F811
    """Measurement only: the vertical rides on the events that already carry
    duration_ms, so spend can be split per vertical later."""
    from app.jobs import get_runner

    created = client.post("/api/projects", json={"name": "Goa hotel", "vertical": "hospitality"})
    pid = created.json()["project"]["project_id"]
    assert client.post(f"/api/projects/{pid}/inputs", data={"description": HOTEL_BRIEF}).status_code == 200
    job = client.post(f"/api/projects/{pid}/analyze", json={}).json()["job"]
    assert get_runner().wait_idle(30)

    data = client.get(f"/api/jobs/{job['job_id']}").json()["data"]
    assert data["job"]["status"] == "SUCCEEDED", data["job"]["error"]
    assert data["job"]["result"]["vertical"] == "hospitality"
    tagged = [e for e in data["events"] if "hospitality" in e["message"]]
    assert tagged and all(e["duration_ms"] >= 0 for e in tagged)

    analysis = client.get(f"/api/projects/{pid}/analysis").json()["data"]["analysis"]
    assert {r["type"] for r in analysis["rooms"]} <= set(vocab.room_types(Vertical.HOSPITALITY))
