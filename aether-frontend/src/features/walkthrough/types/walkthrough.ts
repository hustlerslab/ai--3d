/**
 * Types for the RE Walkthrough Pro engine API.
 *
 * These mirror the DTOs the engine returns (readme2 §26). They are hand-written
 * rather than generated because the engine is plain JavaScript with no schema
 * to generate from — so this file is the contract, and it is the one place to
 * change when the engine's response shape changes.
 *
 * Nothing here is mock data. Unlike the rest of this app, the walkthrough
 * feature talks to a real process — see the walkthrough exception in CLAUDE.md.
 */

/* ── Lifecycle ─────────────────────────────────────────────────────────── */

/**
 * The coarse status the engine reports. Mirrors src/api/stateMachine.js.
 */
export type WalkthroughStatus =
  | "created"
  | "uploading"
  | "uploaded"
  | "analyzing"
  | "curating"
  | "classifying"
  | "planning"
  | "generating"
  | "stitching"
  | "qa"
  | "ready"
  | "revision"
  | "completed"
  | "failed";

/** Statuses where no further polling will change anything. */
export const TERMINAL_STATUSES: readonly WalkthroughStatus[] = [
  "ready",
  "completed",
  "failed",
] as const;

/** Statuses where the engine is actively working. */
export const BUSY_STATUSES: readonly WalkthroughStatus[] = [
  "analyzing",
  "curating",
  "classifying",
  "planning",
  "generating",
  "stitching",
  "qa",
  "revision",
] as const;

/** Per-scene job status. */
export type SceneStatus =
  | "pending"
  | "queued"
  | "running"
  | "retrying"
  | "completed"
  | "failed"
  | "skipped";

/* ── Errors ────────────────────────────────────────────────────────────── */

/**
 * The engine's error vocabulary (readme2 §24). Anything outside this list is
 * rendered with a generic fallback message.
 */
export type WalkthroughErrorCode =
  | "UPLOAD_FAILED"
  | "INVALID_IMAGE"
  | "NO_IMAGES"
  | "ANALYSIS_FAILED"
  | "CURATION_FAILED"
  | "NO_USABLE_IMAGES"
  | "VIDEO_GENERATION_FAILED"
  | "VIDEO_TIMEOUT"
  | "FFMPEG_NOT_FOUND"
  | "STITCH_FAILED"
  | "QA_FAILED"
  | "REVISION_FAILED"
  | "SERVER_UNAVAILABLE"
  // Transport and request-level codes
  | "WALKTHROUGH_NOT_FOUND"
  | "GENERATION_ALREADY_RUNNING"
  | "REVISION_ALREADY_RUNNING"
  | "SCENE_NOT_FOUND"
  | "SCENE_NOT_READY"
  | "UNSUPPORTED_FILE_TYPE"
  | "FILE_TOO_LARGE"
  | "TOO_MANY_FILES"
  | "INVALID_STATE"
  | "NETWORK_ERROR"
  | "INTERNAL_ERROR";

export interface WalkthroughError {
  code: WalkthroughErrorCode | string;
  message: string;
  stage?: string | null;
  retryable?: boolean;
}

/**
 * Thrown by every function in the API client. Carries the engine's structured
 * error so the UI can switch on `code` rather than parse a message.
 */
export class WalkthroughApiError extends Error {
  readonly code: WalkthroughErrorCode | string;
  readonly status: number;
  readonly stage: string | null;
  readonly retryable: boolean;

  constructor(
    code: WalkthroughErrorCode | string,
    message: string,
    status = 0,
    opts: { stage?: string | null; retryable?: boolean } = {},
  ) {
    super(message);
    this.name = "WalkthroughApiError";
    this.code = code;
    this.status = status;
    this.stage = opts.stage ?? null;
    this.retryable = opts.retryable ?? false;
  }
}

/* ── Resources ─────────────────────────────────────────────────────────── */

export interface WalkthroughScene {
  id: string;
  position: number;
  roomType: string;
  cameraMove: string | null;
  status: SceneStatus;
  sceneFile: string | null;
  videoUrl: string | null;
  /** Present on the /scenes listing only. */
  available?: boolean;
  attempts?: number;
  error?: string | null;
}

/** The compact per-scene record the polling endpoint returns. */
export interface SceneProgressItem {
  position: number;
  roomType: string;
  status: SceneStatus;
  sceneFile: string | null;
}

