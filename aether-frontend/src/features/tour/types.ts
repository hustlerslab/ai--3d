/** Web package contract written by the backend's preview / walkthrough jobs (plan §8A). */

export type Vec3 = [number, number, number];
export type Vec2 = [number, number];

export interface TourNode {
  id: string;
  room_id: string;
  room_name: string;
  label: string;
  /** Scene coordinates: x right, y up, z toward the viewer. Eye height. */
  position: Vec3;
  /** Scene yaw (radians) of the panorama's centre direction. */
  yaw: number;
  yaw_deg: number;
  pano_url: string;
  links: string[];
}

export interface TourRoom {
  room_id: string;
  name: string;
  type: string;
  boundary: Vec2[];
}

export interface TourPackage {
  schema_version: string;
  project_id: string;
  project_name: string;
  scene_id: string;
  scene_version: number;
  quality: "preview" | "final";
  modes: string[];
  explore: { scene_id: string; scene_url: string };
  style: { name?: string; tags?: string[]; palette?: string[]; lighting_mood?: string };
  rooms: TourRoom[];
  tour: {
    nodes: TourNode[];
    route: string[];
    autoplay_seconds_per_node: number;
  };
  film?: { mp4_url: string; poster_url?: string; profile?: string };
  generated_at: string;
}

export class TourApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "TourApiError";
  }
}
