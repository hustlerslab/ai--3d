/**
 * Pipeline stage → what a person would call it.
 *
 * Kept out of the component (and free of `@/` imports) so it is testable
 * without a DOM or an alias config, the same way verticals.ts is.
 * Mirrors ProjectStage in aether-backend app/projects/schema.py.
 */

import type { ProjectStage } from "./types";

const STAGE_LABEL: Record<ProjectStage, string> = {
  CREATED: "Not started",
  INPUT_RECEIVED: "Photos added",
  ANALYZING: "Reading photos",
  DESIGN_SPEC_READY: "Moodboard ready",
  ASSET_PLANNING: "Planning",
  ASSETS_READY: "Plan ready",
  SCENE_BUILDING: "Building",
  SCENE_VALIDATING: "Validating",
  CAMERA_PLANNING: "Camera plan",
  PREVIEW_RENDERING: "Preview ready",
  FINAL_RENDERING: "Rendering",
  COMPLETED: "Complete",
  FAILED: "Failed",
};

/** Falls back to the raw value so a stage the backend adds first still shows
 *  something rather than an empty pill. */
export const stageLabel = (stage: ProjectStage): string => STAGE_LABEL[stage] ?? stage;
