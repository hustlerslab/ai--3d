/**
 * Presentation helpers for the walkthrough feature.
 *
 * The engine speaks in codes; people do not. Everything here turns an engine
 * value into something a homeowner can read, in one place, so the same room
 * never appears as "primary-bedroom" on one screen and "Primary Bedroom" on
 * another.
 */

import type {
  SceneStatus,
  WalkthroughCosts,
  WalkthroughStatus,
} from "../types/walkthrough";
import { BUSY_STATUSES, TERMINAL_STATUSES } from "../types/walkthrough";

/* ── Status vocabulary ─────────────────────────────────────────────────── */

/**
 * What the engine is doing, said plainly.
 *
 * readme2 §68 fixes the product language: people upload images and get a
 * cinematic walkthrough. They are not "running a pipeline", so no stage label
 * here mentions one.
 */
const STAGE_LABELS: Record<WalkthroughStatus, string> = {
  created: "Ready for your photos",
  uploading: "Receiving your photos",
  uploaded: "Photos received",
  analyzing: "Reviewing your photos",
  curating: "Choosing the best shots",
  classifying: "Identifying each room",
  planning: "Planning the walkthrough",
  generating: "Filming each room",
  stitching: "Assembling the walkthrough",
  qa: "Checking the result",
  ready: "Ready to watch",
  revision: "Re-filming one room",
  completed: "Approved",
  failed: "Something went wrong",
};

export function stageLabel(status: WalkthroughStatus): string {
  return STAGE_LABELS[status] ?? "Working";
}

export const isTerminal = (status: WalkthroughStatus): boolean =>
  TERMINAL_STATUSES.includes(status);

export const isBusy = (status: WalkthroughStatus): boolean =>
  BUSY_STATUSES.includes(status);

/* ── Rooms ─────────────────────────────────────────────────────────────── */

/**
 * Engine room slugs are kebab-case; a few need more than a capitalisation pass.
 */
const ROOM_LABELS: Record<string, string> = {
  exterior: "Exterior",
  entry: "Entry",
  foyer: "Foyer",
  hallway: "Hallway",
  living: "Living Room",
  "great-room": "Great Room",
  dining: "Dining Room",
  kitchen: "Kitchen",
  "primary-bedroom": "Primary Bedroom",
  bedroom: "Bedroom",
  "primary-bathroom": "Primary Bathroom",
  bathroom: "Bathroom",
  office: "Office",
  library: "Library",
  gym: "Gym",
  cinema: "Home Cinema",
  "wine-room": "Wine Room",
  backyard: "Backyard",
  pool: "Pool",
  patio: "Patio",
  balcony: "Balcony",
  view: "View",
  specialty: "Feature Space",
  detail: "Detail",
  unknown: "Additional Space",
};

export function roomLabel(roomType: string | null | undefined): string {
  if (!roomType) return "Untitled Space";
  return (
    ROOM_LABELS[roomType] ??
    roomType
      .split("-")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ")
  );
}

/* ── Scene status ──────────────────────────────────────────────────────── */

export function sceneStatusLabel(status: SceneStatus): string {
  switch (status) {
    case "pending":
      return "Queued";
    case "queued":
      return "Queued";
    case "running":
      return "Filming";
    case "retrying":
      return "Retrying";
    case "completed":
      return "Done";
    case "failed":
      return "Failed";
    case "skipped":
      return "Skipped";
    default:
      return status;
  }
}

/** Maps a scene status onto the shared StatusPill tones. */
export function sceneStatusTone(
  status: SceneStatus,
): "success" | "warning" | "danger" | "info" | "neutral" {
  switch (status) {
    case "completed":
      return "success";
    case "running":
    case "retrying":
      return "info";
    case "failed":
      return "danger";
    case "skipped":
      return "warning";
    default:
      return "neutral";
  }
}

/* ── Errors ────────────────────────────────────────────────────────────── */

interface FriendlyError {
  title: string;
  detail: string;
  /** What the user can actually do about it. */
  action?: string;
}

/**
 * Engine error code → something worth reading.
 *
 * readme2 §24 requires user-friendly messages and forbids exposing stack
 * traces. Each entry says what happened and what to do; where nothing can be
 * done, it says that rather than inviting a pointless retry.
 */
