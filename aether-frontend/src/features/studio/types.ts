/** DTOs mirrored from aether-backend app/projects, app/jobs, app/intelligence. */

export type ProjectStage =
  | "CREATED"
  | "INPUT_RECEIVED"
  | "ANALYZING"
  | "DESIGN_SPEC_READY"
  | "ASSET_PLANNING"
  | "ASSETS_READY"
  | "SCENE_BUILDING"
  | "SCENE_VALIDATING"
  | "CAMERA_PLANNING"
  | "PREVIEW_RENDERING"
  | "FINAL_RENDERING"
  | "COMPLETED"
  | "FAILED";

/** The market a project is designed for (aether-backend app/projects/schema.py Vertical). */
export type Vertical = "residential" | "hospitality" | "industrial";

export interface RoomHint {
  name: string;
  type: string;
  width_m?: number | null;
  length_m?: number | null;
  height_m?: number | null;
  estimated?: boolean;
}

export interface ProjectRecord {
  project_id: string;
  name: string;
  description: string;
  stage: ProjectStage;
  scene_ids: string[];
  room_hints: RoomHint[];
  vertical: Vertical;
  created_at: string;
  updated_at: string;
}

export interface InputRecord {
  input_id: string;
  kind: "description" | "reference" | "dimensions" | "floor_plan";
  filename: string;
  path: string;
  content_type: string;
  size_bytes: number;
  meta: { url?: string; rooms?: number };
}

export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "RETRYING" | "CANCELLED";

export interface JobDto {
  job_id: string;
  project_id: string;
  type: string;
  lane: "ai" | "render";
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  checkpoint: string;
  error: string;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: string;
  started_at: string;
  finished_at: string;
}

export interface EventDto {
  event_id: number;
  project_id: string;
  job_id: string;
  stage: string;
  status: string;
  message: string;
  duration_ms: number;
  ts: string;
}

