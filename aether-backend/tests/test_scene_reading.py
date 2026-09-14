"""Reading an approved render back into elements.

Every case here is a box a vision model really returned during Stage 2
validation, kept verbatim: the point of the file is that these exact failures
cannot come back quietly.
"""
from __future__ import annotations

from pathlib import Path

from app.intelligence.prompts import element_check_prompt
from app.intelligence.schema import SceneElement, SceneReading
from app.intelligence.scene_reading import (  # noqa: F401
    MIN_LEGIBLE_PX, UPSCALE_SHORT_PX, _bbox, _upscaled, approved_for_generation,
    check_element_crops, estimate_dimensions, mark_duplicates)


def test_mixed_convention_box_is_rejected_out_loud():
    """The real one. Gemini returned this for 'large teal and striped sofa'.

    Three coordinates are 0-1000; `1.0` is the right edge written as a fraction.
    The old rule was "if anything exceeds 1.5 divide the lot by 1000", which
    turned that 1.0 into 0.001, and a `sorted()` then swapped the inverted pair
    so nothing looked wrong. The crop came from the left 40 % of the image
    instead of the right 60 % - a plausible-looking picture of the wrong thing,
    which is worse than no picture at all.
    """
    warn: list[str] = []
    assert _bbox([402, 237, 1.0, 712], warn, "living_room/sofa") is None
    assert len(warn) == 1
    assert "mixes 0-1000 with fractions" in warn[0]
    assert "living_room/sofa" in warn[0]      # says WHICH element, not just that one failed


def test_mixed_convention_curtains_are_rejected_out_loud():
    """Second real one, same render: two fractions beside an out-of-range 4.49."""
    warn: list[str] = []
    assert _bbox([0.702, 0.0, 1.0, 4.49], warn, "living_room/curtains") is None
    assert warn and "mixes 0-1000 with fractions" in warn[0]


def test_both_conventions_are_read_when_a_box_is_self_consistent():
    assert _bbox([0.1, 0.2, 0.6, 0.8]) == (0.1, 0.2, 0.6, 0.8)
    assert _bbox([100, 200, 600, 800]) == (0.1, 0.2, 0.6, 0.8)
    # 0 is the one value that is honest in both conventions, so it must not
    # make an otherwise-0-1000 box look mixed.
    assert _bbox([0.0, 149, 273, 584]) == (0.0, 0.149, 0.273, 0.584)


def test_reversed_corners_are_rejected_rather_than_silently_swapped():
    warn: list[str] = []
    assert _bbox([0.8, 0.2, 0.3, 0.6], warn) is None
    assert warn and "top-left" in warn[0]


def test_whole_image_box_is_rejected():
    warn: list[str] = []
    assert _bbox([0, 0, 1, 1], warn) is None
    assert warn and "whole image" in warn[0]


def test_junk_is_rejected_with_a_reason():
    for raw, why in ([1, 2, 3], "not four"), ("nope", "not four"), ([1, 2, "x", 4], "not numeric"):
        warn: list[str] = []
        assert _bbox(raw, warn) is None
        assert warn and why in warn[0], (raw, warn)


def test_size_no_longer_decides_what_survives():
    """The area gate is gone on purpose, and this is the case that killed it.

    A 59 x 88 towel rail was discarded for being under 6,000 px^2 while three
    stools boxed as one "bar stool" and a bed boxed as a "rug" passed on size
    alone. Measured across our whole crop range, silhouette detail survives at
    83-95 % and texture at 1-36 %, and image-to-3D reads the silhouette - so
    area was ranking crops by the wrong property. What remains is a floor for
    "there is no shape here at all"; judging the rest is the check's job, then
    a person's.
    """
    from PIL import Image

    towel = Image.new("RGB", (59, 88))
    assert min(towel.size) >= MIN_LEGIBLE_PX            # kept now; 5,192 px^2 once wasn't
    rug_edge_on = Image.new("RGB", (538, 59))
    assert min(rug_edge_on.size) >= MIN_LEGIBLE_PX
    assert min(Image.new("RGB", (900, 8)).size) < MIN_LEGIBLE_PX   # a sliver still has none


