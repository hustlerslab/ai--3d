/**
 * The three verticals a project can be designed for, and what each one is
 * allowed to contain.
 *
 * "Industrial" here is an aesthetic — loft-style offices and workspaces. It is
 * not manufacturing-facility work: the backend refuses briefs that ask for
 * load-bearing, fire-code or machine-guarding work with OUT_OF_SCOPE, and this
 * module deliberately offers no vocabulary for any of it.
 *
 * Room type values must match the backend spelling exactly — they travel to
 * the API as `RoomHint.type`.
 */

import type { ProjectStage, Vertical } from "./types";

export interface VerticalOption {
  value: Vertical;
  label: string;
  /** One line under the label — what kind of space this covers. */
  blurb: string;
}

export const VERTICAL_OPTIONS: readonly VerticalOption[] = [
  { value: "residential", label: "Residential", blurb: "Homes and apartments" },
  { value: "hospitality", label: "Hospitality", blurb: "Hotels, restaurants, cafés and bars" },
  { value: "industrial", label: "Industrial", blurb: "Loft-style offices and workspaces" },
];

export const DEFAULT_VERTICAL: Vertical = "residential";

const ROOM_TYPES: Record<Vertical, readonly string[]> = {
  // Unchanged from the original flat list — residential is the default path.
  residential: ["living_room", "master_bedroom", "bedroom", "kids_bedroom", "kitchen", "dining_room", "study", "bathroom", "balcony", "entry"],
  hospitality: ["hotel_lobby", "guest_room", "suite", "restaurant_floor", "cafe_floor", "bar", "reception", "banquet_hall", "corridor"],
  industrial: ["open_plan_office", "private_office", "meeting_room", "reception", "breakout", "pantry"],
};

/** What "+ Add room" inserts, and what an out-of-vertical row falls back to. */
const DEFAULT_ROOM_TYPE: Record<Vertical, string> = {
  residential: "bedroom",
  hospitality: "guest_room",
  industrial: "private_office",
};

export const roomTypeOptions = (vertical: Vertical): readonly string[] => ROOM_TYPES[vertical];

export const defaultRoomType = (vertical: Vertical): string => DEFAULT_ROOM_TYPE[vertical];

/** Same derived label the room selector has always used: `master_bedroom` → "master bedroom". */
export const roomTypeLabel = (type: string): string => type.replace(/_/g, " ");

/** Keeps a room row submittable after the vertical changes under it. */
export const coerceRoomType = (vertical: Vertical, type: string): string =>
  ROOM_TYPES[vertical].includes(type) ? type : DEFAULT_ROOM_TYPE[vertical];

/**
 * The vertical is fixed once the project has left CREATED — everything
 * analysed so far assumed it. A project that does not exist yet is never
 * locked.
 */
export const isVerticalLocked = (stage: ProjectStage | null | undefined): boolean =>
  stage != null && stage !== "CREATED";