export interface OutputDto {
  output_id: string;
  kind: string;
  path: string;
  url: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface ProjectDetail {
  project: ProjectRecord;
  inputs: InputRecord[];
  jobs: JobDto[];
  checkpoints: Record<string, boolean>;
  outputs: OutputDto[];
}

export interface RoomAnalysis {
  room_id: string;
  name: string;
  type: string;
  width_m: number;
  length_m: number;
  height_m: number;
  estimated: boolean;
  notes: string;
}

/** What a read item is for. "place" becomes geometry; "reference" shapes the
 *  palette and materials without furnishing the room — uploads are often shop
 *  photos, and four mattresses from a showroom are not four beds. */
export type ItemRole = "place" | "reference";

export interface SpottedObject {
  /** Stable, content-derived. Address items by this, never by list position. */
  object_id: string;
  role: ItemRole;
  semantic_type: string;
  /** Open reading (schema 1.1): free name, coarse family, where it sits and the photo crop. */
  name?: string;
  family?: string;
  placement?: "floor" | "wall" | "ceiling" | "on_surface";
  support?: string;
  material?: string;
  color?: string;
  crop_ref?: string;
  room_id: string | null;
  count: number;
  confidence: number;
  notes: string;
}

export interface DesignAnalysis {
  version: number;
  intent: string;
  rooms: RoomAnalysis[];
  constraints: string[];
  spotted_objects: SpottedObject[];
  keywords: string[];
  confidence: number;
  provider: string;
  warnings: string[];
}

export interface StyleSpec {
  version: number;
  name: string;
  tags: string[];
  palette: string[];
  materials: string[];
  lighting_mood: "warm_daylight" | "cool_daylight" | "evening" | "studio";
  description: string;
  confidence: number;
  provider: string;
  warnings: string[];
}

/** One room's moodboard image. `url` empty means it could not be painted. */
export interface RoomScene {
  room_id: string;
  name: string;
  type: string;
  url: string;
  error: string;
  /** False means the render never saw a photo of this room's own pieces — the
   *  normal case for rooms the client photographed nothing of. */
  reference_resolved: boolean;
  reference_note: string;
  /** The noise seed this image was drawn from. Regenerating draws a different
   *  one, so the button is a new attempt rather than the same dice re-rolled. */
  seed?: number;
  recipe_version?: string;
}

export interface MoodboardSpec {
  title: string;
  style_name: string;
  style_tags: string[];
  palette: string[];
  material_ids: string[];
  lighting_mood: string;
  /** The raw files the user uploaded. Provenance only — never rendered on the
   *  moodboard, or the board is just the upload step played back. */
  reference_urls: string[];
  /** Cutouts of the pieces the reading identified. Data only: deliberately NOT
   *  rendered on the moodboard — that was tried and rejected for the same
   *  reason as reference_urls. The board shows scene_url or nothing. */
  piece_urls?: string[];
  /** The room Gemini painted from the references and the brief. Empty when
   *  image generation is unavailable — see scene_error for why. */
  scene_url?: string;
  /** Why there is no scene image, in words the user can act on. */
  scene_error?: string;
  /** One image per room. `scene_url` above is the first of these, kept as the
   *  hero so older screens keep working. */
  room_scenes?: RoomScene[];
  /** Was the scene actually conditioned on one of the user's photos? False with
   *  a scene_url present means a generic room was rendered — it must be shown,
   *  because it looks identical to a good result. */
  reference_resolved?: boolean;
  /** Which photo it used, or why it used none. */
  reference_note?: string;
  keywords: string[];
  rooms: string[];
}

export interface AnalysisDto {
  analysis: DesignAnalysis;
  style: StyleSpec | null;
  moodboard: MoodboardSpec | null;
  versions: { kind: string; version: number }[];
  provider: { mode: "live" | "mock"; name: string; fallback_to_mock: boolean };
}

export interface AnalysisPatch {
  intent?: string;
  constraints?: string[];
  rooms?: Partial<RoomAnalysis>[];
  remove_rooms?: string[];
  style?: Partial<Pick<StyleSpec, "name" | "tags" | "palette" | "materials" | "lighting_mood" | "description">>;
  /** { object_id: role } — which read items the client actually owns. */
  item_roles?: Record<string, ItemRole>;
}

export interface SceneSpecDto {
  scene: { scene_id: string; version: number; name: string; rooms: unknown[]; objects: unknown[] };
  violations: { code: string; severity: string; message: string }[];
  asset_plan: { counts: Record<string, number> } | null;
}

export interface BuildDto {
  report: { ok: boolean; errors: string[]; warnings: string[]; counts: Record<string, number> } | null;
  files: { blend: string | null; preview: string | null; manifest: string | null };
}

export class ProjectsApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ProjectsApiError";
  }
}

/** Verdict of the isolated second look at one crop. `unchecked` and
 *  `unreadable` both mean nobody has established what the crop shows — they
 *  are not passes, and the review screen treats them as needing eyes. */
export type ElementCheck =
  | "unchecked" | "ok" | "mismatch" | "crowded" | "duplicate" | "unreadable";

export interface SceneElement {
  element_id: string;
  room_id: string;
  name: string;
  semantic_type: string;
  bbox: [number, number, number, number] | null;
  material: string;
  color: string;
  placement: string;
  against: string;
  faces: string;
  confidence: number;
  crop_ref: string;
  crop_url: string;
  check: ElementCheck;
  check_note: string;
  /** null until a human has actually looked. Not the same as false. */
  approved: boolean | null;
}

export interface SceneReadingDto {
  reading: {
    elements: SceneElement[];
    surfaces: { room_id: string; wall_color: string; wall_material: string;
                floor_color: string; floor_material: string; notes: string }[];
    provider: string;
    warnings: string[];
  };
  summary: {
    with_crops: number;
    approved: number;
    rejected: number;
    pending: number;
    flagged_by_check: number;
    ready_to_generate: number;
    /** What pressing Generate would do right now. */
    to_generate: number;
    already_generated: number;
    credits_needed: number;
  };
}

export interface CreditsDto {
  available: boolean;
  /** Present only when available. */
  balance?: number;
  reason?: string;
  credits_per_piece: number;
  max_per_project?: number;
}
