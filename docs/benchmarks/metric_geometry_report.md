Phase 2 complete. M list unchanged from session start; torch untouched; planes.py still has zero production importers.

PHASE 2 RESULT
The geometry is fixed. The failure has moved.
A. Executed: MoGe-2 Ruicheng/moge-2-vitl, all arms + Depth Anything control re-run in the same harness.
B. Blocked: UniDepthV2 — two independent reasons: CC BY-NC 4.0 forbids commercial use (disqualifying on its own for a commercial product), and it needs Linux + compiled CUDA ops on a Windows host. Not run, not estimated.
C. Licence: MoGe-2 is MIT for both code and checkpoint — commercial use permitted, verified on the repo and HF card.

D–F. 2636 MiB peak · 0.707 s warm · 704×448 dense point map + depth + predicted intrinsics · metric in metres · bit-deterministic (max diff 0.0) · FoV 58.67° predicted vs 60° guessed.

G–J. Geometry diagnostics — every one moved as predicted
Phase 1	Phase 2
Manhattan median	17.73°	3.67°
>20° fraction	0.44	0.214
Zero-wall images	5/21	0/21
Usable walls	43	64
Median extent	1.7×0.8×2.8 (arbitrary)	4.5×2.4×4.1 m
The 5.2× scale spread is not instability — those are metres now, and a 4 m bathroom vs a 21 m lounge is correct.

K–M. Wall contact
false-wall 24.3% [13.4, 40.1] (was 61.5%) · NO-recall 75.7% · UNKNOWN 0% (was 29.7%) · AUC 0.717 (was 0.551).

The sign is repaired: positives now measure 0.097 m from the wall, negatives 0.640 m. Phase 1 had them inverted.

N. Historical negatives 5/5 correct (was 1/5 with four UNKNOWNs). O. Cat A 21.1% vs B 27.8% — overlapping, consistent with 1h.

Arm B (camera up-axis hint) produced identical decisions — a clean negative result proving floor fitting was never the bottleneck.

Q. Root cause — decision-tree case A
Geometry improved, scale improved, wall contact still poor → object grounding. All nine false walls are open-structure furniture at 0.009–0.080 m: bar stools, chairs, armchairs, an ottoman. A chair's bounding box contains the wall between its legs. The object isn't near the wall; the box is. No threshold rescues it — best balanced accuracy 74.7%, false-wall never below 18.9%.

R. FAIL by the gate — three of four conditions met
false-wall 24.3% ✗ (>20%) · Manhattan improved ✓ · wall coverage ✓ · UNKNOWN 0% ✓. Not integrated.

I'm not calling this a pass. But the hypothesis under test — does metric geometry repair the geometric representation — is answered yes, decisively.

S. Next phase
Swap the bounding box for a segmentation mask; re-run the identical benchmark. SAM 2 is Apache-2.0 and transformers already supports it. Prediction stated in advance so it can be wrong: those nine false walls should move from ~0.01–0.08 m out to tens of centimetres. If they persist with masks, the fault is the 10th-percentile rear-surface heuristic instead.

Ablations C/D not run — no room dimensions and no floor plan exists in the repo (find data -iname '*floorplan*' → nothing).

Dependencies added (all --no-deps, torch verified unchanged): moge 3.0.0, utils3d_moge 1.7, opencv-python-headless, scipy. Test baseline 355/7/30 before and after.

STOP. metric_geometry_report.md · metric_geometry_benchmark.md