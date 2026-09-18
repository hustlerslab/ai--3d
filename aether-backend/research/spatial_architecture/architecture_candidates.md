# Architecture candidates: the canonical state between perception and solving

**Question.** What should sit between `ObjectGrounding` (Phase 9) and `SceneSpec`
(production)? Do not assume the answer is a converter. Do not assume the
existing `Scene`/`SpatialGraph` are right, or that they are wrong.

**Method.** Read the current production contracts field-by-field (not from
memory), then read six real systems that solve a closely related problem, then
compare three candidate representations against both.

---

## 1. What production already has, read from the code

`app/scene/schema.py` and `app/intelligence/schema.py`, as they exist today —
not as remembered from earlier phases:

```python
class Confidence(BaseModel):
    value: float = 1.0
    source: str = "seed"

class Room(BaseModel):
    boundary: list[Vec2]            # closed polygon, XZ plane, CCW
    floor_height: float = 0.0
    confidence: Confidence = Confidence()
    features: list[str] = []

class SceneObject(BaseModel):
    semantic_type: str
    asset_id: Optional[str]
    position: Vec3                  # bottom-center pivot
    rotation_y: float               # yaw, +Y, radians
    dimensions: Vec3                # (width_x, height_y, depth_z), pre-rotation
    mount: str                      # floor | ceiling | wall | surface
    source: ObjectSource            # catalog | generated | user | seed
    source_strategy: SourceStrategy # local_asset | local_modified | procedural | generated
    confidence: Confidence = Confidence()
    parent_id: Optional[str]        # support relation, if on a surface
    plan_key: Optional[str]

class SpatialRelation(BaseModel):
    subject_id: str
    predicate: SpatialPredicate     # AGAINST, AGAINST_WALL, FACES, NEAR, ...
    object_id: str = ""
    confidence: SpatialConfidence   # LOW | MEDIUM | HIGH  -- categorical, not a float
    source: SpatialSource           # "semantic" | "geometry"
    frame: Literal["floor_plan", "camera"]
    note: str = ""

class SpatialGraph(BaseModel):
    nodes: list[SpatialNode]
    relations: list[SpatialRelation]
    groups: list[SpatialGroup]
    conflicts: list[SpatialConflict]
    unmatched_detections: list[UnmatchedDetection]
    warnings: list[str]
```

This is already: a flat-object-list scene state with per-object and per-room
**provenance-tagged confidence**; a **separate relation graph** with **frame
tagging** (camera vs floor-plan — exactly the camera/world separation §27
asks for) and **categorical confidence with a source field**; and an explicit
**conflict / unmatched-detection / warnings** channel, which is UNKNOWN in
everything but name. None of this was assumed — it is read from the files
listed above and cross-checked against `apply_spatial_graph`, which already
refuses to let a `frame="camera"` relation reach the plan (`spatial_graph.py`,
the camera-frame skip block).

## 2. Six systems read for this decision