def test_crops_are_enlarged_towards_the_validated_input_size():
    from PIL import Image

    up = _upscaled(Image.new("RGB", (59, 88)))
    assert min(up.size) == UPSCALE_SHORT_PX
    assert up.size == (512, 764)

    # A long thin piece is capped on its long side rather than becoming a strip
    # whose base64 body is most of the request.
    wide = _upscaled(Image.new("RGB", (522, 90)))
    assert max(wide.size) <= 1536 and min(wide.size) < UPSCALE_SHORT_PX

    # Already big enough is left exactly alone - this step never shrinks.
    big = Image.new("RGB", (1024, 452))
    assert _upscaled(big).size == (1024, 452)


# ── the second look ───────────────────────────────────────────────────────


def _el(room="living_room", name="table lamp", sem="table_lamp", box=(0.1, 0.1, 0.3, 0.4), crop="c.png"):
    return SceneElement(element_id="el_" + name.replace(" ", ""), room_id=room, name=name,
                        semantic_type=sem, bbox=box, crop_ref=crop)


class _Answers:
    """Stands in for the vision model: one canned answer per crop."""

    def __init__(self, **by_crop):
        self.by_crop, self.calls = by_crop, []

    def check_element_crop(self, crop, room_type, vertical):
        self.calls.append((Path(crop).name, room_type))
        return self.by_crop.get(Path(crop).stem, {})


def _run(elements, answers, tmp_path):
    reading = SceneReading(elements=elements)
    return check_element_crops(reading, {"living_room": "living_room", "kitchen": "kitchen"},
                               "residential", tmp_path, answers), reading


def test_a_floor_plank_labelled_table_lamp_is_caught(tmp_path):
    """The real case. The box was structurally perfect; the crop was floorboards."""
    el = _el(crop="lamp.png")
    _, reading = _run([el], _Answers(lamp={"sees": "bare wooden floorboards", "semantic_type": "other",
                                           "fills_frame": True, "certain": True}), tmp_path)
    assert reading.elements[0].check == "mismatch"
    assert "floorboards" in reading.elements[0].check_note


def test_a_bed_labelled_rug_is_caught(tmp_path):
    el = _el(name="fluffy white rug", sem="rug", crop="rug.png")
    _, reading = _run([el], _Answers(rug={"sees": "a bed", "semantic_type": "bed",
                                          "fills_frame": True, "certain": True}), tmp_path)
    assert reading.elements[0].check == "mismatch"


def test_a_whole_room_labelled_as_one_piece_is_caught(tmp_path):
    el = _el(room="kitchen", name="kitchen counter", sem="kitchen_counter", crop="counter.png")
    _, reading = _run([el], _Answers(counter={"sees": "a kitchen island with three stools",
                                              "semantic_type": "kitchen_counter",
                                              "fills_frame": False, "certain": True}), tmp_path)
    assert reading.elements[0].check == "crowded"


def test_a_correct_crop_passes(tmp_path):
    el = _el(name="wooden side table", sem="side_table", crop="side.png")
    _, reading = _run([el], _Answers(side={"sees": "a small wooden side table", "semantic_type": "side_table",
                                           "fills_frame": True, "certain": True}), tmp_path)
    assert reading.elements[0].check == "ok"


def test_the_check_is_never_told_what_it_is_looking_at(tmp_path):
    """Asked 'is this a table lamp?' a vision model agrees. The prompt must not
    mention the label, and the crop must arrive with no scene around it."""
    text = element_check_prompt("living_room", "residential").lower()
    for leak in ("table lamp", "expected", "confirm", "is this a"):
        assert leak not in text, leak


def test_a_failed_check_is_not_a_pass(tmp_path):
    """An empty or unsure answer routes the crop to a human, never to spend."""
    for answer in ({}, {"sees": "something", "fills_frame": True, "certain": False}):
        _, reading = _run([_el(crop="x.png")], _Answers(x=answer), tmp_path)
        assert reading.elements[0].check == "unreadable"
        ready, held = approved_for_generation(reading)
        assert ready == [] and held