const ERROR_COPY: Record<string, FriendlyError> = {
  NO_IMAGES: {
    title: "No photos yet",
    detail: "This walkthrough has no photos to work from.",
    action: "Add at least one photo, then start the walkthrough.",
  },
  INVALID_IMAGE: {
    title: "Unreadable image",
    detail: "One or more files were not valid JPEG, PNG, or WebP images.",
    action: "Re-export them as JPEG and try again.",
  },
  UNSUPPORTED_FILE_TYPE: {
    title: "Unsupported file type",
    detail: "Only JPEG, PNG, and WebP images can be used.",
    action: "Remove the other files and upload again.",
  },
  FILE_TOO_LARGE: {
    title: "Photo too large",
    detail: "Each photo must be under 20 MB.",
    action: "Resize the largest photos and try again.",
  },
  TOO_MANY_FILES: {
    title: "Too many photos at once",
    detail: "Up to 50 photos can be uploaded in one go.",
    action: "Upload them in smaller batches.",
  },
  UPLOAD_FAILED: {
    title: "Upload did not finish",
    detail: "The photos did not reach the engine.",
    action: "Check your connection and try again.",
  },
  ANALYSIS_FAILED: {
    title: "Could not review the photos",
    detail: "The engine stopped while inspecting your images.",
    action: "Try starting the walkthrough again.",
  },
  CURATION_FAILED: {
    title: "Could not choose the shots",
    detail: "The engine stopped while selecting which photos to use.",
    action: "Try starting the walkthrough again.",
  },
  NO_USABLE_IMAGES: {
    title: "No usable photos",
    detail:
      "Every photo was set aside — usually watermarks, estate-agent banners, floorplans, or duplicates.",
    action: "Upload clean photos with no text baked into the image.",
  },
  VIDEO_GENERATION_FAILED: {
    title: "A room could not be filmed",
    detail: "The video engine could not produce the clips for this walkthrough.",
    action: "You can retry — completed rooms are kept and will not be re-filmed.",
  },
  VIDEO_TIMEOUT: {
    title: "The video engine took too long",
    detail: "One or more rooms did not finish in the time allowed.",
    action: "Retry — rooms that already finished are kept.",
  },
  FFMPEG_NOT_FOUND: {
    title: "Video tools are not installed",
    detail: "The engine needs FFmpeg on the machine running it, and could not find it.",
    action: "This one is for whoever runs the engine — it is not something you can fix here.",
  },
  STITCH_FAILED: {
    title: "Could not assemble the walkthrough",
    detail: "The room clips were made, but joining them into one video failed.",
    action: "Retry — the individual room clips are kept.",
  },
  QA_FAILED: {
    title: "Quality check could not run",
    detail: "The walkthrough was built but could not be verified.",
    action: "Retry the quality check, or review the video yourself.",
  },
  REVISION_FAILED: {
    title: "Could not re-film that room",
    detail: "The room you asked to change could not be regenerated.",
    action: "Try again, or pick a different room. The rest of the walkthrough is untouched.",
  },
  GENERATION_ALREADY_RUNNING: {
    title: "Already working",
    detail: "This walkthrough is already being built.",
    action: "Wait for it to finish — progress is shown above.",
  },
  REVISION_ALREADY_RUNNING: {
    title: "A revision is already running",
    detail: "One room is already being re-filmed.",
    action: "Wait for it to finish before requesting another.",
  },
  SCENE_NOT_FOUND: {
    title: "No such room",
    detail: "That room is not part of this walkthrough.",
    action: "Pick a room from the list.",
  },
  SCENE_NOT_READY: {
    title: "Room not ready",
    detail: "That room has not finished filming yet.",
  },
  WALKTHROUGH_NOT_FOUND: {
    title: "Walkthrough not found",
    detail: "The engine has no record of this walkthrough.",
    action: "Start a new one.",
  },
  INVALID_STATE: {
    title: "Not possible right now",
    detail: "That action does not apply at this stage of the walkthrough.",
  },
  NETWORK_ERROR: {
    title: "Engine unreachable",
    detail: "The walkthrough engine is not responding.",
    action: "Make sure it is running, then try again.",
  },
  SERVER_UNAVAILABLE: {
    title: "Engine not responding",
    detail: "The walkthrough engine took too long to answer.",
    action: "Check that it is running, then try again.",
  },
};

const GENERIC_ERROR: FriendlyError = {
  title: "Something went wrong",
  detail: "The walkthrough engine reported an error.",
  action: "Try again in a moment.",
};

/**
 * Look up readable copy for an engine error.
 *
 * The engine's own message is deliberately NOT shown as the headline — it is
 * written for an operator reading logs. It is passed through as `technical` so
 * a developer can still see it in the detail line if the UI chooses to show it.
 */
export function friendlyError(
  code: string | undefined,
  engineMessage?: string,
): FriendlyError & { technical: string | null } {
  const copy = (code && ERROR_COPY[code]) || GENERIC_ERROR;
  return { ...copy, technical: engineMessage ?? null };
}

/* ── Formatting ────────────────────────────────────────────────────────── */

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Generation spend.
 *
 * This is external API spend in the engine's billing currency, not a
 * customer-facing rupee figure — so it is rendered with an explicit currency
 * code and never a bare symbol, keeping CLAUDE.md rule 7 intact.
 *
 * readme2 §48 is strict: never invent a price, and never show a fake value.
 * A null total returns null and the caller renders nothing at all.
 */
export function formatCost(costs: WalkthroughCosts | null): string | null {
  if (!costs || costs.total === null) return null;
  if (costs.mock) return "No spend — demo mode";

  const amount = costs.total.toFixed(2);
  const basis = costs.estimated ? "estimated" : "actual";
  return `${costs.currency} ${amount} (${basis})`;
}

export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}