| System | Venue | What it actually is, for this problem |
|---|---|---|
| **Survey on Compositional 3D Indoor Scene Generation** (Tam, Pun, Wang, Sun, Wu, Lee, Chang) | *Computer Graphics Forum* 2026, [doi.org/10.1111/cgf.70591](https://onlinelibrary.wiley.com/doi/full/10.1111/cgf.70591) | The field's own blueprint: **conditioning → representation → prior knowledge → layout generation → placement & refinement → asset selection → architecture modelling**. Every system below is an instance of this pipeline. |
| **Holodeck** (Yang et al.) | CVPR 2024, [arXiv:2312.09067](https://arxiv.org/abs/2312.09067) | LLM proposes **soft relational constraints between objects** (not coordinates); a DFS or MILP solver finds a layout that satisfies them, with collision and room-bounds enforced as **hard** constraints. Floor/wall, openings, object selection and layout are four separate modules. |
| **RoomCraft** | 2026, [arXiv:2506.22291](https://arxiv.org/html/2506.22291) | The closest analogue to Allure's photo path: takes real images/sketches/text to a 3D scene. Representation `O = ⟨R, V, E⟩` (room type, object list, relation set). Constraints are an explicit 5-tuple `C = (T, O, P, R, W)` — type, objects, params, relationship, **weight** — split into **essential** (hard) and **flexible** (soft, can relax). Placement order is a heuristic DFS that places the most-constrained object first; a **Conflict-Aware Positioning Strategy** re-weights a `distance-to-wall` / `distance-to-neighbours` objective as collisions are found. Repair is VLM/geometry violation detection feeding an LLM that proposes an adjustment — the paper states plainly there is **no backtracking or re-solve**, only in-place reweighting. |
| **HSM** (Pun, Tam, Wang, Huo, Chang, Savva) | 3DV 2026, [arXiv:2503.16848](https://arxiv.org/abs/2503.16848) | Scenes are hierarchical **by support surface**, not by an abstract N-level ontology: floor → furniture → tabletop/shelf → small object, with an explicit *valid support region* computed at each level before objects are dropped onto it. |
| **DirectLayout** | NeurIPS 2025, [arXiv:2506.05341](https://arxiv.org/abs/2506.05341) | The counter-example: an LLM emits **numerical** layout directly (BEV → 3D lift → refine). Its own failure mode, named in the paper, is **asset-layout mismatch** — the retrieved asset's real footprint disagreeing with what the LLM imagined — patched with an extra "Iterative Asset-Layout Alignment" stage. This is independent confirmation of a failure Allure already measured directly: the `tv_unit` case in Phase 7, where the annotated object (a TV panel) and the catalogue asset (a cabinet) disagreed. |
| **Open-Vocabulary Functional 3D Scene Graphs** (Zhang et al.) | CVPR 2025, [arXiv:2503.19199](https://arxiv.org/abs/2503.19199) | Scene graphs with **functional** edges (afford/operate), not just spatial ones, for QA and manipulation. Relevant to a future affordance layer; not to placement. |
| **Open-Vocabulary Octree-Graph** (Wang et al.) | ICCV 2025, [arXiv:2411.16253](https://arxiv.org/abs/2411.16253) | An occupancy+graph hybrid for building-scale navigation and retrieval on scanned point clouds. Solves a storage/query problem at a scale (whole buildings, path planning) Allure does not have. |

**What is conspicuously absent from every system that actually places
furniture** (Holodeck, RoomCraft, HSM): a monolithic `WorldModel`, an SE(3)
transform stack, an octree, or a generic N-level `WORLD → BUILDING → ROOM →
ZONE → ANCHOR → OBJECT → SURFACE → SUBOBJECT` ontology. The octree/graph
papers that do use heavy geometric representations (Octree-Graph) are solving
a different problem (embodied navigation over a whole scanned building) at a
different scale. Building one for a photo of one room, to place a handful of
objects, would be modelling something the literature does not model at this
scale either.

## 3. The three candidates

### Candidate A — extend `Scene` / `SpatialGraph`

Keep the flat object list, `Room`, `Wall`, `Confidence`, `SpatialRelation`
exactly as they are. Add exactly two new pieces:

1. A **grounding contract** (`GroundingHypothesis`) that is the FACT/HYPOTHESIS
   layer perception hands to the bridge — this already exists, close to
   verbatim, as Phase 9's `ObjectGrounding`.
2. A **bridge function** that turns a set of `GroundingHypothesis` plus the
   reconstructed room geometry into a `Scene` (objects with real confidence,
   `source_strategy` set from the asset's provenance) and a `SpatialGraph`
   fragment (`AGAINST_WALL`, `SUPPORTED_BY` relations, `frame="floor_plan"`,
   `source="geometry"`), using **only** the relation predicates the pipeline
   actually produces evidence for.

### Candidate B — a new `SpatialScene` object

A single new top-level class holding room geometry, objects-with-hypotheses,
relations and constraints together, replacing `Scene` for the photo path and
converted to `SceneSpec` only at the very end.

### Candidate C — graph + geometric state

A general property graph (nodes = room/zone/object/surface, edges = any
relation/constraint), with geometry stored as attached payloads, closer to
Octree-Graph or a generic scene-graph library.

## 4. Comparison

| | A — extend `Scene`/`SpatialGraph` | B — new `SpatialScene` | C — graph + geometric state |
|---|---|---|---|
| Matches what the read literature actually builds (RoomCraft's `⟨R,V,E⟩`, Holodeck's four modules) | **Yes**, closely — RoomCraft's `V` is `SceneObject`, its `E` is `SpatialRelation` | Partially — no studied system uses one fused object for this | No — the graph-heavy systems solve navigation/retrieval at building scale, not room-scale placement |
| Determinism | Unchanged — same Pydantic models, same validators | New model, new validators to prove deterministic | Graph traversal order must be pinned; new surface for nondeterminism |
| Serialization / §39 (versioned, stable IDs) | **Already true today** — `Scene.spec_version`, `new_id()` | Needs a new schema version from scratch | Needs a new schema *and* a graph serialization format |
| Coordinate frames (§10) | **Already solved** — `SpatialRelation.frame` exists and is already enforced at the plan boundary (`apply_spatial_graph` drops `frame="camera"` relations) | Would have to re-invent this | Would have to re-invent this, per-edge |
| Provenance (§12) | **Already present** — `Confidence.source`, `SpatialRelation.source`, `ObjectSource` | New fields, new places for a call site to forget to set them | Same risk, spread across edge attributes |
| Solver compatibility | **Zero adapter cost** — `place_objects`/`validate_scene` already consume exactly this | Requires a `SpatialScene → SceneSpec` compiler before the solver can run at all | Same, plus a graph-to-flat-list compiler |
| Validation compatibility | `validate_scene` already runs on it | New | New |
| Blender compatibility | `build_manifest` already runs on it | New converter | New converter |
| Repair compatibility | Local repair can read/write objects and relations directly | Repair must know two representations | Repair must know the graph AND the flat form |
| Engineering cost to reach parity with A | — | A full second schema, a compiler, and re-proving every one of the above properties that A already has | Larger still: general graph infrastructure plus the same compiler |
| Risk introduced to the 367-test production baseline | **None** — additive only | New model surface entirely untested against the 12-scene/48-case benchmarks | Same, larger |

## 5. Decision

**Candidate A.** Every real system studied that actually places furniture
(Holodeck, RoomCraft, HSM) converges on the same shape production already has:
a structured object list, a separate relation set, hard/soft constraints, and
an ordered placement search — not a monolithic world model. RoomCraft, the
system doing the most similar job (real photo → 3D scene), maps field-for-field
onto `SceneObject`/`SpatialRelation` already. Candidates B and C would rebuild,
at real engineering cost and real risk to the frozen 367-test baseline,
properties (serialization, frame safety, provenance, solver/Blender/validator
compatibility) that Candidate A already has and that this session did not need
to invent.

The one genuine gap — an explicit, typed home for the FACT/HYPOTHESIS layer
between perception and the object list — is filled by finishing what Phase 9
started, not by a new top-level scene type. See `architecture_decision.md` for
the exact scope, and for what was explicitly considered and rejected (a
7-channel numeric confidence, a general `ConstraintGraph` with MILP solving, an
N-level hierarchy, and most of the relation vocabulary listed in the brief) —
in each case because no system studied does it at this scale, or because
nothing in the measured pipeline produces the evidence such a feature would
need.
