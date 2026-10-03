/**
 * P1-ELEM-004 and P1-SPATIAL-002, rendered: what a person actually reads on
 * the review screen and the trade-off notice. Rendered to HTML with
 * react-dom/server (no DOM library needed) and asserted on the visible words.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ElementReview } from "./components/element-review";
import { TradeoffList } from "./components/tradeoff-notice";
import type { SceneElement, SceneReadingDto, TradeoffDto } from "./types";

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

function element(over: Partial<SceneElement>): SceneElement {
  return {
    element_id: "el_1", room_id: "living_room", name: "grey sofa", semantic_type: "sofa",
    bbox: [0.1, 0.4, 0.4, 0.7], material: "linen", color: "#888888", placement: "floor",
    against: "", faces: "", confidence: 0.8, crop_ref: "planning/element_crops/a.png",
    crop_url: "/files/a.png", check: "ok", check_note: "", approved: null, ...over,
  };
}

function reading(elements: SceneElement[]): SceneReadingDto {
  return {
    reading: { elements, surfaces: [], provider: "mock", warnings: [] },
    summary: {
      with_crops: elements.length, approved: 0, flagged_by_check: 0, to_generate: 0,
      already_generated: 0, credits_needed: 0,
    },
  } as unknown as SceneReadingDto;
}

const review = (els: SceneElement[]) =>
  text(renderToStaticMarkup(createElement(ElementReview, { data: reading(els), onSave: async () => {} })));

describe("keep this furniture (P1-ELEM-004)", () => {
  it("offers every piece a structured 'keep it' control", () => {
    const html = review([element({})]);
    expect(html).toContain("Mine — keep it");
    expect(html).not.toContain("Yours —");
  });

  it("labels a kept piece 'Yours' and says it is not built", () => {
    const html = review([element({ client_owned: true, approved: true }), element({ element_id: "el_2", name: "oak table" })]);
    expect(html).toContain("Yours");
    expect(html).toContain("Yours — kept, not built");
    expect(html).toContain("1 yours, kept");
    // a kept piece is not counted as something to build
    expect(html).toContain("0 to build");
  });
});

describe("spatial trade-offs in plain language (P1-SPATIAL-002)", () => {
  const t: TradeoffDto = {
    kind: "doesnt_fit", room: "Living Room", pieces: ["grey sofa", "velvet armchair"],
    statement: "The grey sofa and the velvet armchair don't fit in the living room alongside everything else while keeping a clear walkway and space in front of the doors.",
    options: [{ id: "leave_out", label: "Leave the grey sofa out of the living room" },
              { id: "smaller", label: "Use a smaller grey sofa that fits" }],
  };

  it("states the conflict and lists at least two things the person can do", () => {
    const html = text(renderToStaticMarkup(createElement(TradeoffList, { tradeoffs: [t] })));
    expect(html).toContain(t.statement);
    expect(html).toContain("What you can do");
    for (const o of t.options) expect(html).toContain(o.label);
    expect(html).not.toMatch(/leave_out|smaller\b.*id|obj_|priority/);
  });

  it("renders nothing when everything fitted", () => {
    expect(renderToStaticMarkup(createElement(TradeoffList, { tradeoffs: [] }))).toBe("");
  });
});