def test_overlapping_boxes_for_one_piece_are_flagged_without_a_model_call():
    """Three 'black bar stool' boxes really came back each reaching to the right
    edge of the kitchen, so each contained the next - 74 % IoU, three meshes,
    one stool. No call is made to notice this."""
    stools = [_el(room="kitchen", name="black bar stool", sem="bar_stool", box=b, crop=f"s{i}.png")
              for i, b in enumerate([(0.375, 0.58, 0.999, 1.0), (0.537, 0.58, 0.999, 1.0),
                                     (0.739, 0.58, 1.0, 1.0)])]
    for i, el in enumerate(stools):
        el.element_id = f"el_stool{i}"
    reading = SceneReading(elements=stools)
    assert mark_duplicates(reading) == 2
    assert [e.check for e in reading.elements].count("duplicate") == 2
    # the widest box keeps the claim; the narrower ones are the ones that drifted
    assert reading.elements[0].check != "duplicate"


def test_two_real_sofas_are_not_called_duplicates():
    """Guard against the opposite mistake. This render genuinely holds two
    sofas; I called them one piece under two names from the crops alone, and
    was wrong. Boxes that do not overlap are not duplicates."""
    reading = SceneReading(elements=[
        _el(name="striped green sofa", sem="sofa", box=(0.0, 0.148, 0.273, 0.606)),
        _el(name="blue couch", sem="sofa", box=(0.403, 0.238, 1.0, 0.711)),
    ])
    assert mark_duplicates(reading) == 0


# ── the gate in front of spending ─────────────────────────────────────────


def test_nothing_generates_until_a_human_says_yes():
    el = _el()
    reading = SceneReading(elements=[el])
    el.check = "ok"                       # the automatic check is not consent
    ready, held = approved_for_generation(reading)
    assert ready == [] and "not reviewed yet" in held[0]

    el.approved = True
    ready, held = approved_for_generation(reading)
    assert [e.name for e in ready] == ["table lamp"] and held == []

    el.approved = False
    ready, held = approved_for_generation(reading)
    assert ready == [] and "rejected by review" in held[0]


# ── the review API ────────────────────────────────────────────────────────


def _seed_reading(env):
    """A project on disk with one crop, as the scene_plan job leaves it."""
    import json

    from fastapi.testclient import TestClient
    from PIL import Image

    from app.main import app
    from app.projects import get_project_store
    from app.projects.layout import ensure_layout, project_dir

    client = TestClient(app)
    pid = get_project_store().create(name="review", description="2BHK").project_id
    ensure_layout(pid)
    root = project_dir(pid)
    crop = root / "planning/scene_crops/living_room/00_sofa.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (512, 300), (40, 90, 120)).save(crop)
    reading = SceneReading(elements=[
        SceneElement(element_id="el_sofa", room_id="living_room", name="striped sofa",
                     semantic_type="sofa", bbox=(0.1, 0.2, 0.6, 0.8),
                     crop_ref="planning/scene_crops/living_room/00_sofa.png",
                     crop_px=(196, 206), check="ok"),
    ])
    (root / "planning/scene_reading.json").write_text(reading.model_dump_json(indent=2), encoding="utf-8")
    return client, pid


def test_saving_a_decision_still_returns_the_crop_url(env):
    """The PATCH answer has to carry crop_url, exactly like the GET.

    It did not. `crop_url` is derived by the API, and only the GET derived it;
    the PATCH answered with the bare model. Saving one decision therefore
    handed the review screen elements whose crop_url was undefined, and the
    next render died in `fileUrl` with "Cannot read properties of undefined".
    Every test passed, tsc passed, and the page still crashed - which is why
    this one drives the shape the browser actually consumes.
    """
    client, pid = _seed_reading(env)

    got = client.get(f"/api/projects/{pid}/scene-reading").json()["data"]
    url = got["reading"]["elements"][0]["crop_url"]
    assert url.endswith("00_sofa.png") and url.startswith("/files/projects/")
    assert got["summary"]["pending"] == 1

    saved = client.patch(f"/api/projects/{pid}/scene-reading",
                         json={"decisions": {"el_sofa": True}}).json()["data"]
    assert saved["reading"]["elements"][0]["crop_url"] == url, "PATCH dropped crop_url"
    assert saved["summary"]["approved"] == 1
    assert saved["summary"]["ready_to_generate"] == 1


