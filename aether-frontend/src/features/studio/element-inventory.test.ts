import { describe, expect, it } from "vitest";

import { buildElementInventory, humanIdentity, humanType } from "./element-inventory";
import type { ElementDefinition, ElementInstance, SceneElement, SceneReadingDto } from "./types";

/**
 * P19. There is no DOM environment in this project (no jsdom, no
 * testing-library), so these test the presenter the review screen renders
 * from - the join of backend definitions, instances and reading rows. Every
 * number asserted here is one the backend sent; the presenter must carry it
 * through unchanged.
 */

function el(id: string, room: string, type: string, check: SceneElement["check"] = "ok",
            approved: boolean | null = null, extra: Partial<SceneElement> = {}): SceneElement {
  return {
    element_id: id, room_id: room, semantic_type: type, name: `${type} ${id}`,
    bbox: [0.1, 0.5, 0.2, 0.8], material: "", color: "", placement: "floor",
    against: "", faces: "", confidence: 0.8,
    crop_ref: `planning/scene_crops/${room}/${id}.png`,
    crop_url: `/files/projects/p/planning/scene_crops/${room}/${id}.png`,
    check, check_note: check === "ok" ? "" : `looked like a ${check}`, approved, ...extra,
  };
}

function def(id: string, room: string, type: string, sources: string[],
             extra: Partial<ElementDefinition> = {}): ElementDefinition {
  return {
    element_id: id, room_id: room, semantic_type: type, canonical_name: "",
    material: "plastic", color: "#111111", dimensions_m: null,
    identity_method: "room_type_dims_material_colour",
    instance_count: sources.length, source_element_ids: sources,
    canonical_asset_id: "", ...extra,
  };
}

function inst(defId: string, n: number, source: string, room: string): ElementInstance {
  return { instance_id: `${defId}.${n}`, element_id: defId, room_id: room,
           source_element_id: source, bbox: [0.1 * n, 0.5, 0.1 * n + 0.1, 0.8],
           crop_ref: `planning/scene_crops/${room}/${source}.png` };
}

function dto(elements: SceneElement[], summary: Partial<SceneReadingDto["summary"]>): SceneReadingDto {
  return {
    reading: { elements, surfaces: [], provider: "mock", warnings: [] },
    summary: {
      with_crops: elements.length, approved: 0, rejected: 0, pending: 0, flagged_by_check: 0,
      ready_to_generate: 0, to_generate: 0, already_generated: 0, credits_needed: 0, ...summary,
    },
  };
}

/** Section 24 of the architecture brief: the three-bar-stool case. */
function threeStools(assetId = "el_p_kitchen_bar_stool") {
  const rows = ["s1", "s2", "s3"].map((id) => el(id, "kitchen", "bar_stool"));
  const d = def("cel_stool", "kitchen", "bar_stool", ["s1", "s2", "s3"],
                { canonical_asset_id: assetId, canonical_name: "black bar stool" });
  const ins = rows.map((r, i) => inst("cel_stool", i + 1, r.element_id, "kitchen"));
  return dto(rows, { definitions: [d], instances: ins });
}

describe("element inventory renders from backend truth", () => {
  it("shows three stools as 3 instances of 1 canonical piece with 1 asset", () => {
    const view = buildElementInventory(threeStools());

    expect(view.canonical_count).toBe(1);
    expect(view.instance_count).toBe(3);
    expect(view.asset_count).toBe(1);
    const [stool] = view.groups;
    expect(stool.instance_count).toBe(3);
    expect(stool.instances).toHaveLength(3);
    expect(stool.asset).toBe("resolved");
    expect(stool.label).toBe("black bar stool");
  });

  it("keeps the three instances distinct - three crops, three ids, three boxes", () => {
    const [stool] = buildElementInventory(threeStools()).groups;
    expect(new Set(stool.instances.map((i) => i.instance_id)).size).toBe(3);
    expect(new Set(stool.instances.map((i) => i.crop_url)).size).toBe(3);
    expect(new Set(stool.instances.map((i) => JSON.stringify(i.bbox))).size).toBe(3);
  });

  it("takes the instance count from the backend, not from counting rows itself", () => {
    // The backend says 5 here; the presenter reports 5. It never recounts.
    const data = threeStools();
    data.summary.definitions![0].instance_count = 5;
    expect(buildElementInventory(data).groups[0].instance_count).toBe(5);
  });

  it("never claims an asset the backend did not confirm", () => {
    const [stool] = buildElementInventory(threeStools("")).groups;
    expect(stool.asset).toBe("unresolved");
    expect(buildElementInventory(threeStools("")).asset_count).toBe(0);
  });
});

