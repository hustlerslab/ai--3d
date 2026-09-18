import { describe, expect, it } from "vitest";

import { buildElementImages } from "./element-images";
import type { ElementDefinition, ElementImageDto, ElementImageSetDto, ElementInstance } from "./types";

function def(id: string, type: string, count: number, extra: Partial<ElementDefinition> = {}): ElementDefinition {
  return {
    element_id: id, room_id: "living_room", semantic_type: type, canonical_name: "",
    material: "", color: "", dimensions_m: null, identity_method: "room_type_dims_material_colour",
    instance_count: count, source_element_ids: [], canonical_asset_id: "", ...extra,
  };
}

function img(id: string, extra: Partial<ElementImageDto> = {}): ElementImageDto {
  return {
    element_image_id: `eim_${id}`, element_id: id, canonical_key: "k", image_ref: `planning/element_images/${id}.png`,
    image_url: `/files/projects/p/planning/element_images/${id}.png`, prompt: "p", seed: 7,
    reference_ref: "", reference_url: "", reference_scale: 0, model: "sd", checksum: "c", version: 1, error: "", ...extra,
  };
}

function inst(defId: string, n: number): ElementInstance {
  return { instance_id: `${defId}.${n}`, element_id: defId, room_id: "living_room",
           source_element_id: "k", bbox: null, crop_ref: "" };
}

function dto(definitions: ElementDefinition[], images: ElementImageDto[], instances: ElementInstance[] = []): ElementImageSetDto {
  return { definitions, images, instances, provider: "sd", warnings: [] };
}

describe("element images view", () => {
  it("one card per canonical piece, with its instance count and picture", () => {
    const view = buildElementImages(dto(
      [def("cel_stool", "bar_stool", 3, { canonical_name: "black bar stool" })],
      [img("cel_stool")],
      [inst("cel_stool", 1), inst("cel_stool", 2), inst("cel_stool", 3)],
    ));
    expect(view.canonical_count).toBe(1);
    expect(view.instance_count).toBe(3);
    expect(view.cards[0].instance_count).toBe(3);
    expect(view.cards[0].picture).toBe("painted");
    expect(view.cards[0].label).toBe("black bar stool");
    expect(view.painted).toBe(1);
  });

  it("says when a piece was pictured from the client's own photo", () => {
    const view = buildElementImages(dto([def("a", "sofa", 1)],
      [img("a", { reference_ref: "analysis/crops/00_sofa.png", reference_url: "/files/p/analysis/crops/00_sofa.png" })]));
    expect(view.cards[0].source).toBe("photo");
    const brief = buildElementImages(dto([def("b", "rug", 1)], [img("b")]));
    expect(brief.cards[0].source).toBe("brief");
  });

  it("shows a failed picture as failed with the backend's reason, never hidden", () => {
    const view = buildElementImages(dto([def("a", "lamp", 1)], [img("a", { error: "CUDA out of memory", image_url: "" })]));
    expect(view.cards).toHaveLength(1);
    expect(view.cards[0].picture).toBe("failed");
    expect(view.cards[0].error).toMatch(/CUDA/);
    expect(view.failed).toBe(1);
  });

  it("shows a piece with no picture yet as pending", () => {
    const view = buildElementImages(dto([def("a", "lamp", 1)], []));
    expect(view.cards[0].picture).toBe("pending");
    expect(view.pending).toBe(1);
  });

  it("empty and legacy payloads do not crash", () => {
    expect(buildElementImages(dto([], [])).cards).toEqual([]);
    const legacy = buildElementImages({ definitions: [], images: [], instances: [], provider: "", warnings: [] });
    expect(legacy.canonical_count).toBe(0);
  });
});
