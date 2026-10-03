/**
 * P2-VIEWER-001: the viewer never re-lays-out, a selected piece says what it
 * is in five plain answers, and a machine without WebGL gets a clear message.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ProvenanceChain } from "@/generated/api-types";

import compiled from "./__fixtures__/compiled-scene.json";
import { IdentityPanel, keptOrNew, materialOf, nameOf, originOf } from "./components/identity-panel";
import { objectTransform } from "./components/scene-meshes";
import type { SceneObject } from "./types/scene";
import { canRender3D } from "./utils/webgl";

const objects = (compiled as unknown as { objects: SceneObject[] }).objects;
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, " ");

describe("the viewer never re-lays-out", () => {
  it("draws every piece of a real compiled scene exactly where the scene puts it", () => {
    // A real scene from the compiler (tests.test_blender_build._compiled_scene):
    // 40 pieces - floor, on-surface and wall-mounted.
    expect(objects.length).toBe(40);
    for (const o of objects) {
      const t = objectTransform(o);
      expect(t.position, o.semantic_type).toEqual([o.position[0], o.position[1], o.position[2]]);
      expect(t.rotation).toEqual([0, o.rotation_y, 0]);
      expect(t.scale).toEqual([o.scale[0], o.scale[1], o.scale[2]]);
    }
  });

  it("leaves floor-standing curtains on the floor, where Blender renders them", () => {
    const curtains = objects.filter((o) => o.semantic_type === "curtains");
    expect(curtains.length).toBeGreaterThan(0);
    for (const c of curtains) {
      expect(c.mount).toBe("wall");
      expect(objectTransform(c).position[1]).toBe(c.position[1]);   // was lifted 0.15 m
    }
  });
});

const sofa: SceneObject = {
  ...(objects.find((o) => o.semantic_type === "sofa") ?? objects[0]),
  name: "grey linen sofa",
  visual: { material: "linen" },
  material_overrides: { primary: "fabric_linen" },
  client_owned: false,
  source_strategy: "generated",
};

const fromPhoto = {
  project_id: "proj_4f2a9c1e", scene_object_id: "obj_77b31d20aa", origin: "moodboard_element", complete: true,
  gaps: [], terminus: "source_image", hops: [{ kind: "element", id: "el_123456" }],
  source_images: [{ input_id: "in_9abcdef0", filename: "living.jpg", url: "/files/projects/proj_4f2a9c1e/input/references/living.jpg" }],
} as unknown as ProvenanceChain;

describe("a selected piece says what it is", () => {
  it("answers all five: name, size, material, kept or new, origin", () => {
    const t = text(renderToStaticMarkup(createElement(IdentityPanel, { obj: sofa, chain: fromPhoto })));
    for (const [label, value] of [["Name", "Grey linen sofa"], ["Material", "Linen"],
                                  ["Kept or new", "New - made for this design"], ["Origin", "From your photo"]]) {
      expect(t).toContain(label);
      expect(t).toContain(value);
    }
    expect(t).toMatch(/Size \d+\.\d{2} × \d+\.\d{2} × \d+\.\d{2} m/);
  });

  it("shows the photo the piece came from", () => {
    const html = renderToStaticMarkup(createElement(IdentityPanel, { obj: sofa, chain: fromPhoto }));
    expect(html).toContain('alt="Your photo living.jpg"');
  });

  it("puts no internal identifier in the visible text", () => {
    const t = text(renderToStaticMarkup(createElement(IdentityPanel, { obj: sofa, chain: fromPhoto })));
    for (const id of ["proj_4f2a9c1e", "obj_77b31d20aa", "el_123456", "in_9abcdef0", sofa.object_id]) {
      expect(t).not.toContain(id);
    }
  });

  it("tells every kind of origin honestly", () => {
    expect(originOf({ ...fromPhoto, source_images: [], terminus: "moodboard" }).text).toBe("From the moodboard you approved");
    expect(originOf({ ...fromPhoto, source_images: [], terminus: "scene_object", origin: "planner_catalog" }).text)
      .toBe("Chosen by the planner - not from one of your photos");
    expect(originOf({ ...fromPhoto, source_images: [], terminus: "", origin: "unknown" }).text)
      .toBe("Where this came from couldn't be traced");
    expect(originOf(null).text).toContain("Looking up");
  });

  it("says kept or new from the backend's own fields", () => {
    expect(keptOrNew({ ...sofa, client_owned: true })).toBe("Yours - kept, not built");
    expect(keptOrNew({ ...sofa, source_strategy: "local_asset" })).toBe("New - from the catalogue");
    expect(keptOrNew({ ...sofa, source_strategy: "procedural" })).toBe("New - a simple stand-in shape");
  });

  it("prefers the client's own material word, then the assigned one", () => {
    expect(materialOf(sofa)).toBe("Linen");
    expect(materialOf({ ...sofa, visual: {} })).toBe("Fabric linen");
    expect(materialOf({ ...sofa, visual: {}, material_overrides: {} })).toBe("Not specified");
    expect(nameOf({ ...sofa, name: "" })).toBe("Sofa");
  });
});

describe("a machine without WebGL is told why", () => {
  const doc = (ctx: unknown, throws = false) => ({
    createElement: () => ({ getContext: () => { if (throws) throw new Error("no"); return ctx; } }),
  }) as unknown as Pick<Document, "createElement">;

  it("detects WebGL, its absence, and a failing probe", () => {
    expect(canRender3D(doc({}))).toBe(true);
    expect(canRender3D(doc(null))).toBe(false);
    expect(canRender3D(doc(null, true))).toBe(false);
  });
});
