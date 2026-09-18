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

export interface IntentResultDto {
  constraint_id: string;
  subject_id: string;
  target_id: string;
  constraint_type: string;
  verdict: "satisfied" | "violated" | "unknown" | "partial";
  error: number | null;
  error_kind: string;
  message: string;
}

/** planning/spatial_check.json — written by scene_plan after the solver commits. */
export interface SpatialCheckDto {
  schema_version: string;
  repair: {
    terminal_state: string;
    hard_before: number;
    hard_after: number;
    moved: string[];
    escalation_level_reached: number;
  } | null;
  intent: {
    satisfied: number;
    violated: number;
    unknown: number;
    partial: number;
    unsupported_relations: Record<string, number>;
    results: IntentResultDto[];
  };
  consistency: { code: string; severity: string; subject_id: string; object_id: string; message: string }[];
}

/** What one uploaded reference photo was understood to mean. */
export type ReferenceClass =
  | "exact_object"
  | "design_reference"
  | "style_reference"
  | "inspiration_only"
  | "uncertain";

export interface DesignIntentDto {
  intent_id: string;
  reference_class: ReferenceClass;
  object_category: string;
  room_hint: string;
  confidence: number;
  notes: string;
  attributes: {
    color_words: string[];
    color_hex: string;
    material: string;
    upholstery: string;
    pattern: string;
    frame_finish: string;
    style_descriptors: string[];
    visual_descriptors: string[];
  };
  provenance: {
    input_id: string;
    filename: string;
    image_ref: string;
    crop_ref: string;
    stage: string;
    model: string;
  };
}

/** planning/design_intent.json — every reference, classified. */
export interface DesignIntentSetDto {
  schema_version: string;
  reference_ids: string[];
  intents: DesignIntentDto[];
  conflicts: { object_category: string; attribute: string; values: string[]; message: string }[];
  /** References that produced no intent — never silently dropped. */
  unread: string[];
  warnings: string[];
}

/** planning/visual_intent_fidelity.json — did the references survive into the scene? */
export interface VisualIntentFidelityDto {
  schema_version: string;
  metrics: {
    instantiation_fidelity: number | null;
    appearance_fidelity: number | null;
    non_instantiation_compliance: number | null;
    traceability: number | null;
  };
  counts: Record<string, number>;
  rows: {
    intent_id: string;
    reference_class: ReferenceClass;
    object_category: string;
    expected_instantiated: boolean;
    instantiated: boolean;
    rung: string;
    attribute_match: Record<string, boolean>;
    traced_object_ids: string[];
    needs_input: boolean;
    note: string;
  }[];
  resolutions: {
    object_category: string;
    rung: "exact_asset" | "compatible_asset" | "generate" | "unresolved";
    asset_id: string;
    needs_input: boolean;
    reason: string;
    source_intent_ids: string[];
  }[];
  unresolved: string[];
  warnings: string[];
}

export interface SceneSpecDto {
  scene: { scene_id: string; version: number; name: string; rooms: unknown[]; objects: unknown[] };
  violations: { code: string; severity: string; message: string; object_id?: string | null }[];
  asset_plan: { counts: Record<string, number> } | null;
  spatial_check?: SpatialCheckDto | null;
  design_intent?: DesignIntentSetDto | null;
  visual_intent_fidelity?: VisualIntentFidelityDto | null;
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
/** `implausible` is the odd one out: the crop may be a perfectly good picture,
 *  and the objection is that the piece cannot belong to this room — a bath read
 *  into a living room. The others judge the image; this one judges the label. */
export type ElementCheck =
  | "unchecked" | "ok" | "mismatch" | "crowded" | "duplicate" | "unreadable"
  | "implausible";

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
  /** P22: the render's frame — back = the wall you look at. Anchor, not placement. */
  wall?: string;
  /** Room-local metres: x along the back wall, y up, z from the back wall. */
  position_m?: [number, number, number] | null;
  /** "read" (the reader answered) | "derived" (estimated from the crop box). */
  position_source?: string;
  facing?: string;
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
                floor_color: string; floor_material: string; notes: string;
                /** P22: finish zones per named wall; extent_m = [from_x, to_x, from_y, to_y]. */
                walls?: { wall: string; material: string; color: string; pattern: string;
                          extent_m: [number, number, number, number] }[] }[];
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
    /** P17/P18 (aether-backend app/intelligence/schema.py). Optional because
        a backend older than P17 answers without them, and the screen must
        still load that project. The frontend never counts or groups on its
        own: these are the counts. */
    inventory?: ElementInventoryRow[];
    inventory_notes?: string[];
    definitions?: ElementDefinition[];
    instances?: ElementInstance[];
  };
}

/** How many of one kind of piece a room was read to hold. */
export interface ElementInventoryRow {
  room_id: string;
  semantic_type: string;
  read: number;
  usable: number;
  /** check name -> rows it removed, e.g. { duplicate: 2 }. */
  lost_to: Record<string, number>;
}

/** The canonical identity of a piece: what it IS, never where it sits. */
export interface ElementDefinition {
  element_id: string;
  room_id: string;
  semantic_type: string;
  canonical_name: string;
  material: string;
  color: string;
  dimensions_m: [number, number, number] | null;
  /** "room_type_dims_material_colour" | "unresolved" (no evidence, kept apart). */
  identity_method: string;
  instance_count: number;
  /** The reading rows that fold into this piece, biggest crop first. */
  source_element_ids: string[];
  /** Empty until a mesh exists for this piece. */
  canonical_asset_id: string;
  /** The client's decision on the pictured piece: true build, false skip, null/absent undecided. */
  approved?: boolean | null;
}

/** The canonical picture of one piece (aether-backend ElementImage). */
export interface ElementImageDto {
  element_image_id: string;
  element_id: string;
  canonical_key: string;
  image_ref: string;
  /** Minted by the API; empty when generation failed. */
  image_url: string;
  prompt: string;
  seed: number;
  /** Crop of the client's own photo it was conditioned on, if any. */
  reference_ref: string;
  reference_url: string;
  reference_scale: number;
  model: string;
  checksum: string;
  version: number;
  error: string;
}

/** GET /projects/{id}/element-images: the pre-moodboard inventory and its pictures. */
export interface ElementImageSetDto {
  definitions: ElementDefinition[];
  instances: ElementInstance[];
  images: ElementImageDto[];
  provider: string;
  warnings: string[];
}

/** One physical occurrence of a definition. */
export interface ElementInstance {
  instance_id: string;
  element_id: string;
  room_id: string;
  source_element_id: string;
  bbox: [number, number, number, number] | null;
  crop_ref: string;
}

export interface CreditsDto {
  available: boolean;
  /** Present only when available. */
  balance?: number;
  reason?: string;
  credits_per_piece: number;
  max_per_project?: number;
}
