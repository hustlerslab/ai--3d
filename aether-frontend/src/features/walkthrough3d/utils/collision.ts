/**
 * Client-side walk collision — a lightweight port of the backend's
 * walkthrough position rules so first-person movement never round-trips per
 * frame. The backend stays authoritative for anything that mutates the scene.
 */

import type { AetherScene, Vec2 } from "../types/scene";

export const EYE_HEIGHT = 1.6;
export const PERSON_RADIUS = 0.3;

function pointSegmentDistance(p: Vec2, a: Vec2, b: Vec2): number {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const lengthSq = dx * dx + dz * dz;
  if (lengthSq < 1e-9) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  const t = Math.max(
    0,
    Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / lengthSq),
  );
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dz));
}

function pointInPolygon(p: Vec2, poly: Vec2[]): boolean {
  let inside = false;
  const [x, z] = p;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [x1, z1] = poly[i];
    const [x2, z2] = poly[j];
    if (z1 > z !== z2 > z && x < x1 + ((z - z1) * (x2 - x1)) / (z2 - z1)) {
      inside = !inside;
    }
  }
  return inside;
}

interface DoorSpan {
  center: Vec2;
  direction: Vec2;
  halfWidth: number;
}

export interface WalkWorld {
  rooms: Vec2[][];
  walls: Array<{ start: Vec2; end: Vec2; thickness: number }>;
  doors: DoorSpan[];
  /** Blocking furniture footprints (rotated rect corners). */
  footprints: Vec2[][];
}

export function buildWalkWorld(scene: AetherScene): WalkWorld {
  const doors: DoorSpan[] = [];
  for (const opening of scene.openings) {
    if (opening.type !== "door") continue;
    const wall = scene.walls.find((w) => w.wall_id === opening.wall_id);
    if (!wall) continue;
    const length = Math.hypot(
      wall.end[0] - wall.start[0],
      wall.end[1] - wall.start[1],
    );
    if (length < 1e-9) continue;
    const t = opening.position / length;
    doors.push({
      center: [
        wall.start[0] + (wall.end[0] - wall.start[0]) * t,
        wall.start[1] + (wall.end[1] - wall.start[1]) * t,
      ],
      direction: [
        (wall.end[0] - wall.start[0]) / length,
        (wall.end[1] - wall.start[1]) / length,
      ],
      halfWidth: opening.width / 2,
    });
  }

  const footprints: Vec2[][] = [];
  for (const obj of scene.objects) {
    if (obj.dimensions[1] * obj.scale[1] <= 0.1) continue; // rugs are walkable
    const hw = (obj.dimensions[0] * obj.scale[0]) / 2 + PERSON_RADIUS;
    const hd = (obj.dimensions[2] * obj.scale[2]) / 2 + PERSON_RADIUS;
    const c = Math.cos(-obj.rotation_y);
    const s = Math.sin(-obj.rotation_y);
    const corners: Vec2[] = (
      [
        [-hw, -hd],
        [hw, -hd],
        [hw, hd],
        [-hw, hd],
      ] as Vec2[]
    ).map(([x, z]) => [
      obj.position[0] + x * c - z * s,
      obj.position[2] + x * s + z * c,
    ]);
    footprints.push(corners);
  }

  return {
    rooms: scene.rooms.map((r) => r.boundary),
    walls: scene.walls.map((w) => ({
      start: w.start,
      end: w.end,
      thickness: w.thickness,
    })),
    doors,
    footprints,
  };
}

function nearDoor(world: WalkWorld, p: Vec2, slack = 0.4): boolean {
  for (const door of world.doors) {
    const dx = p[0] - door.center[0];
    const dz = p[1] - door.center[1];
    const along = Math.abs(dx * door.direction[0] + dz * door.direction[1]);
    const across = Math.abs(-dx * door.direction[1] + dz * door.direction[0]);
    if (along <= door.halfWidth && across <= slack + PERSON_RADIUS) return true;
  }
  return false;
}

export function canStand(world: WalkWorld, x: number, z: number): boolean {
  const p: Vec2 = [x, z];
  const inRoom = world.rooms.some((boundary) => pointInPolygon(p, boundary));
  if (!inRoom && !nearDoor(world, p)) return false;

  for (const wall of world.walls) {
    if (
      pointSegmentDistance(p, wall.start, wall.end) <
      wall.thickness / 2 + PERSON_RADIUS
    ) {
      if (!nearDoor(world, p)) return false;
    }
  }

  for (const footprint of world.footprints) {
    if (pointInPolygon(p, footprint)) return false;
  }

  return true;
}

/**
 * Attempt a move with wall sliding: try the full step, then each axis alone.
 */
export function tryMove(
  world: WalkWorld,
  from: Vec2,
  dx: number,
  dz: number,
): Vec2 {
  if (canStand(world, from[0] + dx, from[1] + dz)) {
    return [from[0] + dx, from[1] + dz];
  }
  if (canStand(world, from[0] + dx, from[1])) return [from[0] + dx, from[1]];
  if (canStand(world, from[0], from[1] + dz)) return [from[0], from[1] + dz];
  return from;
}
