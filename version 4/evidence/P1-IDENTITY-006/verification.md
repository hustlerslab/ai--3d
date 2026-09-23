# P1-IDENTITY-006 — Golden identity benchmark · verification

**Completed:** 2026-09-22 · **Hat:** AI Evaluation Engineer (+ QA) · **Branch:** `ai-3d` on `02ca264` (dirty)

## Deliverables

| Deliverable | Where |
|---|---|
| Harness | `aether-backend/research/p1_identity_benchmark.py` — runs the **shipped** `resolve_elements()` (after `mark_duplicates()`, as production does) over a hand-labelled set; counts generations by the **production spend rule** (`approved_for_generation` → `distinct_shapes` → `storage_key`/mesh-on-disk), not by "number of keys" |
| Benchmark JSON | `docs/benchmarks/p1_identity_benchmark.json` (`git_sha 02ca264`, `captured_at` UTC) |
| Pinning tests | `aether-backend/tests/test_p1_identity_benchmark.py` — 6 tests, same functions as the harness so the two cannot disagree |

## Labelled set (N states itself)

| Case | Rows | Trustworthy | Definitions | Truth | Instances | FM | FS | Count acc. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `golden_living_room_01` (§29.1) | 17 | 17 | **11** | 11 | **17** | 0 | 0 | 1.000 |
| `acceptance_one_rejected_stool_is_excluded` | 3 | 2 | 1 | 1 | 2 | 0 | 0 | 1.000 |
| `acceptance_two_dark_one_light_stool` | 3 | 3 | **2** | 2 | 3 | 0 | 0 | 1.000 |
| `acceptance_television_vs_tv_unit` | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 1.000 |
| `ablation_real_project` (proj_553cb09794, labelled by eye) | 26 | 15 | 13 | 13 | 15 | 0 | 0 | 1.000 |
| `ablation_golden_three_stools` | 3 | 3 | 1 | 1 | 3 | 0 | 0 | 1.000 |
| `ablation_golden_chairs_different_upholstery` | 3 | 1 | 1 | 1 | 1 | 0 | 0 | 1.000 |
| `ablation_golden_two_beds_two_rooms` | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 1.000 |
| `ablation_golden_no_evidence_pair` | 2 | 1 | 1 | 1 | 1 | 0 | 0 | 1.000 |
| `ablation_golden_six_matching_chairs` | 6 | 6 | 1 | 1 | 6 | 0 | 0 | 1.000 |

*Rows excluded as untrustworthy (`check != ok` and no human approval) are reported, never scored as errors — a row a check removed is not evidence of a piece. The ablation's synthetic cases carry no `bbox` spread, so `mark_duplicates()` collapses overlapping same-type boxes exactly as production would; that is why three "different upholstery" chairs count 1 trustworthy row here. The golden and acceptance cases spread their boxes and are read in full.*

## Measured figures

```
TOTAL over 10 cases, N=52 trustworthy rows (37 synthetic + 15 real):
  false-merge rate        0.0   (0 / 35 definitions)
  false-split rate        0.0   (0 / 35 labelled pieces)
  instance-count accuracy 1.0   (33 / 33 (room,type) cells)
golden: 11 definitions, 17 instances, 10 generations (tv_unit reused: 0 spend),
        asset reuse rate 0.4118, 1.7 instances per generation
```

## Acceptance criteria

| Criterion | Result |
|---|---|
| 3 identical stools → exactly 1 generation | ✅ `distinct_shapes` group of 3 → 1 |
| 2 identical chairs → exactly 1 generation | ✅ group of 2 → 1 |
| 2 side tables remain 2 definitions (no false merge) | ✅ |
| 2 dark + 1 light stool → 2 definitions (no merge, no split) | ✅ |
| `television` ≠ `tv_unit` | ✅ |
| 17 instances | ✅ |
| Every figure states N | ✅ per case and in totals |
| "10 definitions · ≤9 generations" | ⚠️ **spec-internal contradiction — correction C10.** With the side-table row required to stay 2 definitions, 10 element rows are **11 definitions**, and with the TV unit owned (0 spend) that is **10 generations**. The no-false-merge rule governs; measured 11 / 17 / 10 |

## Mutation tests — the benchmark must see a broken resolver (source restored, verified)

| Mutation in `app/intelligence/scene_reading.py` | Result |
|---|---|
| M1 colour dropped from the canonical key | **CAUGHT** — 2 failed (side tables + dark/light stools merge) |
| M2 group by the old position key (`shape_key`) | **CAUGHT** — 4 failed (stools, chairs, cushions split) |
| M3 untrustworthy rows admitted | **CAUGHT** — 2 failed (first version survived; pinned by the added `one_rejected_stool` case) |

## Regression (efficient strategy: no production code changed; neighbours + new files)

```
pytest tests/test_p1_identity_benchmark.py tests/test_p18_canonical_identity.py \
       tests/test_element_identity.py tests/test_manifest_identity.py tests/test_provenance.py
64 passed (7.45s)   → 6 in the new file after the exclusion case was added
```
The full suite ran 30 minutes earlier at 1209 passed · 0 failed; the two files added since are the ones above.

## Notes for the record

- CI has no `data/projects`; the harness drops the real-project case when the file is absent and says so in `absent_cases`, and the test asserts that path. Synthetic N alone is 37.
- Client-owned pieces have no first-class control yet (P1-ELEM-004); the harness represents "TV unit already owned" by the only production mechanism that exists — a mesh present under the group's storage key — which is what the spend loop checks.
- Measured on the shipped resolver with **no model in the loop**; these are identity-resolution figures, not reading-quality figures. Reading quality (does the model see 3 stools?) is a different measurement and is not claimed here.