def test_a_decision_for_an_unknown_element_is_refused(env):
    """A decision landing on nothing means the client is looking at a reading
    that has since been re-read. Applying the rest quietly would approve crops
    nobody actually looked at."""
    client, pid = _seed_reading(env)
    r = client.patch(f"/api/projects/{pid}/scene-reading",
                     json={"decisions": {"el_sofa": True, "el_gone": True}})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "UNKNOWN_ELEMENT"
    # ...and nothing was written, so the good half did not sneak through.
    assert client.get(f"/api/projects/{pid}/scene-reading").json()["data"]["summary"]["approved"] == 0


# ── real sizes from the reader ────────────────────────────────────────────


class _Room:
    room_id, name, type = "living_room", "Living Room", "living_room"
    width_m, length_m, height_m = 5.5, 4.5, 2.8


class _Sizer:
    """Stands in for the provider: one canned answer per element."""

    def __init__(self, **by_ref):
        self.by_ref = by_ref

    def estimate_element_dimensions(self, room, elements, vertical):
        return {"items": [dict(ref=r, **v) for r, v in self.by_ref.items()]}


def _reading(*els):
    return SceneReading(elements=list(els))


def _sized_el(eid, sem="sofa", name="sofa"):
    return SceneElement(element_id=eid, room_id="living_room", name=name, semantic_type=sem,
                        bbox=(0.1, 0.2, 0.6, 0.8), crop_ref="c.png", check="ok")


def test_a_sure_and_plausible_size_is_used():
    r = _reading(_sized_el("el_a"))
    warn: list[str] = []
    n = estimate_dimensions(r, {"living_room": _Room()}, "residential",
                            _Sizer(el_a=dict(width_m=2.4, height_m=0.8, depth_m=0.95, sure=True)), warn)
    assert n == 1
    assert r.elements[0].dimensions_m == (2.4, 0.8, 0.95)


def test_an_unsure_answer_is_declined():
    """A generic size is a better outcome than a confident wrong one."""
    r = _reading(_sized_el("el_a"))
    warn: list[str] = []
    n = estimate_dimensions(r, {"living_room": _Room()}, "residential",
                            _Sizer(el_a=dict(width_m=2.4, height_m=0.8, depth_m=0.95, sure=False)), warn)
    assert n == 0 and r.elements[0].dimensions_m is None
    assert "unsure" in warn[0]


def test_an_absurd_size_is_refused_out_loud():
    """Ingest scales by max(expected)/max(mesh), so one wild number does not
    make a piece slightly wrong - it makes the whole mesh wrong, and nothing
    downstream would object."""
    r = _reading(_sized_el("el_a"))
    warn: list[str] = []
    n = estimate_dimensions(r, {"living_room": _Room()}, "residential",
                            _Sizer(el_a=dict(width_m=16.0, height_m=0.85, depth_m=0.9, sure=True)), warn)
    assert n == 0 and r.elements[0].dimensions_m is None
    assert warn and "kept the generic one" in warn[0]


def test_a_thin_piece_is_not_mistaken_for_an_absurd_one():
    """A rug really is a centimetre thick; rejecting it for that was the bug."""
    r = _reading(_sized_el("el_rug", sem="rug", name="woven rug"))
    warn: list[str] = []
    n = estimate_dimensions(r, {"living_room": _Room()}, "residential",
                            _Sizer(el_rug=dict(width_m=1.6, height_m=0.01, depth_m=2.2, sure=True)), warn)
    assert n == 1 and r.elements[0].dimensions_m == (1.6, 0.01, 2.2)


class _Bathroom(_Room):
    room_id, name, type = "living_room", "Bathroom", "bathroom"
    width_m, length_m, height_m = 2.5, 2.0, 2.4


def test_a_piece_that_cannot_fit_the_room_is_refused():
    """3.9 m of sofa is a plausible size on its own and impossible in a 2.5 m
    bathroom. The room is the evidence that catches it."""
    r = _reading(_sized_el("el_a"))
    warn: list[str] = []
    n = estimate_dimensions(r, {"living_room": _Bathroom()}, "residential",
                            _Sizer(el_a=dict(width_m=3.9, height_m=0.8, depth_m=3.8, sure=True)), warn)
    assert n == 0 and warn and "does not fit" in warn[0]


def test_a_provider_without_the_capability_changes_nothing():
    r = _reading(_sized_el("el_a"))
    warn: list[str] = []
    assert estimate_dimensions(r, {"living_room": _Room()}, "residential", object(), warn) == 0
    assert r.elements[0].dimensions_m is None and warn == []
