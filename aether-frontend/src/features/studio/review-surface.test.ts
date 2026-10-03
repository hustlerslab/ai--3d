/**
 * P1-FRONTEND-002, rendered and exercised: the review surface.
 * - every section task.md lists is on the page;
 * - Approve / Edit / Regenerate / Reject are all reachable;
 * - a DOM scan: no raw error, code, enum or internal id in the visible text;
 * - Reject SAVES a version and never deletes anything.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewView } from "@/generated/api-types";

import { ReviewPanel, recordDecision } from "./components/review-surface";
import type { SceneReadingDto } from "./types";

const text = (html: string) =>
  html.replace(/<[^>]+>/g, " ").replace(/&#x27;|&#39;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ");

function view(over: Partial<ReviewView> = {}): ReviewView {
  return {
    status: "needs_attention",
    status_text: "2 things to look at before you approve.",
    render: { url: "/files/projects/proj_4f2a9c1e/previews/build_preview.png" },
    checks: [
      { label: "Every piece was built", outcome: "passed" },
      { label: "The picture shows the current design", outcome: "failed" },
      { label: "Materials and colours match the design", outcome: "not_checked" },
    ],
    issues: [{ text: "1 pieces changed after the render was taken.", next: "You can accept it as it is." }],
    repair: { attempt: 1, of: 2, text: "Correcting the layout — 1 of 2" },
    can_decide: true,
    ...over,
  };
}

const reading: SceneReadingDto = {
  reading: { elements: [], surfaces: [], provider: "mock", warnings: [] },
  summary: {
    with_crops: 0, approved: 0, rejected: 0, pending: 0, flagged_by_check: 0, ready_to_generate: 0,
    to_generate: 0, already_generated: 0, credits_needed: 0, definitions: [], instances: [],
    element_states: {}, counts: { detected_rows: 0, canonical: 0, instances: 0, assets: 0, yours: 0, by_state: {} },
    assumptions: [{ kind: "room_size", ref: "living_room", statement: "Living room: 4.2 × 5.0 m is an estimate.",
                    change: "Enter the real size of this room." }],
  },
};

function render(v: ReviewView = view(), notice: string | null = null) {
  return renderToStaticMarkup(createElement(ReviewPanel, {
    view: v, reading, scene: createElement("div", { "data-testid": "scene" }, "3D"), busy: false, notice,
    onDecide: () => undefined,
  }));
}

describe("review surface, rendered", () => {
  it("presents the render, the 3D scene, the inventory with its assumptions, the checks and the issues", () => {
    const html = render();
    const t = text(html);
    expect(html).toContain('alt="The rendered room"');
    expect(html).toContain('data-testid="scene"');
    expect(t).toContain("Element inventory");
    expect(t).toContain("What we assumed");
    expect(t).toContain("What was checked");
    expect(t).toContain("Things to look at");
    expect(t).toContain("2 things to look at before you approve.");
  });

  it("shows the repair as an attempt out of two", () => {
    expect(text(render())).toContain("Correcting the layout — 1 of 2");
  });

  it("makes all four decisions reachable", () => {
    const t = text(render());
    for (const action of ["Approve", "Edit", "Regenerate", "Reject"]) expect(t).toContain(action);
  });

  it("turns check outcomes into words, never the raw value", () => {
    const t = text(render());
    expect(t).toContain("Checked");
    expect(t).toContain("Needs a look");
    expect(t).toContain("Not checked yet");
  });

  it("puts no raw error, code, enum or internal id in the visible text", () => {
    for (const status of ["verified", "needs_attention", "not_verified", "not_ready"] as const) {
      const t = text(render(view({ status })));
      for (const bad of [
        /\b(obj|scene|proj|ver|rev|usr|job)_[0-9a-z]{4,}/,         // internal ids
        /\b[A-Z]{2,}(?:_[A-Z]+)+\b/,                              // HUMAN_REVIEW, VALIDATION_FAILURE
        /\b[a-z]+(?:_[a-z]+)+\b/,                                 // needs_attention, not_checked
        /\b(FAIL|PASS|Error|undefined|null|NaN)\b/,
      ]) {
        expect(t, `${status}: ${bad}`).not.toMatch(bad);
      }
    }
  });

  it("disables the decisions when there is no design to decide on", () => {
    const html = render(view({ status: "not_ready", can_decide: false, render: null, checks: [], issues: [], repair: null }));
    expect(html.match(/disabled=""/g)?.length).toBe(4);
  });
});

describe("Reject does not delete work", () => {
  afterEach(() => vi.unstubAllGlobals());

  function recordRequests() {
    const sent: { method: string; path: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({ method: (init?.method ?? "GET").toUpperCase(), path: new URL(url).pathname,
                  body: init?.body ? JSON.parse(String(init.body)) : null });
      return new Response(JSON.stringify({ success: true, data: { version: { number: 3 } } }), { status: 200 });
    }));
    return sent;
  }

  it("rejecting saves the design as a version and deletes nothing", async () => {
    const sent = recordRequests();
    const notice = await recordDecision("p1", "reject");
    expect(sent).toEqual([{ method: "POST", path: "/api/projects/p1/versions",
                            body: { accept: false, label: "Rejected design" } }]);
    expect(sent.some((s) => s.method === "DELETE")).toBe(false);
    expect(notice).toContain("kept as saved version 3");
    expect(notice).toContain("Nothing was deleted");
  });

  it("approving saves the design as the accepted version", async () => {
    const sent = recordRequests();
    await recordDecision("p1", "approve");
    expect(sent).toEqual([{ method: "POST", path: "/api/projects/p1/versions",
                            body: { accept: true, label: "Approved design" } }]);
  });
});