describe("canonical elements stay separate", () => {
  it("two definitions are two groups even for the same type", () => {
    const rows = [el("c1", "dining", "dining_chair"), el("c2", "dining", "dining_chair")];
    const data = dto(rows, {
      definitions: [def("cel_a", "dining", "dining_chair", ["c1"], { material: "linen" }),
                    def("cel_b", "dining", "dining_chair", ["c2"], { material: "velvet" })],
      instances: [inst("cel_a", 1, "c1", "dining"), inst("cel_b", 1, "c2", "dining")],
    });
    const view = buildElementInventory(data);
    expect(view.canonical_count).toBe(2);
    expect(view.groups.map((g) => g.instances.length)).toEqual([1, 1]);
  });

  it("does not group by type on its own when the backend sent no grouping", () => {
    const rows = [el("c1", "dining", "dining_chair"), el("c2", "dining", "dining_chair")];
    const view = buildElementInventory(dto(rows, { definitions: [], instances: [] }));
    expect(view.groups).toEqual([]);
  });
});

describe("rejected and unresolved states", () => {
  it("shows a row the checks removed as rejected, with the backend's reason", () => {
    const island = el("k1", "kitchen", "kitchen_island", "mismatch");
    const data = dto([...threeStools().reading.elements, island], threeStools().summary);
    const view = buildElementInventory(data);

    expect(view.rejected).toHaveLength(1);
    expect(view.rejected[0].element.element_id).toBe("k1");
    expect(view.rejected[0].reason).toBe("mismatch");
    expect(view.rejected[0].note).toBe("looked like a mismatch");
    expect(view.detected_rows).toBe(4);
  });

  it("shows a human rejection as unapproved, not as a check", () => {
    const rug = el("r1", "living_room", "rug", "ok", false);
    const view = buildElementInventory(dto([rug], { definitions: [], instances: [] }));
    expect(view.rejected[0].reason).toBe("unapproved");
  });

  it("shows a piece the backend kept apart for lack of evidence as unresolved", () => {
    const rows = [el("n1", "living_room", "side_table")];
    const data = dto(rows, {
      definitions: [def("cel_n", "living_room", "side_table", ["n1"],
                        { identity_method: "unresolved", material: "", color: "" })],
      instances: [inst("cel_n", 1, "n1", "living_room")],
    });
    const [g] = buildElementInventory(data).groups;
    expect(g.state).toBe("unresolved");
    expect(humanIdentity(g.identity)).toMatch(/Kept separate/);
  });

  it("explains a merge in plain words from the backend's identity method", () => {
    const [stool] = buildElementInventory(threeStools()).groups;
    expect(humanIdentity(stool.identity)).toMatch(/Same room and type/);
  });
});

describe("compatibility", () => {
  it("an empty inventory does not crash", () => {
    const view = buildElementInventory(dto([], { definitions: [], instances: [] }));
    expect(view.groups).toEqual([]);
    expect(view.rejected).toEqual([]);
    expect(view.canonical_count).toBe(0);
  });

  it("a legacy payload without inventory fields does not crash and says so", () => {
    const rows = [el("s1", "kitchen", "bar_stool")];
    const view = buildElementInventory(dto(rows, {}));
    expect(view.unavailable).toBe(true);
    expect(view.groups).toEqual([]);
    // and it must NOT report the rows as rejected just because nothing claimed them
    expect(view.rejected).toEqual([]);
  });

  it("an instance whose reading row is missing still renders without a crop", () => {
    const data = threeStools();
    data.reading.elements = data.reading.elements.slice(0, 2);
    const [stool] = buildElementInventory(data).groups;
    expect(stool.instances).toHaveLength(3);
    expect(stool.instances[2].element).toBeNull();
    expect(stool.instances[2].crop_url).toBe("");
  });

  it("humanises a semantic type without changing its identity", () => {
    expect(humanType("bar_stool")).toBe("Bar Stool");
    expect(humanType("kitchen_island")).toBe("Kitchen Island");
  });
});
