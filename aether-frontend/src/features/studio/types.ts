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

export interface SpottedObject {
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
