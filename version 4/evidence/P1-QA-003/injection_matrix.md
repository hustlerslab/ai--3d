| # | Status | Detection | Category | Response | User experience |
|---|---|---|---|---|---|
| 1 | PASS | Watcher element_id_discontinuity (rule); inventory counted 3 usable | perception_failure | RE_READ (scene_plan force_read, repair round 1) | We re-checked your room |
| 2 | PASS | mark_duplicates marked one row 'duplicate' | - | CONTINUE | Marked duplicate, not deleted |
| 3 | PASS | no merge: resolve_elements | - | CONTINUE | 3 instances survive |
| 4 | PASS | shape gate: the generated mesh is 1.20 x 1.27 x 1.00 m, flatness 1.06 against a li | asset_failure | REGENERATE | Labelled stand-in if unresolved (Rebuilding a piece that didn't come out right) |
| 5 | NOT PASSING | Blender validator ±25% | asset_failure | REGENERATE | Flagged in verification |
| 6 | PASS | validate_scene (check_scene): 2 hard violation(s) in the committed scene v2 | solver_failure | RE_SOLVE -> Repair Engine (repair_scene round 1, repaired) | Correcting the layout — 1 of 2 |
| 7 | PASS | door_clearance_rects -> BLOCKS_DOOR | solver_failure | RE_SOLVE -> Repair Engine | The fridge is in the way of a door in the kitchen. (+ options) |
| 8 | PASS | check_scene object-count check: obj_84c1b059c0 missing | validation_failure | HUMAN_REVIEW (review item opened) | One thing to look at |
| 9 | PASS | poll exceeded its wait (MeshyError ... after 900s) | asset_failure | REGENERATE (re-runs generate_elements, which POLLS the kept task - a bounded retry, 0 credits) | Taking longer than usual |
| 10 | PASS | schema/JSON validation at the provider (layer 1) | perception_failure | job failed after its retries; nothing downstream ran | No consumer receives it |
| 11 | PASS | non-zero exit (BlenderError) | blender_execution_failure | RETRY (runner retry, then FAILED after max attempts) | Retrying |
| 12 | NOT PASSING | render verifier | validation_failure | HUMAN_REVIEW | Plain description of the mismatch |
| 13 | PASS | conflict: model FAIL on geometry vs clean deterministic verdicts | validation_failure | HUMAN_REVIEW | Escalated with both verdicts |
| 14 | PASS | Watcher latency_outlier (statistic); no failing verdict | - | CONTINUE | Pipeline not disrupted |
| 15 | PASS | runner repair counter | - | forced escalation after the cap | Halts at round 2 |
| 16 | PASS | delimited-data guard; agent memory is data | SECURITY | Reject | No decision changed |
| 17 | PASS | auth dependency | SECURITY | Reject | 401 / 403, zero spend |
| 18 | PASS | restart recovery (runner.start) | - | resume from checkpoint | resumed event · no duplicate spend |
