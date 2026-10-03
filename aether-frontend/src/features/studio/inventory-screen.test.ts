/**
 * P1-FRONTEND-001, rendered: the element inventory as a person reads it.
 * react-dom/server, asserted on visible words and on what must not appear.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AssumptionsPanel, ElementInventory } from "./components/element-review";
import type { ElementDefinition, ElementInstance, SceneElement, SceneReadingDto } from "./types";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, " ");

function el(id: string, type: string, extra: Partial<SceneElement> = {}): SceneElement {
  return {
    element_id: id, room_id: "living_room", semantic_type: type, name: type, bbox: [0.1, 0.5, 0.2, 0.8],
    material: "oak", color: "#aa7744", placement: "floor", against: "", faces: "", confidence: 0.8,
    crop_ref: `planning/c/${id}.png`, crop_url: `/files/projects/p/planning/c/${id}.png`, check: "ok",
    check_note: "", approved: null, ...extra,
  };
}

function def(id: string, type: string, sources: string[], extra: Partial<ElementDefinition> = {}): ElementDefinition {
  return {
    element_id: id, room_id: "living_room", semantic_type: type, canonical_name: "", material: "oak",
    color: "#aa7744", dimensions_m: null, identity_method: "room_type_dims_material_colour",
    instance_count: sources.length, source_element_ids: sources, canonical_asset_id: "", ...extra,
  };
}

const inst = (d: string, n: number, src: string): ElementInstance => ({
  instance_id: `${d}.${n}`, element_id: d, room_id: "living_room", source_element_id: src,
  bbox: [0.1, 0.5, 0.2, 0.8], crop_ref: "",
});

function data(): SceneReadingDto {
  const elements = [el("e_sofa", "sofa"), el("e_chair", "armchair"), el("e_lamp", "floor_lamp"),
                    el("e_side", "side_table"), el("e_rug", "rug", { approved: false })];
  return {
    reading: { elements, surfaces: [], provider: "mock", warnings: [] },
    summary: {
      with_crops: 5, approved: 1, rejected: 1, pending: 3, flagged_by_check: 0, ready_to_generate: 1,
      to_generate: 1, already_generated: 0, credits_needed: 30,
      definitions: [def("d_sofa", "sofa", ["e_sofa"], { client_owned: true }),
                    def("d_chair", "armchair", ["e_chair"]),
                    def("d_lamp", "floor_lamp", ["e_lamp"]),
                    def("d_side", "side_table", ["e_side"], { identity_method: "unresolved" })],
      instances: [inst("d_sofa", 1, "e_sofa"), inst("d_chair", 1, "e_chair"),
                  inst("d_lamp", 1, "e_lamp"), inst("d_side", 1, "e_side")],
      element_states: { e_sofa: "validated", e_chair: "detected", e_lamp: "detected",
                        e_side: "unresolved", e_rug: "rejected" },
      counts: { detected_rows: 5, canonical: 4, instances: 4, assets: 0, yours: 1,
                by_state: { validated: 1, detected: 2, unresolved: 1, rejected: 1 } },
      assumptions: [
        { kind: "room_size", ref: "living_room", statement: "Living room: 4.2 × 5.0 m is an estimate.", change: "Enter the real size of this room." },
        { kind: "position", ref: "e_lamp", statement: "Where the floor lamp stands was estimated from the picture.", change: "Move it in the 3D view." },
      ],
    },
  };
}

const render = () => renderToStaticMarkup(createElement(ElementInventory, { data: data() }));

describe("element inventory, rendered", () => {
  it("shows each of the four states in plain words", () => {
    const t = text(render());
    for (const label of ["Confirmed", "Awaiting you", "Identity unresolved", "Not used"]) {
      expect(t).toContain(label);
    }
  });

  it("prints the backend's counts", () => {
    const t = text(render());
    expect(t).toContain("5 detected");
    expect(t).toContain("4 pieces");
    expect(t).toContain("1 yours");
  });

  it("marks the estimated position on the piece it belongs to", () => {
    expect(text(render()).match(/est\. position/g)?.length).toBe(1);
  });

  it("lists every assumption with where to change it", () => {
    const t = text(render());
    expect(t).toContain("What we assumed");
    expect(t).toContain("Living room: 4.2 × 5.0 m is an estimate.");
    expect(t).toContain("Enter the real size of this room.");
    expect(t).toContain("Move it in the 3D view.");
  });

  it("labels kept furniture as yours", () => {
    expect(text(render())).toContain("Yours");
    expect(text(render())).toContain("kept, not built");
  });

  it("says why a piece was not used in words, not a check code", () => {
    const t = text(render());
    expect(t).toContain("you left it out");
  });

  it("puts no internal identifier on the page", () => {
    const html = render();
    for (const id of ["d_sofa", "d_chair", "d_side.1", "d_lamp.1", "e_lamp", "e_rug"]) {
      expect(html).not.toContain(`"${id}"`);
      expect(text(html)).not.toContain(id);
    }
  });

  it("an empty assumptions list renders nothing", () => {
    expect(renderToStaticMarkup(createElement(AssumptionsPanel, { assumptions: [] }))).toBe("");
  });
});
