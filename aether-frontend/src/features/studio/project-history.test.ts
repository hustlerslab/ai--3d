import { describe, expect, it } from "vitest";

import { stageLabel } from "./stages";
import type { ProjectStage } from "./types";

/**
 * Every stage the backend can put a project in. Mirrors ProjectStage in
 * ./types, which mirrors ProjectStage in aether-backend app/projects/schema.py.
 */
const ALL_STAGES: ProjectStage[] = [
  "CREATED",
  "INPUT_RECEIVED",
  "ANALYZING",
  "DESIGN_SPEC_READY",
  "ASSET_PLANNING",
  "ASSETS_READY",
  "SCENE_BUILDING",
  "SCENE_VALIDATING",
  "CAMERA_PLANNING",
  "PREVIEW_RENDERING",
  "FINAL_RENDERING",
  "COMPLETED",
  "FAILED",
];

describe("stageLabel", () => {
  it("gives every stage a human label", () => {
    for (const stage of ALL_STAGES) {
      const label = stageLabel(stage);
      expect(label, `${stage} has no label`).toBeTruthy();
      expect(label, `${stage} leaks the raw enum into the UI`).not.toBe(stage);
    }
  });

  it("never leaves SCREAMING_SNAKE_CASE on screen", () => {
    for (const stage of ALL_STAGES) {
      expect(stageLabel(stage)).not.toMatch(/^[A-Z_]+$/);
    }
  });

  it("falls back to the raw value rather than rendering nothing", () => {
    // A stage added to the backend before the frontend catches up should show
    // something, not an empty pill.
    expect(stageLabel("SOMETHING_NEW" as ProjectStage)).toBe("SOMETHING_NEW");
  });
});