export interface WalkthroughPhoto {
  index: number;
  filename: string;
  size: number | null;
  mime: string | null;
  usable: boolean | null;
  roomType: string | null;
  qualityScore: number | null;
  uploadedAt: string | null;
}

export interface QaCheck {
  name: string;
  result: "PASS" | "FAIL" | "WARN" | "NOTE";
  detail: string;
}

export interface QaResult {
  score: number | null;
  passed: boolean | null;
  grade?: string;
  action?: string;
  checks?: QaCheck[];
  /**
   * Unscored notes. A valid file can still warrant one — too few rooms, a
   * skipped scene — and they must be shown, or a warned result reads as a
   * clean pass.
   */
  warnings?: QaCheck[];
  hasWarnings?: boolean;
  skippedRooms?: string[];
}

export interface RevisionEntry {
  revisionNumber: number;
  room: string;
  sceneFile: string;
  oldCameraMove: string;
  newCameraMove: string;
  qaScore: number;
  timestamp: string;
}

export interface ApprovalState {
  status: "pending" | "approved";
  revisionCount: number;
  history?: RevisionEntry[];
  approvedAt?: string;
}

/**
 * Generation spend. Reported in whatever currency the engine bills in — this
 * is external API spend, not a customer-facing rupee figure, so it is rendered
 * with an explicit currency code and never a bare currency symbol.
 */
export interface WalkthroughCosts {
  apify: number | null;
  higgsfield: number | null;
  total: number | null;
  currency: string;
  estimated: boolean;
  mock?: boolean;
}

/* ── API responses ─────────────────────────────────────────────────────── */

export interface CreateWalkthroughResponse {
  success: true;
  walkthroughId: string;
  slug: string;
  status: WalkthroughStatus;
  workspaceDir: string;
}

export interface UploadRejection {
  originalName: string;
  reason: string;
  detail: string;
}

export interface UploadAcceptance {
  originalName: string;
  filename: string;
  size: number;
  mime: string;
  index: number;
}

export interface UploadImagesResponse {
  success: true;
  walkthroughId: string;
  totalUploaded: number;
  totalRejected: number;
  accepted: UploadAcceptance[];
  rejected: UploadRejection[];
  status: WalkthroughStatus;
}

/** GET /:id/status — the lightweight polling shape. */
export interface WalkthroughStatusDto {
  status: WalkthroughStatus;
  stage: string;
  progress: number | null;
  scenes: SceneProgressItem[];
  mockMode: boolean;
  revision: ApprovalState;
  error: WalkthroughError | null;
  videoVersion: number;
  terminal: boolean;
  qa: { score: number; passed: boolean } | null;
}

/** GET /:id — the full record. */
export interface WalkthroughDto {
  id: string;
  title: string | null;
  status: WalkthroughStatus;
  stage: string;
  progress: number | null;
  property: Record<string, unknown>;
  photos: Array<{
    filename: string;
    usable: boolean | null;
    roomType: string | null;
    quality: number | null;
  }>;
  scenes: WalkthroughScene[];
  qa: QaResult;
  approval: ApprovalState;
  costs: WalkthroughCosts | null;
  error: WalkthroughError | null;
  mockMode: boolean;
  createdAt: string;
  updatedAt: string;
  videoVersion: number;
  videoUrl: string | null;
  downloadUrl: string | null;
}

export interface GenerateResponse {
  success: true;
  walkthroughId: string;
  status: WalkthroughStatus;
  stage: string;
  message: string;
  photoCount: number;
}

export interface ReviseResponse {
  success: true;
  walkthroughId: string;
  status: WalkthroughStatus;
  revising: { position: number; roomType: string; sceneFile: string };
  revisionCount: number;
  message: string;
}

export interface ApproveResponse {
  success: true;
  walkthroughId: string;
  status: WalkthroughStatus;
  approval: ApprovalState;
  videoUrl?: string;
  downloadUrl?: string;
}

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  mockMode: boolean;
  timestamp: string;
}

/* ── Client-side upload model ──────────────────────────────────────────── */

/**
 * A file the user has picked but not yet sent. Held in React state only.
 * `previewUrl` is an object URL and must be revoked when the item is removed,
 * or the browser leaks the decoded image for the life of the page.
 */
export interface PendingImage {
  id: string;
  file: File;
  previewUrl: string;
  sizeLabel: string;
  /** Set when local validation rejects the file before any upload happens. */
  error: string | null;
}
