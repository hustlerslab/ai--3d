"""SAM 2 object grounding, isolated from production.

Research only. Nothing in `app/` imports this, and this phase modifies no
production module - `app/spatial/planes.py` still has zero production importers
and is used here exactly as Phase 2 left it.

WHAT THIS EXISTS TO TEST, AND NOTHING ELSE. Phase 2 fixed the geometry -
Manhattan residual 17.73 -> 3.67 degrees, scale in real metres, AUC 0.55 -> 0.72,
UNKNOWN 29.7% -> 0% - and left one failure standing: false-wall 24.3%, with all
nine errors on open-structure furniture (chairs, bar stools, armchairs, an
ottoman) measuring 0.009-0.080 m from a wall. The diagnosis was that a chair's
BOUNDING BOX contains the wall between its legs, so the box is near the wall
even when the chair is not.

This module replaces the box with a SAM 2 mask. That is the only change.

THE SELECTION RULE IS FIXED BEFORE ANY RESULT IS SEEN. SAM returns three
candidate masks per prompt with predicted-IoU scores. The rule is: take the
highest predicted IoU, ties broken by the lower candidate index. It uses only
SAM's own confidence - never the benchmark label, never the annotation prose,
never the resulting wall distance. Every candidate and score is recorded, so if
the rule ever looks convenient the record shows what else was on offer.

WHAT THE BOX IS STILL ALLOWED TO DO. The box is used as SAM's PROMPT, which the
brief permits explicitly. What is under test is the box as the geometric
FOOTPRINT. Those are different uses, and only the second one changes.

WHAT STAYS FROZEN. Wall fitting still excludes annotated object BOXES exactly as
Phase 2 did. Swapping that to masks as well would be a second variable and would
make the comparison uninterpretable, so it is deliberately left alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

WIDTH, HEIGHT = 704, 448

#: Apache-2.0 for code AND checkpoints, verified at github.com/facebookresearch/sam2.
#: Hiera base-plus (80.8M) is the size the architecture document named. The Meta
#: `sam2` pip package wants WSL and a compiled CUDA kernel on Windows; the
#: transformers port needs neither, so the torch/CUDA environment is untouched.
DEFAULT_CHECKPOINT = "facebook/sam2.1-hiera-base-plus"


@dataclass
class SegmentationResult:
    """One object's mask, plus everything needed to audit why it was chosen."""

    mask: np.ndarray                      # (H, W) bool - the selected mask
    candidates: list = field(default_factory=list)
    scores: list = field(default_factory=list)
    candidate_areas: list = field(default_factory=list)
    selected_index: int = 0
    selection_rule: str = "max predicted IoU, ties to lower index"
    mask_area: int = 0
    bbox_area: int = 0
    area_ratio: float = 0.0               # mask / bbox; the open-structure signal
    model_name: str = ""
    checkpoint: str = ""
    failure_reason: Optional[str] = None


class Sam2Grounder:
    """Box prompt in, object mask out. No hidden state, no randomness."""

    name = "SAM2"

    def __init__(self, checkpoint: str = DEFAULT_CHECKPOINT):
        self.checkpoint = checkpoint
        self._model = None
        self._processor = None

    def load(self) -> None:
        from transformers import Sam2Model, Sam2Processor

        self._processor = Sam2Processor.from_pretrained(self.checkpoint)
        self._model = Sam2Model.from_pretrained(self.checkpoint).to("cuda").eval()

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

    def segment(self, image_path: Path, box: Sequence[float]) -> SegmentationResult:
        """Mask for the object inside `box`, at the benchmark's own resolution.

        A failure returns an empty mask and a `failure_reason` rather than
        raising, so one bad case is recorded as a bad case instead of deleting
        the other forty-seven.
        """
        import torch
        from PIL import Image

        x1, y1, x2, y2 = (float(v) for v in box)
        bbox_area = int(max(0.0, x2 - x1) * max(0.0, y2 - y1))
        image = Image.open(image_path).convert("RGB").resize((WIDTH, HEIGHT))

        try:
            inputs = self._processor(images=image, input_boxes=[[[x1, y1, x2, y2]]],
                                     return_tensors="pt").to("cuda")
            with torch.no_grad():
                out = self._model(**inputs, multimask_output=True)
            masks = self._processor.post_process_masks(
                out.pred_masks.cpu(), inputs["original_sizes"])[0]
            scores = out.iou_scores[0, 0].detach().float().cpu().numpy()
        except Exception as exc:                                   # noqa: BLE001
            return SegmentationResult(
                mask=np.zeros((HEIGHT, WIDTH), dtype=bool), bbox_area=bbox_area,
                model_name=self.name, checkpoint=self.checkpoint,
                failure_reason=("%s: %s" % (type(exc).__name__, exc))[:200])

        candidates = [masks[0, i].numpy().astype(bool) for i in range(masks.shape[1])]
        areas = [int(c.sum()) for c in candidates]

        # The rule, applied blind: SAM's own predicted IoU decides, ties to the
        # lower index. Nothing reachable from here can see the benchmark answer.
        best = int(np.lexsort((np.arange(len(scores)), -np.asarray(scores)))[0])

        return SegmentationResult(
            mask=candidates[best], candidates=candidates,
            scores=[round(float(s), 4) for s in scores], candidate_areas=areas,
            selected_index=best, mask_area=areas[best], bbox_area=bbox_area,
            area_ratio=round(areas[best] / bbox_area, 4) if bbox_area else 0.0,
            model_name=self.name, checkpoint=self.checkpoint)


#: Types whose geometry has legs, gaps and open volume, so a bounding box encloses
#: a great deal of whatever is behind them. Taken from the Phase 2 failure list
#: plus the obvious siblings, and fixed before any Phase 3 result was seen.
OPEN_STRUCTURE_TYPES = {
    "chair", "bar_stool", "stool", "armchair", "ottoman", "bench",
    "dining_table", "coffee_table", "side_table", "console", "desk",
}


def is_open_structure(object_type: str) -> bool:
    return (object_type or "").strip().lower() in OPEN_STRUCTURE_TYPES


__all__ = ["Sam2Grounder", "SegmentationResult", "DEFAULT_CHECKPOINT",
           "OPEN_STRUCTURE_TYPES", "is_open_structure", "WIDTH", "HEIGHT"]
