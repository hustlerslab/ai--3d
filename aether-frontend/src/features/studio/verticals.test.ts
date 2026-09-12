import { describe, expect, it } from "vitest";

import { coerceRoomType, defaultRoomType, isVerticalLocked, roomTypeOptions, VERTICAL_OPTIONS } from "./verticals";
import type { ProjectStage, Vertical } from "./types";

/**
 * These values travel to the backend as `RoomHint.type` and `project.vertical`.
 * A typo here is a silently mis-typed room, so the spellings are asserted
 * literally against aether-backend app/projects/schema.py Vertical.
 */
const BACKEND_ROOM_TYPES: Record<Vertical, string[]> = {
  residential: ["living_room", "master_bedroom", "bedroom", "kids_bedroom", "kitchen", "dining_room", "study", "bathroom", "balcony", "entry"],
  hospitality: ["hotel_lobby", "guest_room", "suite", "restaurant_floor", "cafe_floor", "bar", "reception", "banquet_hall", "corridor"],
  industrial: ["open_plan_office", "private_office", "meeting_room", "reception", "breakout", "pantry"],
};

const VERTICALS = Object.keys(BACKEND_ROOM_TYPES) as Vertical[];

describe("vertical options", () => {
  it("offers exactly the three backend verticals, residential first", () => {
    expect(VERTICAL_OPTIONS.map((o) => o.value)).toEqual(["residential", "hospitality", "industrial"]);
  });

  it("labels every option", () => {
    for (const option of VERTICAL_OPTIONS) {
      expect(option.label.length).toBeGreaterThan(0);
      expect(option.blurb.length).toBeGreaterThan(0);
    }
  });
});

describe("roomTypeOptions", () => {
  it("leaves the residential list exactly as it was", () => {
    expect(roomTypeOptions("residential")).toEqual(BACKEND_ROOM_TYPES.residential);
  });

  it("matches the backend spelling for every vertical", () => {
    for (const vertical of VERTICALS) {
      expect(roomTypeOptions(vertical)).toEqual(BACKEND_ROOM_TYPES[vertical]);
    }
  });

  it("uses snake_case values with no duplicates", () => {
    for (const vertical of VERTICALS) {
      const values = roomTypeOptions(vertical);
      expect(new Set(values).size).toBe(values.length);
      for (const value of values) expect(value).toMatch(/^[a-z]+(_[a-z]+)*$/);
    }
  });

  it("gives each vertical its own vocabulary", () => {
    expect(roomTypeOptions("hospitality")).not.toContain("bedroom");
    expect(roomTypeOptions("industrial")).not.toContain("living_room");
    expect(roomTypeOptions("residential")).not.toContain("hotel_lobby");
  });
});

describe("coerceRoomType", () => {
  it("keeps a row whose type is valid for the vertical", () => {
    expect(coerceRoomType("residential", "kitchen")).toBe("kitchen");
    expect(coerceRoomType("hospitality", "bar")).toBe("bar");
    // reception is shared by two verticals and must survive the switch
    expect(coerceRoomType("industrial", "reception")).toBe("reception");
  });

  it("rewrites a row the new vertical cannot express", () => {
    expect(coerceRoomType("hospitality", "kids_bedroom")).toBe("guest_room");
    expect(coerceRoomType("industrial", "balcony")).toBe("private_office");
    expect(coerceRoomType("residential", "banquet_hall")).toBe("bedroom");
  });

  it("always lands on a value the vertical actually offers", () => {
    for (const from of VERTICALS) {
      for (const to of VERTICALS) {
        for (const type of roomTypeOptions(from)) {
          expect(roomTypeOptions(to)).toContain(coerceRoomType(to, type));
        }
      }
    }
    expect(roomTypeOptions("residential")).toContain(coerceRoomType("residential", "nonsense"));
  });

  it("agrees with the default room type each vertical adds", () => {
    for (const vertical of VERTICALS) {
      expect(roomTypeOptions(vertical)).toContain(defaultRoomType(vertical));
    }
    // unchanged: "+ Add room" has always inserted a bedroom on residential
    expect(defaultRoomType("residential")).toBe("bedroom");
  });
});

describe("isVerticalLocked", () => {
  it("is unlocked while the project does not exist or has not left CREATED", () => {
    expect(isVerticalLocked(null)).toBe(false);
    expect(isVerticalLocked(undefined)).toBe(false);
    expect(isVerticalLocked("CREATED")).toBe(false);
  });

  it("locks at every stage past CREATED", () => {
    const past: ProjectStage[] = [
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
    for (const stage of past) expect(isVerticalLocked(stage)).toBe(true);
  });
});
