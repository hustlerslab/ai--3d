/**
 * Types for the Aether walkthrough backend.
 *
 * Hand-written mirror of aether-backend/app/scene/schema.py — the canonical
 * scene schema. Units are meters; +Y up, +X right, -Z forward. Plan geometry
 * (wall lines, room boundaries) lives in the XZ plane.
 */

export type Vec2 = [number, number]; // (x, z)
export type Vec3 = [number, number, number]; // (x, y, z)

export interface Room {
  room_id: string;
  name: string;
  type: string;
  boundary: Vec2[];
  floor_height: number;
  ceiling_height: number;
  floor_material: string;
}

export interface Wall {
  wall_id: string;
  start: Vec2;
  end: Vec2;
  thickness: number;
  height: number;
  material: string;
}

export interface Opening {
  opening_id: string;
  type: "door" | "window";
  wall_id: string;
  /** Meters from wall start to opening center. */
  position: number;
  width: number;
  height: number;
  sill_height: number;
}

export interface SceneObject {
  object_id: string;
  semantic_type: string;
  asset_id: string | null;
  room_id: string;
  position: Vec3;
  rotation_y: number;
  scale: Vec3;
  /** Hybrid pipeline: how the model is sourced and which style material dresses it. */
  source_strategy?: "local_asset" | "local_modified" | "procedural" | "generated";
  material_overrides?: Record<string, string>;
  dimensions: Vec3;
  color: string;
  source: string;
  locked: boolean;
  mount?: Mount;
  /** Surfaces (spec 1.1): the object this one rests on, its open name, shape hint and photo texture. */
  parent_id?: string | null;
  name?: string;
  shape?: string | null;
  texture_ref?: string | null;
}

export interface SavedView {
  view_id: string;
  name: string;
  position: Vec3;
  target: Vec3;
  mode: "orbit" | "first_person";
}

export interface AetherScene {
  /** Moodboard direction compiled into the scene (palette order: wall, floor, upholstery, accent, accent). */
  style?: { name?: string; tags?: string[]; palette?: string[]; materials?: string[]; lighting_mood?: string } | null;
  scene_id: string;
  project_id: string;
  version: number;
  units: string;
  name: string;
  rooms: Room[];
  walls: Wall[];
  openings: Opening[];
  objects: SceneObject[];
  saved_views: SavedView[];
  metadata: Record<string, unknown>;
}

export interface HistoryInfo {
  cursor: number;
  length: number;
  can_undo: boolean;
  can_redo: boolean;
}

export interface TourKeyframe {
  position: Vec3;
  look_at: Vec3;
  /** Seconds spent traveling TO this keyframe. */
  duration: number;
  room_id: string | null;
  label: string;
}

export interface TourPath {
  scene_id: string;
  keyframes: TourKeyframe[];
  total_duration: number;
  room_order: string[];
}

export interface SpawnPoint {
  position: Vec3;
  look_at: Vec3;
}

export interface Violation {
  code: string;
  severity: string;
  message: string;
  object_id: string | null;
  related_id: string | null;
}

export interface ProposalOperation {
  op: "add" | "remove" | "move";
  semantic_type?: string | null;
  object_id?: string | null;
  room_id?: string | null;
}

export interface DesignProposal {
  proposal_id: string;
  scene_id: string;
  base_version: number;
  instruction: string;
  summary: string;
  source: "gemini" | "mock";
  operations: ProposalOperation[];
  warnings: string[];
  status: "preview" | "applied" | "rejected";
  estimated_cost_inr: number;
}

export interface ProposalPreview {
  proposal: DesignProposal;
  candidate_scene: AetherScene;
  added: SceneObject[];
  removed: SceneObject[];
  violations: Violation[];
}

export type Mount = "floor" | "ceiling" | "wall" | "surface";

export interface CatalogItem {
  asset_id: string;
  semantic_type: string;
  name: string;
  dimensions: Vec3;
  color: string;
  style_tags: string[];
  material_tags: string[];
  room_types: string[];
  price_inr: number;
  /** Renderer hint for the parametric fallback; "model" means a real GLB exists. */
  shape: "box" | "seat" | "table" | "tall" | "model";
  mount: Mount;
  /** Path on the engine (e.g. /files/assets/x.glb) — prefix with the base URL. */
  model_url: string | null;
  thumbnail_url: string | null;
  source: "builtin" | "polyhaven" | "upload" | "meshy";
  license: string;
  /** Set when the model was generated for one project from that project's own
   *  material. Renderers leave its textures alone: they are already the
   *  client's fabric, and re-skinning them discards what was generated. */
  project_id?: string;
}

export interface MaterialMaps {
  color: string | null;
  normal: string | null;
  roughness: string | null;
  ao: string | null;
}

export interface MaterialRecord {
  material_id: string;
  name: string;
  category: string;
  base_color: string;
  roughness: number;
  metalness: number;
  /** Paths relative to the engine's /files/ mount. */
  maps: MaterialMaps;
  /** Physical size in meters that one texture repeat covers. */
  tile_size_m: number;
  finish: string;
  style_tags: string[];
  applies_to: string[];
}

export interface AetherHealth {
  status: "ok";
  service: string;
  version: string;
  providers: {
    gemini: { configured: boolean; mode: "live" | "mock"; model: string };
    meshy: { configured: boolean; mode: "live" | "mock" };
  };
  timestamp: string;
}

/** Thrown by every function in the Aether API client. */
export class AetherApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly violations: Violation[];

  constructor(
    code: string,
    message: string,
    status = 0,
    opts: { retryable?: boolean; violations?: Violation[] } = {},
  ) {
    super(message);
    this.name = "AetherApiError";
    this.code = code;
    this.status = status;
    this.retryable = opts.retryable ?? false;
    this.violations = opts.violations ?? [];
  }
}

/** Patch operations accepted by POST /scenes/:id/patches. */
export type PatchOperation =
  | { type: "add_object"; object: SceneObject }
  | { type: "remove_object"; object_id: string }
  | { type: "move_object"; object_id: string; position: Vec3 }
  | { type: "rotate_object"; object_id: string; rotation_y: number }
  | { type: "update_object"; object_id: string; color?: string; locked?: boolean }
  | { type: "replace_asset"; object_id: string; asset_id: string };

export type CameraMode = "orbit" | "first_person" | "tour";
