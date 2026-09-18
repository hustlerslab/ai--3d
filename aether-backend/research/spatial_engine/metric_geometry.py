"""Metric geometry providers, with every coordinate conversion written down.

Research only. Imports `app.spatial.planes` (zero production imports) and is
imported only by the Phase 2 benchmark.

WHY AN ADAPTER AND NOT A DIRECT CALL. Phase 1 failed because geometry was built
on assumptions that were never checked: a guessed 60 degree field of view and an
unprojection of affine-invariant depth that silently produced a non-Euclidean
cloud. The measured symptoms were walls tilted 20-30 degrees and scene scale
varying 8.4x between rooms. The lesson is not "use a better model", it is
"never let a coordinate convention be implicit".

So each provider states, in code:

  * what frame the model returns points in,
  * how that frame is converted to Allure's canonical frame,
  * whether the result is metric, and on whose authority,
  * whether intrinsics are predicted or assumed.

THE CONVENTIONS, MEASURED NOT ASSUMED. MoGe-2 was probed on a real benchmark
image before this adapter was written:

    mean Y of the top rows    -0.930      mean Y of the bottom rows  +0.826
    mean X of the left cols   -1.612      mean X of the right cols   +2.319
    mean Z                    +4.509

which is OpenCV convention: +X right, +Y DOWN, +Z forward into the scene.
Allure's canonical frame (the one `app.spatial.planes.unproject` produces) is
+Y UP and -Z forward. The conversion is therefore a negation of Y and Z, applied
in `_to_canonical` and nowhere else.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.spatial import planes as P                                   # noqa: E402

WIDTH, HEIGHT = 704, 448


@dataclass
class MetricGeometryResult:
    """One model's geometry for one image, in Allure's canonical frame.

    `point_map` is already converted. `source_frame` records what it was before
    conversion so the transformation is auditable rather than folklore.
    """

    point_map: np.ndarray                    # (H, W, 3), canonical frame
    valid: np.ndarray                        # (H, W) bool
    depth_map: Optional[np.ndarray]          # (H, W), metres if metric
    camera_intrinsics: Optional[np.ndarray]  # (3, 3) pixel units, or None
    camera_pose: Optional[np.ndarray]        # (4, 4) or None - these are camera frame
    coordinate_frame: str                    # canonical frame description
    source_frame: str                        # what the model actually returned
    metric_scale: bool                       # True => point_map is in real metres
    units: str
    fov_deg: Optional[float]                 # predicted where available
    fov_source: str                          # "predicted" | "assumed"
    confidence: float
    model_name: str
    model_version: str
    notes: list[str] = field(default_factory=list)

    def as_pointmap(self) -> P.PointMap:
        """Hand the geometry to the Phase 1 plane-fitting code unchanged.

        `metric_source` is the switch that makes `wall_contact` use the absolute
        0.12 m threshold instead of the relative one. It is set from
        `metric_scale`, so a provider cannot accidentally claim metres it does
        not have.
        """
        source = (P.MetricSource.METRIC_MODEL if self.metric_scale
                  else P.MetricSource.UNSCALED)
        # `disparity` is kept for the affine-invariant cross-check. For a metric
        # provider it is derived from real depth, so it is genuine inverse depth
        # rather than a model's raw output.
        depth = self.depth_map
        if depth is None:
            depth = -self.point_map[..., 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            disparity = np.where(depth > 1e-6, 1.0 / np.maximum(depth, 1e-6), 0.0)
        return P.PointMap(points=self.point_map, valid=self.valid,
                          disparity=disparity, metric_source=source,
                          fov_deg=self.fov_deg or P.DEFAULT_FOV_DEG,
                          note=f"{self.model_name} {self.model_version}; "
                               f"{self.coordinate_frame}; fov {self.fov_source}")


class MetricGeometryProvider:
    """Stable interface. One method, one result, no hidden state."""

    name = "abstract"
    version = "0"

    def load(self) -> None:
        raise NotImplementedError

    def unload(self) -> None:
        raise NotImplementedError

    def predict(self, image_path: Path) -> MetricGeometryResult:
        raise NotImplementedError


def _to_canonical(points_opencv: np.ndarray) -> np.ndarray:
    """OpenCV (+X right, +Y down, +Z forward) -> Allure (+X right, +Y up, -Z forward).

    Negating Y and Z is a proper rotation (180 degrees about X), so it preserves
    handedness, distances and angles. Written here once, used nowhere else.
    """
    out = points_opencv.astype(np.float64, copy=True)
    out[..., 1] *= -1.0
    out[..., 2] *= -1.0
    return out


class MoGe2Provider(MetricGeometryProvider):
    """MoGe-2, MIT licensed, metric point map with predicted intrinsics.

    Licence verified from the primary sources this session: the repository states
    MIT for the code (excepting vendored DINOv2 under Apache-2.0) and the
    `Ruicheng/moge-2-vitl` model card states `mit`. Commercial use permitted.
    """

    name = "MoGe-2"

    def __init__(self, checkpoint: str = "Ruicheng/moge-2-vitl"):
        self.checkpoint = checkpoint
        self.version = checkpoint
        self._model = None

    def load(self) -> None:
        from moge.model.v2 import MoGeModel

        self._model = MoGeModel.from_pretrained(self.checkpoint).to("cuda").eval()

    def unload(self) -> None:
        import gc

        import torch

        self._model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        gc.collect()

    def predict(self, image_path: Path) -> MetricGeometryResult:
        import torch
        from PIL import Image

        image = Image.open(image_path).convert("RGB").resize((WIDTH, HEIGHT))
        tensor = torch.tensor(np.asarray(image) / 255.0, dtype=torch.float32,
                              device="cuda").permute(2, 0, 1)
        with torch.no_grad():
            out = self._model.infer(tensor)

        points = out["points"].detach().float().cpu().numpy()
        depth = out["depth"].detach().float().cpu().numpy()
        mask = out["mask"].detach().float().cpu().numpy() > 0.5
        finite = np.isfinite(points).all(axis=-1) & np.isfinite(depth)
        valid = mask & finite & (depth > 1e-6)

        # MoGe returns NORMALISED intrinsics (cx = cy = 0.5). Converting to pixel
        # units here rather than at the call site, because a normalised K that
        # looks like a pixel K is exactly the sort of silent error Phase 1 was
        # built on.
        k_norm = out["intrinsics"].detach().float().cpu().numpy()
        k_pixels = k_norm.copy()
        k_pixels[0, :] *= WIDTH
        k_pixels[1, :] *= HEIGHT
        fov = 2.0 * math.degrees(math.atan(0.5 / float(k_norm[0, 0])))

        return MetricGeometryResult(
            point_map=_to_canonical(points), valid=valid, depth_map=depth,
            camera_intrinsics=k_pixels, camera_pose=None,
            coordinate_frame="canonical: +X right, +Y up, -Z forward, metres",
            source_frame="OpenCV: +X right, +Y down, +Z forward (measured on a "
                         "benchmark image, not assumed)",
            metric_scale=True, units="metres",
            fov_deg=round(fov, 3), fov_source="predicted",
            confidence=float(valid.mean()),
            model_name=self.name, model_version=self.checkpoint,
            notes=["intrinsics converted from normalised to pixel units here",
                   "Y and Z negated to reach the canonical frame"])


class DepthAnythingRelativeProvider(MetricGeometryProvider):
    """The Phase 1 method, wrapped in the same interface as the control arm.

    Kept so the comparison runs through one harness. It reports
    `metric_scale=False`, which routes `wall_contact` to the relative threshold -
    the same behaviour Phase 1 measured.
    """

    name = "DepthAnythingV2-Small"
    version = "depth-anything/Depth-Anything-V2-Small-hf"

    def __init__(self, fov_deg: float = P.DEFAULT_FOV_DEG):
        self.fov_deg = fov_deg
        self._model = None
        self._processor = None

    def load(self) -> None:
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        self._processor = AutoImageProcessor.from_pretrained(self.version)
        self._model = AutoModelForDepthEstimation.from_pretrained(
            self.version).to("cuda").eval()

    def unload(self) -> None:
        import gc

        import torch

        self._model = None
        self._processor = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        gc.collect()

    def predict(self, image_path: Path) -> MetricGeometryResult:
        import torch
        from PIL import Image

        image = Image.open(image_path).convert("RGB").resize((WIDTH, HEIGHT))
        inputs = self._processor(images=image, return_tensors="pt").to("cuda")
        with torch.no_grad():
            predicted = self._model(**inputs).predicted_depth
        disparity = torch.nn.functional.interpolate(
            predicted.unsqueeze(1), size=(HEIGHT, WIDTH), mode="bicubic",
            align_corners=False).squeeze().detach().float().cpu().numpy()

        pointmap = P.unproject(disparity, fov_deg=self.fov_deg)
        return MetricGeometryResult(
            point_map=pointmap.points, valid=pointmap.valid, depth_map=None,
            camera_intrinsics=None, camera_pose=None,
            coordinate_frame="canonical: +X right, +Y up, -Z forward, UNSCALED",
            source_frame="affine-invariant inverse depth; no frame of its own",
            metric_scale=False, units="relative",
            fov_deg=self.fov_deg, fov_source="assumed",
            confidence=float(pointmap.valid.mean()),
            model_name=self.name, model_version=self.version,
            notes=["affine ambiguity d = a/Z + b is NOT resolved; distances are "
                   "comparable within one image only"])


__all__ = ["MetricGeometryProvider", "MetricGeometryResult", "MoGe2Provider",
           "DepthAnythingRelativeProvider", "WIDTH", "HEIGHT"]
