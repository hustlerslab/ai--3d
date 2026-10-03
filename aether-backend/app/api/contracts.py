"""P1-FRONTEND-003: one declared response model per route.

The envelope is unchanged (`envelope.py`): reads are `{success, data}`, most
writes are a flat object carrying `success: true`, errors `{success, error}`.
These models describe that exact wire shape - they do not redesign it.

Where a route dumps a domain model (`Scene`, `Job`, `ProjectRecord`, ...) the
contract reuses that model instead of re-declaring it, so there is one
definition of each shape. Where a route passes through a JSON artifact read
from disk (analysis, scene reading, tour package) the payload is genuinely
free-form and is typed `dict[str, Any]` rather than a guess.

Every model here allows extra keys. Runtime must never drop a field a route
returns (FastAPI validates and re-serialises through these); the contract
tests check the other direction - that no route returns a key its model does
not declare.
"""
from __future__ import annotations

from typing import Any, Generic, Literal, Optional, TypeVar

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from ..assets.schema import AssetRecord
from ..catalog.catalog import CatalogItem
from ..jobs.schema import Job, JobEvent
from ..materials.schema import MaterialRecord
from ..projects.schema import InputRecord, ProjectRecord
from ..projects.versions import DesignVersion
from ..provenance import ProvenanceChain
from ..scene.schema import SavedView, Scene
from ..walkthrough.service import PositionCheck, TourPath

T = TypeVar("T")

Obj = dict[str, Any]


