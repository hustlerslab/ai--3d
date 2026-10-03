// GENERATED from the backend's OpenAPI document by aether-backend/scripts/gen_api_types.py.
// Do not edit by hand: change the response model in app/api/contracts.py and re-run
//   python scripts/gen_api_types.py
// CI fails if this file differs from what the backend would generate.

export interface AddObjectOp {
  type?: "add_object";
  object: SceneObject;
}

export interface Analysis {
  analysis: Record<string, unknown>;
  style?: Record<string, unknown> | null;
  moodboard?: Record<string, unknown> | null;
  versions: Record<string, unknown>[];
  provider: Record<string, unknown>;
  [key: string]: unknown;
}

export interface AnalysisPatchBody {
  intent?: string | null;
  constraints?: string[] | null;
  rooms?: RoomPatch[] | null;
  remove_rooms?: string[];
  style?: StylePatch | null;
  item_roles?: Record<string, string>;
}

export interface AnalysisWritten {
  success: true;
  analysis: Record<string, unknown>;
  style?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface AnalyzeBody {
  force?: boolean;
  paint?: boolean;
}

export interface AssetFiles {
  original?: string;
  normalized?: string;
  web?: string;
}

export interface AssetRecord {
  asset_id?: string;
  name: string;
  semantic_type: string;
  status?: "normalized" | "failed";
  source?: AssetSource;
  format?: string;
  files?: AssetFiles;
  dimensions?: [number, number, number];
  polycount?: number;
  file_size?: number;
  textures?: Record<string, number>;
  normalization?: NormalizationInfo;
  validation?: ValidationIssue[];
  mount?: "floor" | "ceiling" | "wall" | "surface";
  style_tags?: string[];
  material_tags?: string[];
  room_types?: string[];
  price_inr?: number;
  color?: string;
  created_at?: string;
  project_id?: string;
  canonical_element_id?: string;
  source_image_id?: string;
}

export interface AssetSource {
  provider?: "polyhaven" | "upload" | "meshy" | "local";
  source_id?: string;
  url?: string;
  license?: string;
  license_url?: string;
  creator?: string;
  thumbnail_url?: string;
}

export interface AssetWritten {
  success: true;
  asset: AssetRecord;
  [key: string]: unknown;
}

export interface AssetsUpgraded {
  success: true;
  scene: Scene;
  version: number;
  history: Record<string, unknown>;
  replaced: Record<string, unknown>[];
  skipped: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface Assumption {
  kind: "room_size" | "position" | "identity";
  ref: string;
  statement: string;
  change: string;
  [key: string]: unknown;
}

export interface AuthMe {
  user: UserOut;
  [key: string]: unknown;
}

export interface AuthRegistered {
  user: UserOut;
  token: string;
  expires_in_days: number;
  bootstrapped: boolean;
  claimed: number;
  [key: string]: unknown;
}

export interface AuthSession {
  authenticated: boolean;
  user?: UserOut | null;
  [key: string]: unknown;
}

export interface AuthSignedIn {
  user: UserOut;
  token: string;
  expires_in_days: number;
  [key: string]: unknown;
}

export interface AuthSignedOut {
  ended: boolean;
  [key: string]: unknown;
}

export interface AuthSignedOutEverywhere {
  revoked: number;
  [key: string]: unknown;
}

export interface Body_add_inputs_api_projects__project_id__inputs_post {
  description?: string | null;
  dimensions?: string | null;
  references?: string[];
}

export interface Body_upload_asset_api_assets_upload_post {
  file: string;
  name: string;
  semantic_type: string;
  asset_id?: string | null;
  expected_width?: number | null;
  expected_height?: number | null;
  expected_depth?: number | null;
  yaw_offset?: number | null;
  mount?: string;
  style_tags?: string;
  room_types?: string;
  price_inr?: number;
  color?: string;
  license?: string;
  creator?: string;
}

export interface BuildBody {
  force?: boolean;
  preview?: boolean;
  preview_profile?: string;
}

export interface BuildView {
  report: Record<string, unknown>;
  manifest_summary: Record<string, unknown>;
  files: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Calibration {
  meters_per_unit?: number;
  source?: string;
  confidence?: number;
}

export interface CameraKeyframe {
  position: [number, number, number];
  look_at: [number, number, number];
  duration?: number;
  room_id?: string | null;
  label?: string;
}

export interface CameraPlan {
  type?: "walkthrough" | "orbit" | "stills";
  duration_seconds?: number;
  seconds_per_room?: number;
  keyframes?: CameraKeyframe[];
  hero_shots?: SavedView[];
}

export interface CatalogItem {
  asset_id: string;
  semantic_type: string;
  name: string;
  dimensions: [number, number, number];
  color: string;
  style_tags?: string[];
  material_tags?: string[];
  room_types?: string[];
  price_inr?: number;
  shape?: string;
  mount?: string;
  model_url?: string | null;
  thumbnail_url?: string | null;
  source?: string;
  license?: string;
  project_id?: string;
}

export interface CheckPositionBody {
  x: number;
  z: number;
}

export interface Confidence {
  value?: number;
  source?: string;
}

export interface CreateProjectBody {
  name: string;
  description?: string;
  room_hints?: RoomHint[];
  vertical?: Vertical;
}

export interface CreateSceneBody {
  project_id: string;
  name?: string;
  from_seed?: boolean;
}

export interface Credits {
  available: boolean;
  reason?: string | null;
  balance?: unknown | null;
  credits_per_piece?: number | null;
  [key: string]: unknown;
}

export interface DesignVersion {
  version_id: string;
  number: number;
  label: string;
  accepted: boolean;
  scene_id: string;
  scene_version: number;
  content_sha256: string;
  created_by: string;
  created_at: string;
  is_current?: boolean;
}

export interface DesignVersionDetail {
  version: DesignVersion;
  snapshot: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DesignVersionRestored {
  version: DesignVersion;
  scene_version: number;
  [key: string]: unknown;
}

export interface DesignVersionSaved {
  version: DesignVersion;
  [key: string]: unknown;
}

export interface DesignVersions {
  versions: DesignVersion[];
  unsaved_changes: boolean;
  [key: string]: unknown;
}

export interface ElementDecisionsBody {
  decisions: Record<string, boolean>;
}

export interface ElementImages {
  schema_version: string;
  version: number;
  definitions: Record<string, unknown>[];
  instances: Record<string, unknown>[];
  images: Record<string, unknown>[];
  provider: string;
  warnings: string[];
  created_at: string;
  [key: string]: unknown;
}

export interface ElementImagesBody {
  force?: boolean;
}

export interface ElementReviewBody {
  decisions?: Record<string, boolean>;
  keep?: Record<string, boolean>;
}

export interface ElementsGenerateAccepted {
  success: true;
  job: Job;
  summary: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EnqueueJobBody {
  type: string;
  params?: Record<string, unknown>;
}

export interface Envelope_Analysis_ {
  success: true;
  data: Analysis;
  [key: string]: unknown;
}

export interface Envelope_AssetRecord_ {
  success: true;
  data: AssetRecord;
  [key: string]: unknown;
}

export interface Envelope_AuthMe_ {
  success: true;
  data: AuthMe;
  [key: string]: unknown;
}

export interface Envelope_AuthRegistered_ {
  success: true;
  data: AuthRegistered;
  [key: string]: unknown;
}

export interface Envelope_AuthSession_ {
  success: true;
  data: AuthSession;
  [key: string]: unknown;
}

export interface Envelope_AuthSignedIn_ {
  success: true;
  data: AuthSignedIn;
  [key: string]: unknown;
}

export interface Envelope_AuthSignedOutEverywhere_ {
  success: true;
  data: AuthSignedOutEverywhere;
  [key: string]: unknown;
}

export interface Envelope_AuthSignedOut_ {
  success: true;
  data: AuthSignedOut;
  [key: string]: unknown;
}

export interface Envelope_BuildView_ {
  success: true;
  data: BuildView;
  [key: string]: unknown;
}

export interface Envelope_CatalogItem_ {
  success: true;
  data: CatalogItem;
  [key: string]: unknown;
}

export interface Envelope_Credits_ {
  success: true;
  data: Credits;
  [key: string]: unknown;
}

export interface Envelope_DesignVersionDetail_ {
  success: true;
  data: DesignVersionDetail;
  [key: string]: unknown;
}

export interface Envelope_DesignVersionRestored_ {
  success: true;
  data: DesignVersionRestored;
  [key: string]: unknown;
}

export interface Envelope_DesignVersionSaved_ {
  success: true;
  data: DesignVersionSaved;
  [key: string]: unknown;
}

export interface Envelope_DesignVersions_ {
  success: true;
  data: DesignVersions;
  [key: string]: unknown;
}

export interface Envelope_ElementImages_ {
  success: true;
  data: ElementImages;
  [key: string]: unknown;
}

export interface Envelope_EventPage_ {
  success: true;
  data: EventPage;
  [key: string]: unknown;
}

export interface Envelope_InputDeleted_ {
  success: true;
  data: InputDeleted;
  [key: string]: unknown;
}

export interface Envelope_JobDetail_ {
  success: true;
  data: JobDetail;
  [key: string]: unknown;
}

export interface Envelope_MaterialRecord_ {
  success: true;
  data: MaterialRecord;
  [key: string]: unknown;
}

export interface Envelope_Outputs_ {
  success: true;
  data: Outputs;
  [key: string]: unknown;
}

export interface Envelope_PositionCheck_ {
  success: true;
  data: PositionCheck;
  [key: string]: unknown;
}

export interface Envelope_ProjectDeleted_ {
  success: true;
  data: ProjectDeleted;
  [key: string]: unknown;
}

export interface Envelope_ProjectDetail_ {
  success: true;
  data: ProjectDetail;
  [key: string]: unknown;
}

export interface Envelope_ProvenanceChain_ {
  success: true;
  data: ProvenanceChain;
  [key: string]: unknown;
}

export interface Envelope_ProvenanceCoverage_ {
  success: true;
  data: ProvenanceCoverage;
  [key: string]: unknown;
}

export interface Envelope_RepairRounds_ {
  success: true;
  data: RepairRounds;
  [key: string]: unknown;
}

export interface Envelope_ReviewDecided_ {
  success: true;
  data: ReviewDecided;
  [key: string]: unknown;
}

export interface Envelope_ReviewItems_ {
  success: true;
  data: ReviewItems;
  [key: string]: unknown;
}

export interface Envelope_ReviewView_ {
  success: true;
  data: ReviewView;
  [key: string]: unknown;
}

export interface Envelope_SceneReadingView_ {
  success: true;
  data: SceneReadingView;
  [key: string]: unknown;
}

export interface Envelope_SceneSpec_ {
  success: true;
  data: SceneSpec;
  [key: string]: unknown;
}

export interface Envelope_SceneValidation_ {
  success: true;
  data: SceneValidation;
  [key: string]: unknown;
}

export interface Envelope_SceneWithHistory_ {
  success: true;
  data: SceneWithHistory;
  [key: string]: unknown;
}

export interface Envelope_ShareLinkCreated_ {
  success: true;
  data: ShareLinkCreated;
  [key: string]: unknown;
}

export interface Envelope_ShareLinkRevoked_ {
  success: true;
  data: ShareLinkRevoked;
  [key: string]: unknown;
}

export interface Envelope_ShareLinks_ {
  success: true;
  data: ShareLinks;
  [key: string]: unknown;
}

export interface Envelope_Spawn_ {
  success: true;
  data: Spawn;
  [key: string]: unknown;
}

export interface Envelope_TourPackage_ {
  success: true;
  data: TourPackage;
  [key: string]: unknown;
}

export interface Envelope_TourPath_ {
  success: true;
  data: TourPath;
  [key: string]: unknown;
}

export interface Envelope_Tradeoffs_ {
  success: true;
  data: Tradeoffs;
  [key: string]: unknown;
}

export interface Envelope_list_AssetRecord__ {
  success: true;
  data: AssetRecord[];
  [key: string]: unknown;
}

export interface Envelope_list_CatalogItem__ {
  success: true;
  data: CatalogItem[];
  [key: string]: unknown;
}

export interface Envelope_list_InputRecord__ {
  success: true;
  data: InputRecord[];
  [key: string]: unknown;
}

export interface Envelope_list_JobType__ {
  success: true;
  data: JobType[];
  [key: string]: unknown;
}

export interface Envelope_list_Job__ {
  success: true;
  data: Job[];
  [key: string]: unknown;
}

export interface Envelope_list_MaterialRecord__ {
  success: true;
  data: MaterialRecord[];
  [key: string]: unknown;
}

export interface Envelope_list_ProjectRecord__ {
  success: true;
  data: ProjectRecord[];
  [key: string]: unknown;
}

export interface Envelope_list_SavedView__ {
  success: true;
  data: SavedView[];
  [key: string]: unknown;
}

export interface Envelope_list_SceneSummary__ {
  success: true;
  data: SceneSummary[];
  [key: string]: unknown;
}

export interface EventPage {
  events: JobEvent[];
  last_id: number;
  [key: string]: unknown;
}

export interface FilmBody {
  force?: boolean;
  profile?: string;
}

export interface GenerateElementsBody {
  limit?: number | null;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface Health {
  status: string;
  service: string;
  version: string;
  runtime: Record<string, unknown>;
  providers: Record<string, unknown>;
  timestamp: string;
  [key: string]: unknown;
}

export interface Hop {
  hop: string;
  resolved?: boolean;
  gap?: boolean;
  id?: string;
  note?: string;
  detail?: Record<string, unknown>;
}

export interface InputDeleted {
  input_id: string;
  kind: string;
  file_removed: boolean;
  [key: string]: unknown;
}

export type InputKind = "description" | "reference" | "dimensions" | "floor_plan";

export interface InputRecord {
  input_id?: string;
  project_id: string;
  kind: InputKind;
  filename: string;
  path: string;
  content_type?: string;
  size_bytes?: number;
  meta?: Record<string, unknown>;
  created_at: string;
}

export interface InputsAdded {
  success: true;
  project: ProjectRecord;
  inputs: InputRecord[];
  rejected: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface InteriorLight {
  light_id?: string;
  room_id: string;
  type?: "area" | "point" | "spot";
  position: [number, number, number];
  power_w?: number;
  color_temp_k?: number;
  size_m?: number;
}

export interface InventoryCounts {
  detected_rows: number;
  canonical: number;
  instances: number;
  assets: number;
  yours: number;
  by_state: Record<string, number>;
  [key: string]: unknown;
}

export interface Job {
  job_id?: string;
  project_id: string;
  type: string;
  lane: JobLane;
  status?: JobStatus;
  attempt?: number;
  max_attempts?: number;
  checkpoint?: string;
  error?: string;
  params?: Record<string, unknown>;
  result?: Record<string, unknown>;
  log_path?: string;
  created_by?: string;
  correlation_id?: string;
  repair_round?: number;
  created_at: string;
  started_at?: string;
  finished_at?: string;
}

export interface JobAccepted {
  success: true;
  job: Job;
  [key: string]: unknown;
}

export interface JobDetail {
  job: Job;
  events: JobEvent[];
  [key: string]: unknown;
}

export interface JobEvent {
  event_id: number;
  project_id: string;
  job_id?: string;
  stage: string;
  status: string;
  message?: string;
  duration_ms?: number;
  ts: string;
  schema_version?: string;
  event_type?: string;
  severity?: string;
  confidence?: number | null;
  correlation_id?: string;
  parent_event_id?: number | null;
  producer?: string;
  entity_ids?: string[];
  evidence_refs?: string[];
  payload?: Record<string, unknown>;
}

export type JobLane = "ai" | "render";

export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "RETRYING" | "CANCELLED";

export interface JobType {
  type: string;
  lane: string;
  max_attempts: number;
  stage_running?: string | null;
  stage_done?: string | null;
  description: string;
  [key: string]: unknown;
}

export interface LightingSpec {
  mood?: "warm_daylight" | "cool_daylight" | "evening" | "studio";
  sun_azimuth_deg?: number;
  sun_elevation_deg?: number;
  sun_strength?: number;
  sky_turbidity?: number;
  exposure_ev?: number;
  interior_lights?: InteriorLight[];
}

export interface LoginBody {
  email: string;
  password: string;
}

export interface Material {
  material_id?: string;
  name: string;
  base_color?: string;
  roughness?: number;
  metalness?: number;
  style_tags?: string[];
}

export interface MaterialMaps {
  color?: string | null;
  normal?: string | null;
  roughness?: string | null;
  ao?: string | null;
}

export interface MaterialRecord {
  material_id: string;
  name: string;
  category: "wood" | "marble" | "stone" | "metal" | "fabric" | "glass" | "paint" | "tile" | "leather" | "plaster";
  base_color?: string;
  roughness?: number;
  metalness?: number;
  maps?: MaterialMaps;
  tile_size_m?: number;
  finish?: string;
  style_tags?: string[];
  applies_to?: ("floor" | "wall" | "furniture" | "ceiling")[];
  source?: AssetSource;
}

export interface MaterialWritten {
  success: true;
  material: MaterialRecord;
  [key: string]: unknown;
}

export interface MoveObjectOp {
  type?: "move_object";
  object_id: string;
  position: [number, number, number];
}

export interface NormalizationInfo {
  version?: string;
  detected_unit?: "meter" | "centimeter" | "millimeter" | "unknown";
  unit_scale?: number;
  yaw_offset?: number;
  yaw_source?: "unmeasured" | "declared" | "measured";
  translation?: [number, number, number];
  source_size?: [number, number, number];
  strategy?: string;
}

export type ObjectSource = "catalog" | "generated" | "user" | "seed";

export interface ObjectVisual {
  color_words?: string[];
  material?: string;
  upholstery?: string;
  pattern?: string;
  frame_finish?: string;
  descriptors?: string[];
  source_intent_ids?: string[];
}

export interface Opening {
  opening_id?: string;
  type: OpeningType;
  wall_id: string;
  position: number;
  width: number;
  height: number;
  sill_height?: number;
}

export type OpeningType = "door" | "window";

export interface Outputs {
  outputs: Record<string, unknown>[];
  checkpoints: Record<string, boolean>;
  [key: string]: unknown;
}

export interface PatchBody {
  base_version: number;
  operations: (AddObjectOp | RemoveObjectOp | MoveObjectOp | RotateObjectOp | ScaleObjectOp | UpdateObjectOp | ReplaceAssetOp | RenameRoomOp | SetRoomMaterialOp)[];
  source?: string;
}

export interface PatchPreview {
  success: true;
  valid: boolean;
  violations: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface PolyhavenIngestBody {
  source_id: string;
  name: string;
  semantic_type: string;
  asset_id?: string | null;
  resolution?: string;
  expected_dimensions?: [number, number, number] | null;
  yaw_offset?: number | null;
  mount?: string;
  style_tags?: string[];
  material_tags?: string[];
  room_types?: string[];
  price_inr?: number;
  color?: string;
}

export interface PolyhavenMaterialBody {
  source_id: string;
  material_id: string;
  name?: string | null;
  category?: string | null;
  resolution?: string;
  tile_size_m?: number | null;
  base_color?: string | null;
  roughness?: number | null;
  style_tags?: string[] | null;
  applies_to?: string[] | null;
}

export interface PositionCheck {
  valid: boolean;
  reason?: string | null;
  room_id?: string | null;
  corrected?: [number, number, number] | null;
}

export interface PreviewBody {
  force?: boolean;
  profile?: string;
}

export interface ProjectDeleted {
  deleted: string;
  kept: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ProjectDetail {
  project: ProjectRecord;
  inputs: InputRecord[];
  jobs: Job[];
  checkpoints: Record<string, boolean>;
  outputs: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface ProjectRecord {
  project_id?: string;
  name: string;
  description?: string;
  stage?: ProjectStage;
  scene_ids?: string[];
  correlation_id?: string;
  room_hints?: RoomHint[];
  vertical?: Vertical;
  created_at: string;
  updated_at: string;
}

export type ProjectStage = "CREATED" | "INPUT_RECEIVED" | "ANALYZING" | "DESIGN_SPEC_READY" | "ASSET_PLANNING" | "ASSETS_READY" | "SCENE_BUILDING" | "SCENE_VALIDATING" | "CAMERA_PLANNING" | "PREVIEW_RENDERING" | "FINAL_RENDERING" | "COMPLETED" | "FAILED" | "REPAIRING" | "HUMAN_REVIEW" | "VERIFIED" | "CANCELLED";

export interface ProjectWritten {
  success: true;
  project: ProjectRecord;
  [key: string]: unknown;
}

export interface ProposalBody {
  instruction: string;
}

export interface ProposalCreated {
  success: true;
  proposal: Record<string, unknown>;
  candidate_scene: Record<string, unknown>;
  added: unknown[];
  removed: unknown[];
  violations: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface ProposalRejected {
  success: true;
  proposal_id: string;
  status: string;
  [key: string]: unknown;
}

export interface ProvenanceChain {
  project_id: string;
  scene_object_id: string;
  origin?: string;
  complete?: boolean;
  gaps?: string[];
  terminus?: string;
  hops?: Hop[];
  source_images?: Record<string, unknown>[];
}

export interface ProvenanceCoverage {
  objects: number;
  origins: Record<string, unknown>;
  terminus: Record<string, unknown>;
  traced_to_element: number;
  traced_to_scene_element: number;
  reached_moodboard: number;
  reached_source_image_exact: number;
  reached_source_image_via_moodboard: number;
  complete: number;
  gaps: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ReadingSummary {
  element_states: Record<string, "detected" | "validated" | "rejected" | "unresolved">;
  counts: InventoryCounts;
  assumptions: Assumption[];
  [key: string]: unknown;
}

export interface RegisterBody {
  email: string;
  password: string;
  role?: string;
}

export interface RemoveObjectOp {
  type?: "remove_object";
  object_id: string;
}

export interface RenameRoomOp {
  type?: "rename_room";
  room_id: string;
  name: string;
}

export interface RenormalizeBody {
  expected_dimensions?: [number, number, number] | null;
  yaw_offset?: number | null;
}

export interface RepairRounds {
  rounds: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface ReplaceAssetOp {
  type?: "replace_asset";
  object_id: string;
  asset_id: string;
}

export interface ReviewCheck {
  label: string;
  outcome: "passed" | "failed" | "not_checked";
  [key: string]: unknown;
}

export interface ReviewDecided {
  decision: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ReviewIssue {
  text: string;
  next: string;
  [key: string]: unknown;
}

export interface ReviewItems {
  items: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface ReviewRender {
  url: string;
  [key: string]: unknown;
}

export interface ReviewRepair {
  attempt: number;
  of: number;
  text: string;
  [key: string]: unknown;
}

export interface ReviewView {
  status: "not_ready" | "not_verified" | "needs_attention" | "verified";
  status_text: string;
  render?: ReviewRender | null;
  checks: ReviewCheck[];
  issues: ReviewIssue[];
  repair?: ReviewRepair | null;
  can_decide: boolean;
  [key: string]: unknown;
}

export interface Room {
  room_id?: string;
  name: string;
  type?: string;
  boundary: [number, number][];
  floor_height?: number;
  ceiling_height?: number;
  floor_material?: string;
  confidence?: Confidence;
  features?: string[];
}

export interface RoomHint {
  name: string;
  type?: string;
  width_m?: number | null;
  length_m?: number | null;
  height_m?: number | null;
  estimated?: boolean;
}

export interface RoomPatch {
  room_id: string;
  name?: string | null;
  type?: string | null;
  width_m?: number | null;
  length_m?: number | null;
  height_m?: number | null;
  estimated?: boolean | null;
  notes?: string | null;
}

export interface RotateObjectOp {
  type?: "rotate_object";
  object_id: string;
  rotation_y: number;
}

export interface SaveVersionBody {
  label?: string;
  accept?: boolean;
}

export interface SavedView {
  view_id?: string;
  name: string;
  position: [number, number, number];
  target: [number, number, number];
  mode?: "orbit" | "first_person";
}

export interface SavedViewBody {
  name: string;
  position: [number, number, number];
  target: [number, number, number];
  mode?: string;
}

export interface ScaleObjectOp {
  type?: "scale_object";
  object_id: string;
  scale: [number, number, number];
}

export interface Scene {
  scene_id?: string;
  project_id: string;
  version?: number;
  units?: "meter";
  coordinate_system?: Record<string, string>;
  name?: string;
  rooms?: Room[];
  walls?: Wall[];
  openings?: Opening[];
  objects?: SceneObject[];
  materials?: Material[];
  saved_views?: SavedView[];
  calibration?: Calibration;
  metadata?: Record<string, unknown>;
  spec_version?: string;
  style?: SceneStyle | null;
  lighting?: LightingSpec | null;
  camera_plan?: CameraPlan | null;
}

export interface SceneCommitted {
  success: true;
  scene: Scene;
  version: number;
  history: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SceneCreated {
  success: true;
  scene: Scene;
  [key: string]: unknown;
}

export interface SceneObject {
  object_id?: string;
  semantic_type: string;
  asset_id?: string | null;
  room_id: string;
  position: [number, number, number];
  rotation_y?: number;
  scale?: [number, number, number];
  dimensions: [number, number, number];
  color?: string;
  source?: ObjectSource;
  locked?: boolean;
  mount?: string;
  confidence?: Confidence;
  source_strategy?: "local_asset" | "local_modified" | "procedural" | "generated";
  material_overrides?: Record<string, string>;
  plan_key?: string | null;
  element_id?: string | null;
  instance_id?: string | null;
  client_owned?: boolean;
  identity_source?: string;
  parent_id?: string | null;
  texture_ref?: string | null;
  shape?: string | null;
  name?: string;
  visual?: ObjectVisual;
}

export interface ScenePlanBody {
  force?: boolean;
  force_read?: boolean;
}

export interface SceneReadingView {
  reading: Record<string, unknown>;
  summary: ReadingSummary;
  [key: string]: unknown;
}

export interface SceneReverted {
  success: true;
  scene: Scene;
  history: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SceneSpec {
  scene: Record<string, unknown>;
  history: Record<string, unknown>;
  violations: Record<string, unknown>[];
  object_plan?: Record<string, unknown> | null;
  asset_plan?: Record<string, unknown> | null;
  spatial_check?: Record<string, unknown> | null;
  design_intent?: Record<string, unknown> | null;
  visual_intent_fidelity?: Record<string, unknown> | null;
  scene_specs: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface SceneStyle {
  name?: string;
  tags?: string[];
  palette?: string[];
  materials?: string[];
  lighting_mood?: "warm_daylight" | "cool_daylight" | "evening" | "studio";
}

export interface SceneSummary {
  scene_id: string;
  name: string;
  project_id?: string | null;
  version: number;
  rooms: number;
  objects: number;
  [key: string]: unknown;
}

export interface SceneValidation {
  valid: boolean;
  violations: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface SceneWithHistory {
  scene: Scene;
  history: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ServiceRoot {
  service: string;
  docs: string;
  api: string;
  [key: string]: unknown;
}

export interface SetRoomMaterialOp {
  type?: "set_room_material";
  room_id: string;
  floor_material: string;
}

export interface ShareLinkBody {
  label?: string;
  expires_in_days?: number | null;
}

export interface ShareLinkCreated {
  token_id: string;
  url: string;
  token: string;
  label: string;
  expires_in_days?: number | null;
  note: string;
  [key: string]: unknown;
}

export interface ShareLinkRevoked {
  revoked: boolean;
  [key: string]: unknown;
}

export interface ShareLinks {
  links: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface Spawn {
  position: number[];
  look_at: number[];
  [key: string]: unknown;
}

export interface StylePatch {
  name?: string | null;
  tags?: string[] | null;
  palette?: string[] | null;
  materials?: string[] | null;
  lighting_mood?: string | null;
  description?: string | null;
}

export interface TourKeyframe {
  position: [number, number, number];
  look_at: [number, number, number];
  duration: number;
  room_id?: string | null;
  label?: string;
}

export interface TourPackage {
  schema_version?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  scene_id?: string | null;
  scene_version?: number | null;
  quality?: string | null;
  modes?: string[] | null;
  explore?: Record<string, unknown> | null;
  style?: Record<string, unknown> | null;
  rooms?: Record<string, unknown>[] | null;
  tour?: Record<string, unknown> | null;
  nodes?: Record<string, unknown>[] | null;
  generated_at?: string | null;
  [key: string]: unknown;
}

export interface TourPath {
  scene_id: string;
  keyframes: TourKeyframe[];
  total_duration: number;
  room_order: string[];
}

export interface Tradeoffs {
  tradeoffs: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface UpdateObjectOp {
  type?: "update_object";
  object_id: string;
  color?: string | null;
  locked?: boolean | null;
  semantic_type?: string | null;
}

export interface UpdateProjectBody {
  name?: string | null;
  description?: string | null;
  room_hints?: RoomHint[] | null;
  vertical?: Vertical | null;
}

export interface UserOut {
  user_id: string;
  email: string;
  role: string;
  [key: string]: unknown;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface ValidationIssue {
  code: string;
  severity: "hard" | "warn" | "info";
  message: string;
}

export type Vertical = "residential" | "hospitality" | "industrial";

export interface ViewSaved {
  success: true;
  view: SavedView;
  [key: string]: unknown;
}

export interface WalkthroughBody {
  force?: boolean;
  profile?: string;
  hero_stills?: number;
}

export interface Wall {
  wall_id?: string;
  start: [number, number];
  end: [number, number];
  thickness?: number;
  height?: number;
  material?: string;
  extrusion_direction?: [number, number, number];
  finishes?: WallFinishZone[];
}

export interface WallFinishZone {
  room_id: string;
  wall_name: string;
  material: string;
  material_text?: string;
  color?: string;
  pattern?: string;
  extent?: [number, number, number, number];
}

/** Every route the backend serves. The frontend contract test calls each
 * API function against a mocked fetch and fails if its method + path is
 * not in this list - the class of bug where a PATCH silently became a POST. */
export const API_ENDPOINTS = [
  { method: "GET", path: "/", response: "ServiceRoot" },
  { method: "GET", path: "/api/assets", response: "Envelope_list_AssetRecord__" },
  { method: "POST", path: "/api/assets/ingest/polyhaven", response: "AssetWritten" },
  { method: "POST", path: "/api/assets/upload", response: "AssetWritten" },
  { method: "GET", path: "/api/assets/{asset_id}", response: "Envelope_AssetRecord_" },
  { method: "POST", path: "/api/assets/{asset_id}/renormalize", response: "AssetWritten" },
  { method: "POST", path: "/api/auth/login", response: "Envelope_AuthSignedIn_" },
  { method: "POST", path: "/api/auth/logout", response: "Envelope_AuthSignedOut_" },
  { method: "POST", path: "/api/auth/logout-everywhere", response: "Envelope_AuthSignedOutEverywhere_" },
  { method: "GET", path: "/api/auth/me", response: "Envelope_AuthMe_" },
  { method: "POST", path: "/api/auth/register", response: "Envelope_AuthRegistered_" },
  { method: "GET", path: "/api/auth/session", response: "Envelope_AuthSession_" },
  { method: "GET", path: "/api/catalog", response: "Envelope_list_CatalogItem__" },
  { method: "GET", path: "/api/catalog/{asset_id}", response: "Envelope_CatalogItem_" },
  { method: "GET", path: "/api/credits", response: "Envelope_Credits_" },
  { method: "GET", path: "/api/health", response: "Health" },
  { method: "GET", path: "/api/jobs/types", response: "Envelope_list_JobType__" },
  { method: "GET", path: "/api/jobs/{job_id}", response: "Envelope_JobDetail_" },
  { method: "GET", path: "/api/materials", response: "Envelope_list_MaterialRecord__" },
  { method: "POST", path: "/api/materials/ingest/polyhaven", response: "MaterialWritten" },
  { method: "GET", path: "/api/materials/{material_id}", response: "Envelope_MaterialRecord_" },
  { method: "GET", path: "/api/projects", response: "Envelope_list_ProjectRecord__" },
  { method: "POST", path: "/api/projects", response: "ProjectWritten" },
  { method: "DELETE", path: "/api/projects/{project_id}", response: "Envelope_ProjectDeleted_" },
  { method: "GET", path: "/api/projects/{project_id}", response: "Envelope_ProjectDetail_" },
  { method: "PATCH", path: "/api/projects/{project_id}", response: "ProjectWritten" },
  { method: "GET", path: "/api/projects/{project_id}/analysis", response: "Envelope_Analysis_" },
  { method: "PATCH", path: "/api/projects/{project_id}/analysis", response: "AnalysisWritten" },
  { method: "POST", path: "/api/projects/{project_id}/analyze", response: "JobAccepted" },
  { method: "POST", path: "/api/projects/{project_id}/assets/resolve", response: "JobAccepted" },
  { method: "GET", path: "/api/projects/{project_id}/build", response: "Envelope_BuildView_" },
  { method: "POST", path: "/api/projects/{project_id}/build", response: "JobAccepted" },
  { method: "GET", path: "/api/projects/{project_id}/element-images", response: "Envelope_ElementImages_" },
  { method: "PATCH", path: "/api/projects/{project_id}/element-images", response: "Envelope_ElementImages_" },
  { method: "POST", path: "/api/projects/{project_id}/element-images", response: "JobAccepted" },
  { method: "POST", path: "/api/projects/{project_id}/elements/generate", response: "ElementsGenerateAccepted" },
  { method: "GET", path: "/api/projects/{project_id}/events", response: "Envelope_EventPage_" },
  { method: "POST", path: "/api/projects/{project_id}/film", response: "JobAccepted" },
  { method: "GET", path: "/api/projects/{project_id}/inputs", response: "Envelope_list_InputRecord__" },
  { method: "POST", path: "/api/projects/{project_id}/inputs", response: "InputsAdded" },
  { method: "DELETE", path: "/api/projects/{project_id}/inputs/{input_id}", response: "Envelope_InputDeleted_" },
  { method: "GET", path: "/api/projects/{project_id}/jobs", response: "Envelope_list_Job__" },
  { method: "POST", path: "/api/projects/{project_id}/jobs", response: "JobAccepted" },
  { method: "POST", path: "/api/projects/{project_id}/moodboard/rooms/{room_id}/repaint", response: "JobAccepted" },
  { method: "GET", path: "/api/projects/{project_id}/outputs", response: "Envelope_Outputs_" },
  { method: "POST", path: "/api/projects/{project_id}/preview", response: "JobAccepted" },
  { method: "GET", path: "/api/projects/{project_id}/provenance", response: "Envelope_ProvenanceCoverage_" },
  { method: "GET", path: "/api/projects/{project_id}/provenance/{scene_object_id}", response: "Envelope_ProvenanceChain_" },
  { method: "GET", path: "/api/projects/{project_id}/repairs", response: "Envelope_RepairRounds_" },
  { method: "GET", path: "/api/projects/{project_id}/review", response: "Envelope_ReviewView_" },
  { method: "GET", path: "/api/projects/{project_id}/reviews", response: "Envelope_ReviewItems_" },
  { method: "POST", path: "/api/projects/{project_id}/reviews/{item_id}/decision", response: "Envelope_ReviewDecided_" },
  { method: "POST", path: "/api/projects/{project_id}/scene-plan", response: "JobAccepted" },
  { method: "GET", path: "/api/projects/{project_id}/scene-reading", response: "Envelope_SceneReadingView_" },
  { method: "PATCH", path: "/api/projects/{project_id}/scene-reading", response: "Envelope_SceneReadingView_" },
  { method: "GET", path: "/api/projects/{project_id}/scene-spec", response: "Envelope_SceneSpec_" },
  { method: "GET", path: "/api/projects/{project_id}/share", response: "Envelope_ShareLinks_" },
  { method: "POST", path: "/api/projects/{project_id}/share", response: "Envelope_ShareLinkCreated_" },
  { method: "DELETE", path: "/api/projects/{project_id}/share/{token_id}", response: "Envelope_ShareLinkRevoked_" },
  { method: "GET", path: "/api/projects/{project_id}/tour", response: "Envelope_TourPackage_" },
  { method: "GET", path: "/api/projects/{project_id}/tradeoffs", response: "Envelope_Tradeoffs_" },
  { method: "GET", path: "/api/projects/{project_id}/versions", response: "Envelope_DesignVersions_" },
  { method: "POST", path: "/api/projects/{project_id}/versions", response: "Envelope_DesignVersionSaved_" },
  { method: "GET", path: "/api/projects/{project_id}/versions/{version_id}", response: "Envelope_DesignVersionDetail_" },
  { method: "POST", path: "/api/projects/{project_id}/versions/{version_id}/restore", response: "Envelope_DesignVersionRestored_" },
  { method: "POST", path: "/api/projects/{project_id}/walkthrough", response: "JobAccepted" },
  { method: "GET", path: "/api/scenes", response: "Envelope_list_SceneSummary__" },
  { method: "POST", path: "/api/scenes", response: "SceneCreated" },
  { method: "GET", path: "/api/scenes/{scene_id}", response: "Envelope_SceneWithHistory_" },
  { method: "POST", path: "/api/scenes/{scene_id}/assets/upgrade", response: "AssetsUpgraded" },
  { method: "POST", path: "/api/scenes/{scene_id}/design/proposals", response: "ProposalCreated" },
  { method: "POST", path: "/api/scenes/{scene_id}/design/proposals/{proposal_id}/apply", response: "SceneCommitted" },
  { method: "POST", path: "/api/scenes/{scene_id}/design/proposals/{proposal_id}/reject", response: "ProposalRejected" },
  { method: "POST", path: "/api/scenes/{scene_id}/patches", response: "SceneCommitted" },
  { method: "POST", path: "/api/scenes/{scene_id}/patches/preview", response: "PatchPreview" },
  { method: "POST", path: "/api/scenes/{scene_id}/redo", response: "SceneReverted" },
  { method: "POST", path: "/api/scenes/{scene_id}/undo", response: "SceneReverted" },
  { method: "GET", path: "/api/scenes/{scene_id}/validate", response: "Envelope_SceneValidation_" },
  { method: "POST", path: "/api/scenes/{scene_id}/walkthrough/check-position", response: "Envelope_PositionCheck_" },
  { method: "GET", path: "/api/scenes/{scene_id}/walkthrough/spawn", response: "Envelope_Spawn_" },
  { method: "GET", path: "/api/scenes/{scene_id}/walkthrough/tour", response: "Envelope_TourPath_" },
  { method: "GET", path: "/api/scenes/{scene_id}/walkthrough/views", response: "Envelope_list_SavedView__" },
  { method: "POST", path: "/api/scenes/{scene_id}/walkthrough/views", response: "ViewSaved" },
  { method: "GET", path: "/files/assets-web/{path}", response: "Blob" },
  { method: "GET", path: "/files/assets/{path}", response: "Blob" },
  { method: "GET", path: "/files/materials/{path}", response: "Blob" },
  { method: "GET", path: "/files/projects/{project_id}/{path}", response: "Blob" },
] as const;

export interface ApiResponses {
  "GET /": ServiceRoot;
  "GET /api/assets": Envelope_list_AssetRecord__;
  "POST /api/assets/ingest/polyhaven": AssetWritten;
  "POST /api/assets/upload": AssetWritten;
  "GET /api/assets/{asset_id}": Envelope_AssetRecord_;
  "POST /api/assets/{asset_id}/renormalize": AssetWritten;
  "POST /api/auth/login": Envelope_AuthSignedIn_;
  "POST /api/auth/logout": Envelope_AuthSignedOut_;
  "POST /api/auth/logout-everywhere": Envelope_AuthSignedOutEverywhere_;
  "GET /api/auth/me": Envelope_AuthMe_;
  "POST /api/auth/register": Envelope_AuthRegistered_;
  "GET /api/auth/session": Envelope_AuthSession_;
  "GET /api/catalog": Envelope_list_CatalogItem__;
  "GET /api/catalog/{asset_id}": Envelope_CatalogItem_;
  "GET /api/credits": Envelope_Credits_;
  "GET /api/health": Health;
  "GET /api/jobs/types": Envelope_list_JobType__;
  "GET /api/jobs/{job_id}": Envelope_JobDetail_;
  "GET /api/materials": Envelope_list_MaterialRecord__;
  "POST /api/materials/ingest/polyhaven": MaterialWritten;
  "GET /api/materials/{material_id}": Envelope_MaterialRecord_;
  "GET /api/projects": Envelope_list_ProjectRecord__;
  "POST /api/projects": ProjectWritten;
  "DELETE /api/projects/{project_id}": Envelope_ProjectDeleted_;
  "GET /api/projects/{project_id}": Envelope_ProjectDetail_;
  "PATCH /api/projects/{project_id}": ProjectWritten;
  "GET /api/projects/{project_id}/analysis": Envelope_Analysis_;
  "PATCH /api/projects/{project_id}/analysis": AnalysisWritten;
  "POST /api/projects/{project_id}/analyze": JobAccepted;
  "POST /api/projects/{project_id}/assets/resolve": JobAccepted;
  "GET /api/projects/{project_id}/build": Envelope_BuildView_;
  "POST /api/projects/{project_id}/build": JobAccepted;
  "GET /api/projects/{project_id}/element-images": Envelope_ElementImages_;
  "PATCH /api/projects/{project_id}/element-images": Envelope_ElementImages_;
  "POST /api/projects/{project_id}/element-images": JobAccepted;
  "POST /api/projects/{project_id}/elements/generate": ElementsGenerateAccepted;
  "GET /api/projects/{project_id}/events": Envelope_EventPage_;
  "POST /api/projects/{project_id}/film": JobAccepted;
  "GET /api/projects/{project_id}/inputs": Envelope_list_InputRecord__;
  "POST /api/projects/{project_id}/inputs": InputsAdded;
  "DELETE /api/projects/{project_id}/inputs/{input_id}": Envelope_InputDeleted_;
  "GET /api/projects/{project_id}/jobs": Envelope_list_Job__;
  "POST /api/projects/{project_id}/jobs": JobAccepted;
  "POST /api/projects/{project_id}/moodboard/rooms/{room_id}/repaint": JobAccepted;
  "GET /api/projects/{project_id}/outputs": Envelope_Outputs_;
  "POST /api/projects/{project_id}/preview": JobAccepted;
  "GET /api/projects/{project_id}/provenance": Envelope_ProvenanceCoverage_;
  "GET /api/projects/{project_id}/provenance/{scene_object_id}": Envelope_ProvenanceChain_;
  "GET /api/projects/{project_id}/repairs": Envelope_RepairRounds_;
  "GET /api/projects/{project_id}/review": Envelope_ReviewView_;
  "GET /api/projects/{project_id}/reviews": Envelope_ReviewItems_;
  "POST /api/projects/{project_id}/reviews/{item_id}/decision": Envelope_ReviewDecided_;
  "POST /api/projects/{project_id}/scene-plan": JobAccepted;
  "GET /api/projects/{project_id}/scene-reading": Envelope_SceneReadingView_;
  "PATCH /api/projects/{project_id}/scene-reading": Envelope_SceneReadingView_;
  "GET /api/projects/{project_id}/scene-spec": Envelope_SceneSpec_;
  "GET /api/projects/{project_id}/share": Envelope_ShareLinks_;
  "POST /api/projects/{project_id}/share": Envelope_ShareLinkCreated_;
  "DELETE /api/projects/{project_id}/share/{token_id}": Envelope_ShareLinkRevoked_;
  "GET /api/projects/{project_id}/tour": Envelope_TourPackage_;
  "GET /api/projects/{project_id}/tradeoffs": Envelope_Tradeoffs_;
  "GET /api/projects/{project_id}/versions": Envelope_DesignVersions_;
  "POST /api/projects/{project_id}/versions": Envelope_DesignVersionSaved_;
  "GET /api/projects/{project_id}/versions/{version_id}": Envelope_DesignVersionDetail_;
  "POST /api/projects/{project_id}/versions/{version_id}/restore": Envelope_DesignVersionRestored_;
  "POST /api/projects/{project_id}/walkthrough": JobAccepted;
  "GET /api/scenes": Envelope_list_SceneSummary__;
  "POST /api/scenes": SceneCreated;
  "GET /api/scenes/{scene_id}": Envelope_SceneWithHistory_;
  "POST /api/scenes/{scene_id}/assets/upgrade": AssetsUpgraded;
  "POST /api/scenes/{scene_id}/design/proposals": ProposalCreated;
  "POST /api/scenes/{scene_id}/design/proposals/{proposal_id}/apply": SceneCommitted;
  "POST /api/scenes/{scene_id}/design/proposals/{proposal_id}/reject": ProposalRejected;
  "POST /api/scenes/{scene_id}/patches": SceneCommitted;
  "POST /api/scenes/{scene_id}/patches/preview": PatchPreview;
  "POST /api/scenes/{scene_id}/redo": SceneReverted;
  "POST /api/scenes/{scene_id}/undo": SceneReverted;
  "GET /api/scenes/{scene_id}/validate": Envelope_SceneValidation_;
  "POST /api/scenes/{scene_id}/walkthrough/check-position": Envelope_PositionCheck_;
  "GET /api/scenes/{scene_id}/walkthrough/spawn": Envelope_Spawn_;
  "GET /api/scenes/{scene_id}/walkthrough/tour": Envelope_TourPath_;
  "GET /api/scenes/{scene_id}/walkthrough/views": Envelope_list_SavedView__;
  "POST /api/scenes/{scene_id}/walkthrough/views": ViewSaved;
  "GET /files/assets-web/{path}": Blob;
  "GET /files/assets/{path}": Blob;
  "GET /files/materials/{path}": Blob;
  "GET /files/projects/{project_id}/{path}": Blob;
}
