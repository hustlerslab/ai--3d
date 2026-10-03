/**
 * P1-FRONTEND-004, rendered: what a person reads in the design-versions panel.
 * Rendered to HTML with react-dom/server and asserted on the visible words -
 * and on what must NOT be there: no version id, scene id or content hash.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { DesignVersion } from "@/generated/api-types";

import { VersionList } from "./components/design-versions";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, " ");

function version(over: Partial<DesignVersion>): DesignVersion {
  return {
    version_id: "ver_4f2a9c1e", number: 1, label: "Accepted design", accepted: true,
    scene_id: "scene_77b31d20aa", scene_version: 4,
    content_sha256: "9f2c1e7ab3d04c55e1d8f0a6b9c2d7e4f1a3b5c7d9e0f2a4b6c8d0e2f4a6b8c0",
    created_by: "usr_0a1b2c3d4e5f", created_at: "2026-09-26T10:15:00+00:00", is_current: false, ...over,
  };
}

function render(versions: DesignVersion[], unsavedChanges = false) {
  return renderToStaticMarkup(createElement(VersionList, {
    versions, unsavedChanges, busy: false, onSave: () => undefined, onMakeCurrent: () => undefined,
  }));
}

describe("design versions panel", () => {
  it("shows which version is accepted and which is current", () => {
    const html = render([
      version({ label: "Accepted design", accepted: true, is_current: true }),
      version({ version_id: "ver_b", number: 2, label: "Wider walkway", accepted: false, is_current: false }),
    ]);
    const t = text(html);
    expect(t).toContain("Accepted design");
    expect(t).toContain("Wider walkway");
    expect(t).toContain("Accepted");
    expect(t).toContain("Current");
  });

  it("offers Make current only on versions that are not already current", () => {
    const html = render([
      version({ label: "A", is_current: true }),
      version({ version_id: "ver_b", label: "B", is_current: false, accepted: false }),
    ]);
    expect(html.match(/Make current/g)?.length).toBe(1);
  });

  it("says when the design has changes no saved version holds", () => {
    expect(text(render([version({ is_current: false })], true))).toContain("changes that aren't in any saved version");
    expect(text(render([version({ is_current: true })], false))).not.toContain("saved version yet");
  });

  it("invites saving before an experiment when nothing is saved", () => {
    const t = text(render([]));
    expect(t).toContain("Nothing saved yet");
    expect(t).toContain("Save this design");
    expect(t).toContain("Save and accept");
  });

  it("never puts an internal identifier on the page", () => {
    const v = version({ is_current: true });
    const html = render([v, version({ version_id: "ver_second01", label: "B", accepted: false })]);
    for (const secret of [v.version_id, "ver_second01", v.scene_id, v.content_sha256, v.created_by]) {
      expect(html).not.toContain(secret);
    }
  });
});
