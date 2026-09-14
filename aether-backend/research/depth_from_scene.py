"""A depth map built from the planner's geometry — no renderer, no estimator.

    python research/depth_from_scene.py <project_id> <room_id> [out.png]

Written up in docs/ADR-004. Reference only: nothing in `app/` imports this.

Why it exists
-------------
Conditioning image generation on real geometry needs a depth map, and the two
usual ways to get one were unavailable or wasteful here:

  * Blender's Z pass. Blender 5.2 removed `CompositorNodeComposite`, moved the
    compositor to `scene.compositing_node_group`, and its File Output writes
    EXR only. A material override rendered flat white through both
    `View Z Depth` and `View Distance`. Four attempts, no usable depth.
  * A depth estimator (MiDaS/DPT) over a render. Another model to download, and
    it would only be GUESSING at depth we already know exactly.

The planner already holds the answer: every room boundary and every object's
position, size and yaw, all validated and collision-checked. Projecting that
through a known camera is a dozen lines of ray/box intersection and runs in
about 0.1 s — and it is the most trustworthy data in this pipeline.

What it is not
--------------
Objects are oriented bounding BOXES, not their meshes. For structural
conditioning that is enough — and it is also the ceiling: a box tells the model
where volume sits, so the model paints a plausible object filling that volume.
Silhouettes would sharpen shape, which already works; they would not fix
appearance, which is the thing that actually does not transfer (ADR-004).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 704, 448
LENS_MM, SENSOR_MM = 24.0, 36.0
EYE_HEIGHT_M = 1.6
MIN_FRAME_COVER = 0.10          # below this the subject is a speck; refuse


def _slab(origin, dirs, lo, hi):
    """Entry and exit t for an axis-aligned box. Safe on parallel rays."""
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = (lo - origin) / dirs
        t2 = (hi - origin) / dirs
    return (np.nanmax(np.minimum(t1, t2), axis=2),
            np.nanmin(np.maximum(t1, t2), axis=2))


def frame_subject(room: dict, objs: list[dict]):
    """A camera that actually contains the room's largest piece.

    Derived from the subject, not chosen by eye. The first run of this probe
    used a hand-picked look-at, framed a blank corner, and spent a render
    proving nothing — so the framing is computed and then CHECKED before
    anything downstream is asked to run.
    """
    subject = max(objs, key=lambda o: o["dimensions"][0] * o["dimensions"][2])
    sx, sy, sz = subject["position"]
    sw, sh, sd = subject["dimensions"]
    zs = [p[1] for p in room["boundary"]]
    fov_x = 2 * math.atan(SENSOR_MM / 2 / LENS_MM)
    standoff = (sw / 2) / math.tan(fov_x / 2) * 1.7 + sd
    cam = np.array([sx, EYE_HEIGHT_M, min(max(zs) - 0.25, sz + max(2.2, standoff))])
    target = np.array([sx, sy + sh * 0.5, sz])
    return subject, cam, target, fov_x


def _basis(cam, target):
    fwd = target - cam
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    right = right / np.linalg.norm(right)
    return fwd, right, np.cross(right, fwd)


def check_framing(subject: dict, cam, target, fov_x) -> tuple[int, float]:
    """(corners in frame, fraction of the frame filled). Wants 8 and >= 10 %."""
    fwd, right, up = _basis(cam, target)
    sx, sy, sz = subject["position"]
    sw, sh, sd = subject["dimensions"]
    f = (W / 2) / math.tan(fov_x / 2)
    pts = []
    for dx in (-1, 1):
        for dy in (0, 1):
            for dz in (-1, 1):
                rel = np.array([sx + dx * sw / 2, sy + dy * sh, sz + dz * sd / 2]) - cam
                zc = float(np.dot(rel, fwd))
                if zc <= 1e-6:
                    return 0, 0.0                      # behind the camera
                pts.append((W / 2 + f * float(np.dot(rel, right)) / zc,
                            H / 2 - f * float(np.dot(rel, up)) / zc))
    us, vs = [p[0] for p in pts], [p[1] for p in pts]
    inside = sum(0 <= u <= W and 0 <= v <= H for u, v in pts)
    return inside, (max(us) - min(us)) * (max(vs) - min(vs)) / (W * H)


def depth_map(room: dict, objs: list[dict], cam, target, fov_x) -> np.ndarray:
    """Metres to the nearest surface per pixel: object boxes, else the room."""
    fwd, right, up = _basis(cam, target)
    f = (W / 2) / math.tan(fov_x / 2)
    uu, vv = np.meshgrid(np.arange(W) + 0.5 - W / 2, -(np.arange(H) + 0.5 - H / 2))
    dirs = fwd * f + right * uu[..., None] + up * vv[..., None]
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True)

    xs = [p[0] for p in room["boundary"]]
    zs = [p[1] for p in room["boundary"]]
    ceiling = room.get("ceiling_height", 2.8)

    # The camera stands inside the room, so the shell's EXIT is the background.
    _, room_exit = _slab(cam, dirs, np.array([min(xs), 0.0, min(zs)]),
                         np.array([max(xs), ceiling, max(zs)]))
    depth = np.where(room_exit > 0, room_exit, np.inf)

    for o in objs:
        ox, oy, oz = o["position"]
        ow, oh, od = o["dimensions"]
        yaw = o.get("rotation_y", 0.0)
        c, s = math.cos(-yaw), math.sin(-yaw)
        rot = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
        origin = np.array([cam[0] - ox, cam[1] - oy, cam[2] - oz]) @ rot.T
        half = np.array([ow / 2, oh / 2, od / 2])
        lift = np.array([0.0, oh / 2, 0.0])            # objects sit ON the floor
        tmin, tmax = _slab(origin, dirs @ rot.T, -half + lift, half + lift)
        hit = (tmax >= np.maximum(tmin, 0)) & (tmin > 0)
        depth = np.where(hit, np.minimum(depth, tmin), depth)
    return depth


def to_png(depth: np.ndarray) -> Image.Image:
    """Near-white, far-black, normalised over the 1st-99th percentile.

    That is the convention the SD 1.5 depth ControlNets were trained on, and
    the percentile clip stops one stray far corner flattening everything else.
    """
    finite = depth[np.isfinite(depth)]
    near, far = float(np.percentile(finite, 1)), float(np.percentile(finite, 99))
    norm = np.clip((depth - near) / max(far - near, 1e-6), 0.0, 1.0)
    return Image.fromarray(((1.0 - norm) * 255).astype(np.uint8))


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python research/depth_from_scene.py <project_id> <room_id> [out.png]")
        return 2
    project_id, room_id = sys.argv[1], sys.argv[2]
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(f"{room_id}_depth.png")
    spec = json.loads(Path(f"data/projects/{project_id}/planning/scene_spec.json")
                      .read_text(encoding="utf-8"))
    room = next(r for r in spec["rooms"] if r["room_id"] == room_id)
    objs = [o for o in spec["objects"] if o["room_id"] == room_id]
    if not objs:
        print(f"{room_id}: nothing placed in this room")
        return 1

    subject, cam, target, fov_x = frame_subject(room, objs)
    inside, cover = check_framing(subject, cam, target, fov_x)
    print(f"subject : {subject['semantic_type']} "
          f"{subject['dimensions'][0]:.2f}x{subject['dimensions'][1]:.2f}"
          f"x{subject['dimensions'][2]:.2f} m")
    print(f"camera  : {tuple(round(float(v), 2) for v in cam)} -> "
          f"{tuple(round(float(v), 2) for v in target)}")
    print(f"framing : {inside}/8 corners in frame, fills {cover:.0%}")
    if inside < 8 or cover < MIN_FRAME_COVER:
        print("REFUSED: the subject is not properly framed")
        return 1

    depth = depth_map(room, objs, cam, target, fov_x)
    finite = depth[np.isfinite(depth)]
    to_png(depth).save(out)
    print(f"depth   : {finite.min():.2f}-{finite.max():.2f} m -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