class ContractRoute(APIRoute):
    """Every route serialises with `exclude_unset`. Without it, an optional
    field a route did not return comes back as an explicit `null` - measured:
    `/credits` grew `balance: null` and the tour package a dozen null keys the
    moment models were attached, and no existing test noticed. With it, the
    wire shape is exactly what the route returned."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["response_model_exclude_unset"] = True
        super().__init__(*args, **kwargs)


class Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Envelope(Open, Generic[T]):
    """`ok(data)` - every read."""
    success: Literal[True]
    data: T


class Written(Open):
    """A flat write response: `{"success": true, ...}`."""
    success: Literal[True]


# ── auth ─────────────────────────────────────────────────────────────────


class UserOut(Open):
    user_id: str
    email: str
    role: str


class AuthRegistered(Open):
    user: UserOut
    token: str
    expires_in_days: int
    bootstrapped: bool
    claimed: int


class AuthSignedIn(Open):
    user: UserOut
    token: str
    expires_in_days: int


class AuthSignedOut(Open):
    ended: bool


class AuthSignedOutEverywhere(Open):
    revoked: int


class AuthMe(Open):
    user: UserOut


class AuthSession(Open):
    authenticated: bool
    user: Optional[UserOut] = None


# ── service ──────────────────────────────────────────────────────────────


class ServiceRoot(Open):
    service: str
    docs: str
    api: str


class Health(Open):
    status: str
    service: str
    version: str
    runtime: Obj
    providers: Obj
    timestamp: str


class Credits(Open):
    available: bool
    reason: Optional[str] = None
    balance: Optional[Any] = None
    credits_per_piece: Optional[int] = None


# ── scenes ───────────────────────────────────────────────────────────────


class SceneSummary(Open):
    scene_id: str
    name: str
    project_id: Optional[str] = None
    version: int
    rooms: int
    objects: int


class SceneCreated(Written):
    scene: Scene


class SceneWithHistory(Open):
    scene: Scene
    history: Obj


class SceneValidation(Open):
    valid: bool
    violations: list[Obj]


class SceneCommitted(Written):
    scene: Scene
    version: int
    history: Obj


class SceneReverted(Written):
    scene: Scene
    history: Obj


class PatchPreview(Written):
    valid: bool
    violations: list[Obj]


class AssetsUpgraded(SceneCommitted):
    replaced: list[Obj]
    skipped: list[Obj]


class Spawn(Open):
    position: list[float]
    look_at: list[float]


class ViewSaved(Written):
    view: SavedView


class ProposalCreated(Written):
    proposal: Obj
    candidate_scene: Obj
    added: list[Any]
    removed: list[Any]
    violations: list[Obj]


class ProposalRejected(Written):
    proposal_id: str
    status: str


# ── catalog, assets, materials ───────────────────────────────────────────


class AssetWritten(Written):
    asset: AssetRecord


class MaterialWritten(Written):
    material: MaterialRecord


# ── projects ─────────────────────────────────────────────────────────────


class ProjectWritten(Written):
    project: ProjectRecord


class ProjectDetail(Open):
    project: ProjectRecord
    inputs: list[InputRecord]
    jobs: list[Job]
    checkpoints: dict[str, bool]
    outputs: list[Obj]


class ProjectDeleted(Open):
    deleted: str
    kept: Obj


class InputDeleted(Open):
    input_id: str
    kind: str
    file_removed: bool


class InputsAdded(Written):
    project: ProjectRecord
    inputs: list[InputRecord]
    rejected: list[Obj]


class JobAccepted(Written):
    """Every route that enqueues work."""
    job: Job


class ElementsGenerateAccepted(JobAccepted):
    summary: Obj


class ElementImages(Open):
    schema_version: str
    version: int
    definitions: list[Obj]
    instances: list[Obj]
    images: list[Obj]
    provider: str
    warnings: list[str]
    created_at: str


class Analysis(Open):
    analysis: Obj
    style: Optional[Obj] = None
    moodboard: Optional[Obj] = None
    versions: list[Obj]
    provider: Obj


class AnalysisWritten(Written):
    analysis: Obj
    style: Optional[Obj] = None


ElementState = Literal["detected", "validated", "rejected", "unresolved"]


class InventoryCounts(Open):
    """The numbers the review screen prints - counted by the backend from the
    same definitions and instances it sends (P1-FRONTEND-001)."""
    detected_rows: int
    canonical: int
    instances: int
    assets: int
    yours: int
    by_state: dict[str, int]


class Assumption(Open):
    kind: Literal["room_size", "position", "identity"]
    #: Where the screen puts the marker. An anchor, never text for the page.
    ref: str
    statement: str
    change: str


class ReadingSummary(Open):
    """The review summary. Its older keys (approval tallies, cost, inventory,
    definitions, instances) pass through as extras."""
    element_states: dict[str, ElementState]
    counts: InventoryCounts
    assumptions: list[Assumption]


class SceneReadingView(Open):
    reading: Obj
    summary: ReadingSummary


class SceneSpec(Open):
    scene: Obj
    history: Obj
    violations: list[Obj]
    object_plan: Optional[Obj] = None
    asset_plan: Optional[Obj] = None
    spatial_check: Optional[Obj] = None
    design_intent: Optional[Obj] = None
    visual_intent_fidelity: Optional[Obj] = None
    scene_specs: list[Obj]


class ProvenanceCoverage(Open):
    objects: int
    origins: Obj
    terminus: Obj
    traced_to_element: int
    traced_to_scene_element: int
    reached_moodboard: int
    reached_source_image_exact: int
    reached_source_image_via_moodboard: int
    complete: int
    gaps: Obj


class BuildView(Open):
    report: Obj
    manifest_summary: Obj
    files: Obj


class TourPackage(Open):
    """`outputs/web/tour.json` as written by the preview/walkthrough jobs -
    passed through verbatim, so every field is optional here."""
    schema_version: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    scene_id: Optional[str] = None
    scene_version: Optional[int] = None
    quality: Optional[str] = None
    modes: Optional[list[str]] = None
    explore: Optional[Obj] = None
    style: Optional[Obj] = None
    rooms: Optional[list[Obj]] = None
    tour: Optional[Obj] = None
    #: The preview job writes nodes under `tour`; minimal hand-written packages
    #: (the share-link and file-authorization tests) put them at the top level.
    nodes: Optional[list[Obj]] = None
    generated_at: Optional[str] = None


class ShareLinkCreated(Open):
    token_id: str
    url: str
    token: str
    label: str
    expires_in_days: Optional[int] = None
    note: str


class ShareLinks(Open):
    links: list[Obj]


class ShareLinkRevoked(Open):
    revoked: bool


class JobType(Open):
    type: str
    lane: str
    max_attempts: int
    stage_running: Optional[str] = None
    stage_done: Optional[str] = None
    description: str


class JobDetail(Open):
    job: Job
    events: list[JobEvent]


class EventPage(Open):
    events: list[JobEvent]
    last_id: int


class Tradeoffs(Open):
    tradeoffs: list[Obj]


class ReviewItems(Open):
    items: list[Obj]


class ReviewDecided(Open):
    decision: Obj


class RepairRounds(Open):
    rounds: list[Obj]


class Outputs(Open):
    outputs: list[Obj]
    checkpoints: dict[str, bool]


# ── review surface (P1-FRONTEND-002) ─────────────────────────────────────


class ReviewCheck(Open):
    label: str
    outcome: Literal["passed", "failed", "not_checked"]


class ReviewIssue(Open):
    text: str
    #: What the person can do about it, in words.
    next: str


class ReviewRepair(Open):
    attempt: int
    of: int
    text: str


class ReviewRender(Open):
    url: str


class ReviewView(Open):
    """Every string here is a sentence for a person - no check name,
    category, code or internal id (tests/test_review_surface.py scans it)."""
    status: Literal["not_ready", "not_verified", "needs_attention", "verified"]
    status_text: str
    render: Optional[ReviewRender] = None
    checks: list[ReviewCheck]
    issues: list[ReviewIssue]
    repair: Optional[ReviewRepair] = None
    can_decide: bool


# ── design versions (P1-FRONTEND-004) ────────────────────────────────────


class DesignVersions(Open):
    versions: list[DesignVersion]
    #: The live scene matches no saved version.
    unsaved_changes: bool


class DesignVersionSaved(Open):
    version: DesignVersion


class DesignVersionDetail(Open):
    version: DesignVersion
    #: The scene exactly as it was saved.
    snapshot: Obj


class DesignVersionRestored(Open):
    version: DesignVersion
    scene_version: int


#: Routes that stream a file, not JSON. The only routes allowed no model.
BINARY_ROUTES: frozenset[str] = frozenset({
    "/files/projects/{project_id}/{path}",
    "/files/assets/{path}",
    "/files/assets-web/{path}",
    "/files/materials/{path}",
})

__all__ = [n for n in dir() if n[0].isupper() and n not in ("Any", "Literal", "Optional", "Generic", "TypeVar",
                                                          "BaseModel", "ConfigDict")]
