"use client";

/**
 * Walkthrough Studio — the homeowner journey, now wired to the local pipeline:
 *
 *   Create Project → Upload & Describe → Generate Moodboard (FREE, analyze job)
 *   → Review & Refine (corrections, then confirm which read pieces get built)
 *   → Plan 3D Space (FREE: the confirmed pieces become meshes and are placed)
 *   → Generate 3D Space (PAID: build + preview jobs on the render lane)
 *   → View 3D Experience (Explore in 3D · 360° Tour)
 *   → Save / Share (public /w/{projectId} link) → Connect with Designer (mock)
 *
 * Every long step is a backend job polled by useJob; the project id is kept
 * in sessionStorage so a reload resumes at the furthest completed stage.
 */

import {
  ArrowLeft,
  ArrowRight,
  Box,
  Check,
  Film,
  ImagePlus,
  Link2,
  Loader2,
  Lock,
  RefreshCw,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { StatusPill } from "@/components/shared/status-pill";
import { DESIGNERS } from "@/lib/mock/designers";

import * as api from "@/features/studio/api/projects-api";
import { AnalysisReview } from "@/features/studio/components/analysis-review";
import { ElementReview } from "@/features/studio/components/element-review";
import type { CreditsDto, SceneReadingDto } from "@/features/studio/types";
import { JobProgress } from "@/features/studio/components/job-progress";
import { ProjectHistory } from "@/features/studio/components/project-history";
import { useJob } from "@/features/studio/hooks/use-job";
import { ProjectsApiError, type AnalysisDto, type AnalysisPatch, type ProjectDetail, type ProjectRecord, type RoomHint, type Vertical } from "@/features/studio/types";
import {
  coerceRoomType,
  defaultRoomType,
  DEFAULT_VERTICAL,
  isVerticalLocked,
  roomTypeLabel,
  roomTypeOptions,
  VERTICAL_OPTIONS,
} from "@/features/studio/verticals";
import { getTour } from "@/features/tour/api/tour-api";
import { PanoramaTour } from "@/features/tour/components/panorama-tour";
import { FilmPlayer } from "@/features/tour/components/share-view";
import type { TourPackage } from "@/features/tour/types";
import { Walkthrough3DView } from "@/features/walkthrough3d/components/walkthrough3d-view";

/* ── Steps ─────────────────────────────────────────────────────────────── */

type StepId =
  | "project" | "describe" | "moodboard" | "refine" | "planspace"
  | "generate3d" | "experience" | "share" | "designer";

interface StepDef {
  id: StepId;
  title: string;
  badge: "free" | "paid" | null;
}

const STEPS: StepDef[] = [
  { id: "project", title: "Create Project", badge: null },
  { id: "describe", title: "Upload & Describe", badge: null },
  { id: "moodboard", title: "Generate Moodboard", badge: "free" },
  { id: "refine", title: "Review & Refine", badge: null },
  // Confirming what gets built and seeing it in 3D are two different jobs, and
  // they were sharing one screen. Step 4 is now purely the decision — crops and
  // labels, Build or Skip — and step 5 is the room that decision produced.
  { id: "planspace", title: "Plan 3D Space", badge: null },
  { id: "generate3d", title: "Generate 3D Space", badge: "paid" },
  { id: "experience", title: "View 3D Experience", badge: null },
  { id: "share", title: "Save / Share", badge: null },
  { id: "designer", title: "Connect with Designer", badge: "free" },
];

const STEP_INDEX: Record<StepId, number> = Object.fromEntries(STEPS.map((s, i) => [s.id, i])) as Record<StepId, number>;
const STORAGE_KEY = "allure.studio.project";
/** Mirrors MAX_REFERENCES in aether-backend app/api/projects_routes.py. Used
 *  only to explain the cap before the server enforces it. */
const MAX_REFERENCES = 12;

interface StagedPhoto {
  id: string;
  file: File;
  previewUrl: string;
  name: string;
}

interface RoomRow {
  key: string;
  name: string;
  type: string;
  width: string;
  length: string;
}

const room = (key: string, name: string, type: string): RoomRow => ({ key, name, type, width: "", length: "" });

/** What each space IS, structurally — not a hint about it.
 *
 *  A 2BHK has two bedrooms, a living room, a kitchen and a bathroom whether or
 *  not the client thought to mention them in the brief; the brief then says
 *  what each room is for. These used to be `rooms: []` with the choice passed
 *  only as the sentence "Space: 2BHK apartment.", which left the room list
 *  entirely to the reading — so the same project came back with a bathroom one
 *  run and without it the next. */
const SPACE_PRESETS: Record<string, { hint: string; rooms: RoomRow[] }> = {
  "Full 2BHK": {
    hint: "2BHK apartment",
    rooms: [
      room("l", "Living Room", "living_room"),
      room("b1", "Master Bedroom", "master_bedroom"),
      room("b2", "Second Bedroom", "bedroom"),
      room("k", "Kitchen", "kitchen"),
      room("ba", "Bathroom", "bathroom"),
    ],
  },
  "Full 3BHK": {
    hint: "3BHK apartment",
    rooms: [
      room("l", "Living Room", "living_room"),
      room("b1", "Master Bedroom", "master_bedroom"),
      room("b2", "Second Bedroom", "bedroom"),
      room("b3", "Third Bedroom", "bedroom"),
      room("k", "Kitchen", "kitchen"),
      room("ba", "Bathroom", "bathroom"),
    ],
  },
  "Living room + bedroom": {
    hint: "living room and one bedroom",
    rooms: [room("l", "Living Room", "living_room"), room("b", "Bedroom", "bedroom")],
  },
  "Living room": { hint: "living room only", rooms: [room("l", "Living Room", "living_room")] },
  "Bedroom": { hint: "one bedroom", rooms: [room("b", "Bedroom", "bedroom")] },
};

/** Furthest wizard step a project's backend stage justifies. */
function stepForStage(stage: ProjectRecord["stage"], hasTour: boolean): StepId {
  switch (stage) {
    case "CREATED":
      return "describe";
    case "INPUT_RECEIVED":
    case "ANALYZING":
      return "moodboard";
    case "DESIGN_SPEC_READY":
    case "ASSET_PLANNING":
      return "refine";
    // The plan exists but nothing has been rendered: that is the Plan step,
    // not the paid one. Resuming straight to "Generate 3D Space" used to skip
    // the room the client is meant to look at before paying for it.
    case "ASSETS_READY":
      return "planspace";
    case "SCENE_BUILDING":
    case "SCENE_VALIDATING":
    case "CAMERA_PLANNING":
      return "generate3d";
    case "PREVIEW_RENDERING":
    case "FINAL_RENDERING":
    case "COMPLETED":
      return hasTour ? "experience" : "generate3d";
    default:
      return "refine";
  }
}

export function WalkthroughStudio() {
  const [stepIndex, setStepIndex] = useState(0);
  const [maxReached, setMaxReached] = useState(0);

  // Step 1 — project
  const [projectName, setProjectName] = useState("");
  const [spaceType, setSpaceType] = useState("Full 2BHK");
  const [vertical, setVertical] = useState<Vertical>(DEFAULT_VERTICAL);
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const [engineError, setEngineError] = useState<EngineErrorState | null>(null);

  // Step 2 — upload & describe
  const [photos, setPhotos] = useState<StagedPhoto[]>([]);
  const [vision, setVision] = useState("");
  const [roomRows, setRoomRows] = useState<RoomRow[]>(SPACE_PRESETS["Full 2BHK"].rooms);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [removingInputId, setRemovingInputId] = useState<string | null>(null);
  const photosRef = useRef<StagedPhoto[]>([]);
  photosRef.current = photos;

  // Step 3/4 — analysis + scene plan
  const analyzeJob = useJob();
  const [analysis, setAnalysis] = useState<AnalysisDto | null>(null);
  const [savingAnalysis, setSavingAnalysis] = useState(false);
  // Redrawing one room: a different seed, same brief and style (ADR-002 §1).
  const repaintJob = useJob();
  const [repaintingRoom, setRepaintingRoom] = useState<string | null>(null);
  const [analysisEditedSincePlan, setAnalysisEditedSincePlan] = useState(false);
  const planJob = useJob();
  // The crops read out of the approved rooms, awaiting a human yes/no.
  // Loaded after a plan succeeds, because that is the job that writes them.
  const [sceneReading, setSceneReading] = useState<SceneReadingDto | null>(null);
  const [savingReview, setSavingReview] = useState(false);
  // The paid step: approved crops become meshes. The balance is shown beside
  // the button that spends it, so the cost is never a surprise after the fact.
  const elementsJob = useJob();
  const [credits, setCredits] = useState<CreditsDto | null>(null);
  const [sceneId, setSceneId] = useState<string | null>(null);

  // Step 5/6 — render lane
  const buildJob = useJob();
  const previewJob = useJob();
  const finalJob = useJob();
  const [buildPreviewUrl, setBuildPreviewUrl] = useState<string | null>(null);
  const [tour, setTour] = useState<TourPackage | null>(null);
  const [experienceMode, setExperienceMode] = useState<"explore" | "tour" | "film">("tour");
  const filmJob = useJob();

  // Step 8 — designer
  const [connectedDesigner, setConnectedDesigner] = useState<string | null>(null);

  useEffect(
    () => () => {
      for (const photo of photosRef.current) URL.revokeObjectURL(photo.previewUrl);
    },
    [],
  );

  const step = STEPS[stepIndex];

  const goTo = useCallback((index: number) => {
    setStepIndex(index);
    setMaxReached((m) => Math.max(m, index));
  }, []);
  const goToStep = useCallback((id: StepId) => goTo(STEP_INDEX[id]), [goTo]);
  const next = useCallback(() => goTo(Math.min(stepIndex + 1, STEPS.length - 1)), [goTo, stepIndex]);
  const back = useCallback(() => setStepIndex((i) => Math.max(0, i - 1)), []);

  /** Has the client actually confirmed anything to build?
   *
   *  This is what opens the Plan step. Approval is the whole gate — a piece
   *  nobody ticked is not built (ADR-003 §5) — so moving on before any
   *  decision exists would land on an empty room and read as a broken step. */
  const confirmedAnything = (sceneReading?.summary.approved ?? 0) > 0;


  /* ── Resume a project after a reload ──────────────────────────────── */

  const refreshDetail = useCallback(async (projectId: string) => {
    const d = await api.getProject(projectId);
    setDetail(d);
    setProject(d.project);
    return d;
  }, []);

  /**
   * Load a project and jump to the furthest stage it reached. Used by both the
   * session resume below and the project history, so opening an older project
   * behaves exactly like reloading the tab on it. Every field is set
   * unconditionally — switching projects must not leave the previous one's
   * analysis or preview on screen.
   */
  const openProject = useCallback(
    async (projectId: string) => {
      const d = await refreshDetail(projectId);
      setProjectName(d.project.name);
      setVision(d.project.description);
      setVertical(d.project.vertical);
      setUploadedCount(d.inputs.filter((i) => i.kind === "reference").length);
      setSceneId(d.project.scene_ids.length ? d.project.scene_ids[d.project.scene_ids.length - 1] : null);
      setAnalysis(d.checkpoints.analysis ? await api.getAnalysis(projectId).catch(() => null) : null);

      let previewUrl: string | null = null;
      if (d.checkpoints.scene_blend) {
        const b = await api.getBuild(projectId).catch(() => null);
        previewUrl = b?.files.preview ?? null;
      }
      setBuildPreviewUrl(previewUrl);

      let pkg: TourPackage | null = null;
      if (d.checkpoints.preview || d.checkpoints.outputs) pkg = await getTour(projectId).catch(() => null);
      setTour(pkg);

      // Unconditional like every field above it: a project without crops to
      // review must clear the previous project's, or the reviewer would be
      // ticking someone else's furniture.
      setSceneReading(
        d.checkpoints.scene_reading ? await api.getSceneReading(projectId).catch(() => null) : null,
      );

      try {
        window.sessionStorage.setItem(STORAGE_KEY, projectId);
      } catch {
        /* ignore */
      }
      goToStep(stepForStage(d.project.stage, Boolean(pkg)));
    },
    [refreshDetail, goToStep],
  );

  /** Open a project chosen from the history, surfacing a failure rather than
   *  silently doing nothing. */
  const openFromHistory = useCallback(
    (projectId: string) => {
      setEngineError(null);
      void openProject(projectId).catch((e) =>
        setEngineError(toEngineError(e)),
      );
    },
    [openProject],
  );

  /** Reference photos already on the server, as opposed to `photos`, which are
   *  staged in the browser and not uploaded yet. */
  const existingPhotos = (detail?.inputs ?? []).filter((i) => i.kind === "reference");

  /** Delete one uploaded photo, then re-read the project so the grid and the
   *  count come from the server rather than from optimistic local state. */
  const removeExistingPhoto = useCallback(
    async (inputId: string) => {
      if (!project) return;
      setRemovingInputId(inputId);
      setEngineError(null);
      try {
        await api.deleteInput(project.project_id, inputId);
        const d = await refreshDetail(project.project_id);
        setUploadedCount(d.inputs.filter((i) => i.kind === "reference").length);
      } catch (e) {
        setEngineError(toEngineError(e));
      } finally {
        setRemovingInputId(null);
      }
    },
    [project, refreshDetail],
  );

  /** Clear the workspace back to an empty step 1 without reloading the page, so
   *  the history stays on screen and nothing else is refetched. */
  const startNewProject = useCallback(() => {
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setProject(null);
    setDetail(null);
    setProjectName("");
    setVision("");
    setVertical(DEFAULT_VERTICAL);
    setSpaceType("Full 2BHK");
    setRoomRows(SPACE_PRESETS["Full 2BHK"].rooms);
    setPhotos([]);
    setUploadedCount(0);
    setUploadProgress(0);
    setAnalysis(null);
    setSceneId(null);
    setBuildPreviewUrl(null);
    setTour(null);
    setEngineError(null);
    setMaxReached(0);
    setStepIndex(0);
  }, []);

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.sessionStorage.getItem(STORAGE_KEY);
    } catch {
      stored = null;
    }
    if (!stored) return;
    void openProject(stored).catch(() => {
      try {
        window.sessionStorage.removeItem(STORAGE_KEY);
      } catch {
        /* ignore */
      }
    });
  }, [openProject]);

  const remember = (p: ProjectRecord) => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, p.project_id);
    } catch {
      /* ignore */
    }
  };

  /* ── Step 1: create project ─────────────────────────────────────────── */

  const verticalLocked = isVerticalLocked(project?.stage);

  /** Changing the vertical re-validates the room rows, so an invalid pair can never be submitted. */
  const changeVertical = useCallback((value: Vertical) => {
    setVertical(value);
    setRoomRows((rows) => rows.map((r) => ({ ...r, type: coerceRoomType(value, r.type) })));
  }, []);

  const createProject = useCallback(async () => {
    // Past CREATED nothing on this step is editable any more — walk on rather
    // than quietly starting a second project.
    if (project && verticalLocked) {
      next();
      return;
    }
    setCreating(true);
    setEngineError(null);
    try {
      const preset = SPACE_PRESETS[spaceType];
      const body = { name: projectName.trim(), description: preset?.hint ?? "", vertical };
      const p = project ? await api.updateProject(project.project_id, body) : await api.createProject(body);
      setProject(p);
      remember(p);
      setRoomRows((preset?.rooms ?? []).map((r) => ({ ...r, type: coerceRoomType(vertical, r.type) })));
      next();
    } catch (err) {
      setEngineError(toEngineError(err));
    } finally {
      setCreating(false);
    }
  }, [projectName, spaceType, vertical, project, verticalLocked, next]);

  /* ── Step 2: photos + vision ────────────────────────────────────────── */

  const addFiles = useCallback((files: FileList | null) => {
    if (!files) return;
    const staged: StagedPhoto[] = [];
    for (const file of Array.from(files)) {
      if (!file.type.startsWith("image/")) continue;
      staged.push({ id: `${file.name}-${file.size}-${file.lastModified}`, file, previewUrl: URL.createObjectURL(file), name: file.name });
    }
    setPhotos((prev) => {
      const seen = new Set(prev.map((p) => p.id));
      return [...prev, ...staged.filter((p) => !seen.has(p.id))];
    });
  }, []);

  const removePhoto = useCallback((id: string) => {
    setPhotos((prev) => {
      const photo = prev.find((p) => p.id === id);
      if (photo) URL.revokeObjectURL(photo.previewUrl);
      return prev.filter((p) => p.id !== id);
    });
  }, []);

  const uploadAndContinue = useCallback(async () => {
    if (!project) return;
    setUploading(true);
    setEngineError(null);
    setUploadProgress(0);
    try {
      const preset = SPACE_PRESETS[spaceType];
      const description = [vision.trim(), preset?.hint ? `Space: ${preset.hint}.` : ""].filter(Boolean).join("\n");
      const dimensions: RoomHint[] = roomRows
        .filter((r) => r.name.trim())
        .map((r) => ({
          name: r.name.trim(),
          type: r.type,
          width_m: r.width ? Number(r.width) : null,
          length_m: r.length ? Number(r.length) : null,
          estimated: !(r.width && r.length),
        }));
      const res = await api.uploadInputs(project.project_id, { description, dimensions, files: photos.map((p) => p.file) }, setUploadProgress);
      setProject(res.project);
      setUploadedCount((n) => n + photos.length - res.rejected.length);
      if (res.rejected.length) setEngineError({ code: "PARTIAL_UPLOAD", message: `${res.rejected.length} file(s) were skipped: ${res.rejected.map((r) => `${r.filename} (${r.reason})`).join(", ")}` });
      for (const photo of photos) URL.revokeObjectURL(photo.previewUrl);
      setPhotos([]);
      setAnalysis(null);
      analyzeJob.reset();
      next();
    } catch (err) {
      setEngineError(toEngineError(err));
    } finally {
      setUploading(false);
    }
  }, [project, spaceType, vision, roomRows, photos, next, analyzeJob]);

  /* ── Step 3: analyze ────────────────────────────────────────────────── */

  const runAnalyze = useCallback(
    async (force = false) => {
      if (!project) return;
      const job = await analyzeJob.run(() => api.analyze(project.project_id, force));
      if (job?.status === "SUCCEEDED") {
        setAnalysis(await api.getAnalysis(project.project_id));
        setAnalysisEditedSincePlan(true);
        await refreshDetail(project.project_id);
      }
    },
    [project, analyzeJob, refreshDetail],
  );

  useEffect(() => {
    if (step.id === "moodboard" && project && !analysis && !analyzeJob.running && !analyzeJob.job) {
      void runAnalyze(false);
    }
  }, [step.id, project, analysis, analyzeJob.running, analyzeJob.job, runAnalyze]);

  const repaintRoom = useCallback(
    async (roomId: string) => {
      if (!project) return;
      setRepaintingRoom(roomId);
      try {
        // Poll the job we just started — never read the moodboard on a timer.
        // Reading before the job that writes it has finished is how a previous
        // run's image gets reported as the current one.
        const job = await repaintJob.run(() => api.repaintRoom(project.project_id, roomId));
        if (job?.status === "SUCCEEDED") setAnalysis(await api.getAnalysis(project.project_id));
      } finally {
        setRepaintingRoom(null);
      }
    },
    [project, repaintJob],
  );

  const saveAnalysis = useCallback(
    async (patch: AnalysisPatch) => {
      if (!project) return;
      setSavingAnalysis(true);
      try {
        await api.patchAnalysis(project.project_id, patch);
        setAnalysis(await api.getAnalysis(project.project_id));
        setAnalysisEditedSincePlan(true);
      } finally {
        setSavingAnalysis(false);
      }
    },
    [project],
  );

  /* ── Step 4: scene plan ─────────────────────────────────────────────── */

  const runPlan = useCallback(async () => {
    if (!project) return;
    const force = analysisEditedSincePlan && Boolean(sceneId);
    const job = await planJob.run(() => api.scenePlan(project.project_id, force));
    if (job?.status === "SUCCEEDED") {
      const spec = await api.getSceneSpec(project.project_id);
      setSceneId(spec.scene.scene_id);
      setAnalysisEditedSincePlan(false);
      setBuildPreviewUrl(null);
      setTour(null);
      // Read-back is optional in the pipeline, so a project whose provider
      // cannot do it simply has nothing to review rather than an error.
      try {
        setSceneReading(await api.getSceneReading(project.project_id));
      } catch {
        setSceneReading(null);
      }
      await refreshDetail(project.project_id);
    }
  }, [project, planJob, analysisEditedSincePlan, sceneId, refreshDetail]);

  const saveElementReview = useCallback(
    async (decisions: Record<string, boolean>) => {
      if (!project) return;
      setSavingReview(true);
      try {
        setSceneReading(await api.reviewSceneReading(project.project_id, decisions));
      } finally {
        setSavingReview(false);
      }
    },
    [project],
  );

  /** Never throws into the page: an unreachable vendor shows as "unavailable"
   *  beside the button rather than stopping someone planning a room. */
  const refreshCredits = useCallback(async () => {
    setCredits(await api.getCredits().catch(() => null));
  }, []);

  useEffect(() => {
    void refreshCredits();
  }, [refreshCredits]);

  /** The paid step. Re-reads both the reading and the balance afterwards, so
   *  the cost shown is what the server says was spent rather than what the
   *  client assumed. */
  const runGenerateElements = useCallback(async () => {
    if (!project) return;
    const job = await elementsJob.run(() => api.generateElements(project.project_id));
    if (job?.status === "SUCCEEDED") {
      setSceneReading(await api.getSceneReading(project.project_id).catch(() => null));
      await refreshDetail(project.project_id);
    }
    await refreshCredits();
  }, [project, elementsJob, refreshCredits, refreshDetail]);
  /** Leaving step 4 IS the commitment: build what was confirmed, then show it.
   *
   *  The generation is awaited rather than fired off, so the Plan step is
   *  never entered with meshes still arriving — that was how a room full of
   *  loading placeholders got mistaken for a finished one. Advancing anyway on
   *  failure is deliberate: the plan still stands with catalog pieces, and the
   *  job's own error panel says what went wrong. */
  const confirmAndPlan = useCallback(async () => {
    if (!project) return;
    if ((sceneReading?.summary.to_generate ?? 0) > 0) {
      await runGenerateElements();
    }
    // Re-plan, because the scene was laid out BEFORE those meshes existed and
    // therefore still points at catalog stand-ins. Without this the pieces are
    // generated, paid for, and never appear: a fresh project spent 180 credits
    // on six meshes and the 3D plan showed none of them.
    //
    // Forced, and safe to force: `force` rebuilds the plan only — re-reading
    // the moodboard is `force_read`, kept separate precisely because it would
    // discard the approvals just given.
    const planned = await planJob.run(() => api.scenePlan(project.project_id, true));
    if (planned?.status === "SUCCEEDED") {
      const spec = await api.getSceneSpec(project.project_id).catch(() => null);
      if (spec) setSceneId(spec.scene.scene_id);
      await refreshDetail(project.project_id);
    }
    next();
  }, [project, sceneReading, runGenerateElements, planJob, refreshDetail, next]);

  /* ── Step 5: build + preview panoramas ──────────────────────────────── */

  const runRender = useCallback(async () => {
    if (!project) return;
    const built = await buildJob.run(() => api.build(project.project_id, { preview: true, force: true }));
    if (built?.status !== "SUCCEEDED") return;
    const b = await api.getBuild(project.project_id).catch(() => null);
    if (b?.files.preview) setBuildPreviewUrl(b.files.preview);
    const pv = await previewJob.run(() => api.preview(project.project_id, { force: true }));
    if (pv?.status === "SUCCEEDED") {
      setTour(await getTour(project.project_id));
      await refreshDetail(project.project_id);
      goToStep("experience");
    }
  }, [project, buildJob, previewJob, refreshDetail, goToStep]);

  const runFinal = useCallback(async () => {
    if (!project) return;
    const job = await finalJob.run(() => api.walkthrough(project.project_id, {}));
    if (job?.status === "SUCCEEDED") {
      setTour(await getTour(project.project_id));
      await refreshDetail(project.project_id);
    }
  }, [project, finalJob, refreshDetail]);

  const runFilm = useCallback(async () => {
    if (!project) return;
    const job = await filmJob.run(() => api.film(project.project_id, { profile: "preview" }));
    if (job?.status === "SUCCEEDED") {
      setTour(await getTour(project.project_id));
      setExperienceMode("film");
      await refreshDetail(project.project_id);
    }
  }, [project, filmJob, refreshDetail]);

  const rendering = buildJob.running || previewJob.running;
  const shareUrl = project && typeof window !== "undefined" ? `${window.location.origin}/w/${project.project_id}` : "";

  /* ── Render ──────────────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="overline text-ink-muted">See it before you commit</p>
          <h1 className="display text-3xl text-ink">Walkthrough Studio</h1>
          <p className="body-sm text-ink-muted">
            From an idea to a space you can walk through — moodboard first, 3D when you&apos;re sure.
            {project ? <span className="ml-2 rounded-sm bg-muted px-1.5 py-0.5 caption text-ink-soft">{project.name} · {project.stage.toLowerCase().replace(/_/g, " ")}</span> : null}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/cinematic" className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted transition-colors hover:bg-muted hover:text-ink-soft">
            <Film className="size-3.5" /> Cinematic film studio
          </Link>
          <Link href={sceneId ? `/3d?scene=${sceneId}` : "/3d"} className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted transition-colors hover:bg-muted hover:text-ink-soft">
            <Box className="size-3.5" /> Open 3D viewer
          </Link>
          {project ? (
            <button
              type="button"
              onClick={startNewProject}
              className="rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted"
            >
              New project
            </button>
          ) : null}
        </div>
      </div>

      {/* Stepper rail */}
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
        {STEPS.map((s, i) => {
          const state = i === stepIndex ? "current" : i <= maxReached ? "done" : "todo";
          return (
            <li key={s.id} className="flex items-center gap-1">
              <button
                type="button"
                disabled={i > maxReached}
                onClick={() => setStepIndex(i)}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 caption transition-colors ${
                  state === "current" ? "bg-gold text-ink font-medium" : state === "done" ? "border text-ink-soft hover:bg-muted" : "border text-ink-muted/60"
                }`}
              >
                <span className="tabular">{i + 1}</span>
                {s.title}
                {s.badge === "free" ? <span className="rounded-sm border px-1 text-[10px] uppercase tracking-wide">Free</span> : null}
                {s.badge === "paid" ? (
                  <span className={`rounded-sm px-1 text-[10px] uppercase tracking-wide ${state === "current" ? "bg-ink/15" : "bg-gold text-ink"}`}>Paid</span>
                ) : null}
              </button>
              {i < STEPS.length - 1 ? <span className="text-ink-muted/40" aria-hidden>→</span> : null}
            </li>
          );
        })}
      </ol>

      {/* Step body */}
      <div className="rounded-lg border p-6">
        {step.id === "project" ? (
          <StepShell title="Tell us about your space" subtitle="Basic details to name the project — everything else comes from your photos and vision.">
            <div className="flex max-w-md flex-col gap-4">
              <label className="flex flex-col gap-1.5">
                <span className="body-sm font-medium text-ink-soft">Project name</span>
                <input
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="e.g. Sharma Residence, Kankarbagh"
                  className="rounded-md border bg-transparent px-3 py-2 body-sm text-ink-soft placeholder:text-ink-muted/60 focus:outline-none focus:ring-1 focus:ring-gold"
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="body-sm font-medium text-ink-soft">Space</span>
                <select
                  value={spaceType}
                  onChange={(e) => {
                    // The space defines the rooms, so changing it reloads them.
                    // Without this, picking 3BHK kept the 2BHK room list and the
                    // extra bedroom never reached the backend at all.
                    setSpaceType(e.target.value);
                    setRoomRows(SPACE_PRESETS[e.target.value]?.rooms ?? []);
                  }}
                  className="rounded-md border bg-transparent px-3 py-2 body-sm text-ink-soft focus:outline-none focus:ring-1 focus:ring-gold"
                >
                  {Object.keys(SPACE_PRESETS).map((k) => <option key={k}>{k}</option>)}
                </select>
              </label>
              <VerticalField value={vertical} onChange={changeVertical} locked={verticalLocked} />
              {engineError ? <EngineError error={engineError} /> : null}
            </div>
            <NavRow onNext={() => void createProject()} nextDisabled={!projectName.trim() || creating} nextLabel={creating ? "Creating…" : project ? "Continue" : "Create project"} />

            {/* Everything on this engine, not just this browser session. */}
            <div className="mt-8 border-t pt-6">
              <ProjectHistory
                activeProjectId={project?.project_id ?? null}
                onOpen={openFromHistory}
                onCreateNew={project ? startNewProject : undefined}
                onDeleted={(id) => {
                  // Only if it was the one open: otherwise the Studio would
                  // drop the user's current work because they tidied up an
                  // unrelated project.
                  if (project?.project_id === id) startNewProject();
                }}
              />
            </div>
          </StepShell>
        ) : null}

        {step.id === "describe" ? (
          <StepShell title="Upload photos and describe your vision" subtitle="Room photos, inspiration shots, anything that shows what you have and what you want. Room sizes are optional — the AI estimates what you leave blank.">
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="flex flex-col gap-3">
                <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-ink-muted transition-colors hover:bg-muted">
                  <ImagePlus className="size-6" />
                  <span className="body-sm">Click to add room or inspiration photos</span>
                  <input type="file" accept="image/*" multiple className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
                </label>
                {/* The uploads themselves, not just a count. Without these the
                    12-reference cap is a dead end: files get rejected and the
                    user cannot see what is taking the slots, let alone free one. */}
                {existingPhotos.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    <p className="caption text-ink-muted">
                      {existingPhotos.length} photo{existingPhotos.length > 1 ? "s" : ""} already uploaded
                      {existingPhotos.length >= MAX_REFERENCES ? " — that is the limit; remove one to add another" : ""}.
                    </p>
                    <div className="grid grid-cols-4 gap-2">
                      {existingPhotos.map((input) => (
                        <div key={input.input_id} className="group relative aspect-square overflow-hidden rounded-md border">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={api.fileUrl(`/files/projects/${project?.project_id}/${input.path}`)}
                            alt={input.filename}
                            title={input.filename}
                            className="size-full object-cover"
                          />
                          <button
                            type="button"
                            onClick={() => void removeExistingPhoto(input.input_id)}
                            disabled={removingInputId === input.input_id}
                            aria-label={`Remove ${input.filename}`}
                            className="absolute right-1 top-1 rounded-full bg-ink/70 p-1 text-white opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-50"
                          >
                            <X className="size-3" aria-hidden />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {photos.length > 0 ? (
                  <div className="grid grid-cols-4 gap-2">
                    {photos.map((photo) => (
                      <div key={photo.id} className="group relative aspect-square overflow-hidden rounded-md border">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={photo.previewUrl} alt={photo.name} className="size-full object-cover" />
                        <button type="button" onClick={() => removePhoto(photo.id)} className="absolute right-1 top-1 rounded-full bg-ink/70 p-0.5 text-cream opacity-0 transition-opacity group-hover:opacity-100" aria-label={`Remove ${photo.name}`}>
                          <X className="size-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="flex flex-col gap-4">
                <label className="flex flex-col gap-1.5">
                  <span className="body-sm font-medium text-ink-soft">Your vision</span>
                  <textarea
                    value={vision}
                    onChange={(e) => setVision(e.target.value)}
                    rows={6}
                    placeholder="Warm and calm 2BHK, seating for five, oak floors, keep the TV unit we already have, nothing that shows dust…"
                    className="resize-none rounded-md border bg-transparent px-3 py-2 body-sm text-ink-soft placeholder:text-ink-muted/60 focus:outline-none focus:ring-1 focus:ring-gold"
                  />
                </label>
                <RoomRows rows={roomRows} onChange={setRoomRows} vertical={vertical} />
              </div>
            </div>
            {uploading ? (
              <div className="flex flex-col gap-1">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(uploadProgress * 100)}>
                  <div className="h-full bg-gold transition-[width]" style={{ width: `${Math.round(uploadProgress * 100)}%` }} />
                </div>
                <p className="caption text-ink-muted">Uploading {photos.length} photo{photos.length === 1 ? "" : "s"}… {Math.round(uploadProgress * 100)}%</p>
              </div>
            ) : null}
            {engineError ? <EngineError error={engineError} /> : null}
            <NavRow onBack={back} onNext={() => void uploadAndContinue()} nextDisabled={uploading || (photos.length === 0 && !vision.trim() && uploadedCount === 0)} nextLabel={uploading ? "Uploading…" : "Continue"} />
          </StepShell>
        ) : null}

        {step.id === "moodboard" ? (
          <StepShell title="Your moodboard" subtitle="Allure reads your photos and vision and composes a direction — rooms, palette, materials and light. This step is free; regenerate as often as you like.">
            {analyzeJob.running || (!analysis && analyzeJob.job) ? (
              <JobProgress title="Reading your photos and composing a direction" job={analyzeJob.job} events={analyzeJob.events} error={analyzeJob.error} onRetry={() => void runAnalyze(true)} />
            ) : analysis ? (
              <>
                <AnalysisReview
                  data={analysis}
                  onRepaintRoom={repaintRoom}
                  repaintingRoom={repaintingRoom}
                />
                <button type="button" onClick={() => void runAnalyze(true)} className="flex w-fit items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted">
                  <RefreshCw className="size-3.5" /> Regenerate
                </button>
              </>
            ) : (
              <div className="flex flex-col items-center gap-4 py-10">
                <Sparkles className="size-6 text-gold" />
                <button type="button" onClick={() => void runAnalyze(false)} className="flex items-center gap-2 rounded-md bg-gold px-4 py-2 body-sm font-medium text-ink hover:opacity-90">
                  <Sparkles className="size-4" /> Generate moodboard
                </button>
              </div>
            )}
            <NavRow onBack={back} onNext={next} nextDisabled={!analysis || analyzeJob.running} nextLabel="Looks right — review it" />
          </StepShell>
        ) : null}

        {step.id === "refine" ? (
          <StepShell title="Review and refine" subtitle="Correct room sizes, add must-haves, then plan the space: the layout and furniture appear in 3D within seconds, and you can edit any of it before rendering.">
            {analysis ? (
              <AnalysisReview
                data={analysis}
                onSave={saveAnalysis}
                saving={savingAnalysis}
                onRepaintRoom={repaintRoom}
                repaintingRoom={repaintingRoom}
              />
            ) : null}
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void runPlan()}
                  disabled={!analysis || planJob.running || savingAnalysis}
                  className="flex items-center gap-2 rounded-md bg-gold px-4 py-2 body-sm font-medium text-ink hover:opacity-90 disabled:opacity-40"
                >
                  {planJob.running ? <Loader2 className="size-4 animate-spin" /> : <Box className="size-4" />}
                  {sceneId ? (analysisEditedSincePlan ? "Re-plan the space" : "Plan again") : "Plan the space"}
                </button>
                {sceneId && analysisEditedSincePlan ? <span className="caption text-ink-muted">Your corrections haven&apos;t been applied to the 3D plan yet.</span> : null}
                {/* Planning is free; building the confirmed pieces is not.
                    The balance sits on this step because this is where the
                    spending decision gets made. */}
                {credits ? (
                  <span className="ml-auto flex items-center gap-1.5 rounded-full border px-2.5 py-1 caption text-ink-muted tabular">
                    <Sparkles className="size-3 text-gold" />
                    {credits.available && typeof credits.balance === "number"
                      ? `${credits.balance.toLocaleString()} 3D credits`
                      : "3D credits unavailable"}
                  </span>
                ) : null}
              </div>
              {planJob.job || planJob.error ? (
                <JobProgress title="Planning rooms, furniture and materials" job={planJob.job} events={planJob.events} error={planJob.error} onRetry={() => void runPlan()} compact={Boolean(sceneId) && !planJob.running} />
              ) : null}
              {sceneReading && !planJob.running ? (
                <ElementReview
                  data={sceneReading}
                  onSave={saveElementReview}
                  saving={savingReview}
                  credits={credits}
                  onGenerate={runGenerateElements}
                  generating={elementsJob.running}
                />
              ) : null}
            </div>
            <NavRow
              onBack={back}
              onNext={confirmAndPlan}
              nextDisabled={!confirmedAnything || planJob.running || elementsJob.running}
              nextLabel={
                elementsJob.running
                  ? "Building…"
                  : confirmedAnything
                    ? `Build ${sceneReading?.summary.to_generate ?? 0} and plan the space`
                    : "Confirm at least one piece first"
              }
            />
          </StepShell>
        ) : null}

        {step.id === "planspace" ? (
          <StepShell
            title="Plan your 3D space"
            subtitle="The pieces you confirmed are built as 3D models and placed in the rooms. Free — nothing is rendered yet, so move things about until the layout is right."
          >
            <div className="flex flex-col gap-3">
              {elementsJob.job || elementsJob.error ? (
                <JobProgress
                  title="Building the confirmed pieces in 3D"
                  job={elementsJob.job}
                  events={elementsJob.events}
                  error={elementsJob.error}
                  onRetry={() => void runGenerateElements()}
                  compact={!elementsJob.running}
                />
              ) : null}
              {sceneId && !planJob.running && !elementsJob.running ? (
                <Walkthrough3DView key={sceneId} sceneId={sceneId} />
              ) : null}
              {!sceneId && !planJob.running && !elementsJob.running ? (
                <div className="rounded-md border border-dashed px-4 py-6 text-center body-sm text-ink-muted">
                  No 3D plan yet. Go back a step and confirm the pieces you want built.
                </div>
              ) : null}
            </div>
            <NavRow onBack={back} onNext={next} nextDisabled={!sceneId || elementsJob.running} nextLabel="Happy with the plan — render it" />
          </StepShell>
        ) : null}

        {step.id === "generate3d" ? (
          <StepShell title="Generate your 3D space" subtitle="This is the paid step: the plan is built in Blender, lit, validated and rendered as a 360° tour you can share. A few minutes on this machine.">
            <div className="flex max-w-2xl flex-col gap-4">
              <div className="flex items-center justify-between rounded-md border p-4">
                <div className="flex flex-col gap-0.5">
                  <p className="body-sm font-medium text-ink-soft">{project?.name ?? "My Allure space"}</p>
                  <p className="caption text-ink-muted">
                    {analysis ? `${analysis.analysis.rooms.length} rooms · ${analysis.style?.name.replace(/_/g, " ")}` : spaceType}
                    {detail?.checkpoints.scene_blend ? " · built before" : ""}
                  </p>
                </div>
                <span className="rounded-sm bg-gold px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink">Paid</span>
              </div>
              {buildJob.job || buildJob.error ? (
                <JobProgress title="Building the scene in Blender" job={buildJob.job} events={buildJob.events} error={buildJob.error} onRetry={() => void runRender()} />
              ) : null}
              {buildPreviewUrl && !buildJob.running ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={api.fileUrl(buildPreviewUrl)} alt="Build preview" className="w-full rounded-md border" />
              ) : null}
              {previewJob.job || previewJob.error ? (
                <JobProgress title="Rendering the 360° tour" job={previewJob.job} events={previewJob.events} error={previewJob.error} onRetry={() => void runRender()} />
              ) : null}
              {engineError ? <EngineError error={engineError} /> : null}
              <button
                type="button"
                onClick={() => void runRender()}
                disabled={rendering || !sceneId}
                className="flex items-center justify-center gap-2 rounded-md bg-gold px-4 py-2.5 body-sm font-medium text-ink hover:opacity-90 disabled:opacity-40"
              >
                {rendering ? <Loader2 className="size-4 animate-spin" /> : <Box className="size-4" />}
                {rendering ? "Rendering your space…" : tour ? "Render again" : "Generate 3D space"}
              </button>
            </div>
            <NavRow onBack={back} onNext={tour ? next : undefined} nextLabel="View the experience" />
          </StepShell>
        ) : null}

        {step.id === "experience" ? (
          <StepShell title="Walk through your space" subtitle="Explore it live in 3D, or take the rendered 360° tour room by room.">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex gap-1 rounded-full border p-1" role="tablist" aria-label="View mode">
                {(["tour", "explore", "film"] as const).map((m) => (
                  <button key={m} role="tab" type="button" aria-selected={experienceMode === m} onClick={() => setExperienceMode(m)} className={`rounded-full px-4 py-1.5 caption font-medium transition ${experienceMode === m ? "bg-ink text-cream" : "text-ink-muted hover:text-ink-soft"}`}>
                    {m === "tour" ? "360° Tour" : m === "explore" ? "Explore in 3D" : "Film"}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                {tour ? <span className="caption text-ink-muted">{tour.quality === "final" ? "Final quality" : "Preview quality"}</span> : null}
                <button type="button" onClick={() => void runFilm()} disabled={filmJob.running || !tour} className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted disabled:opacity-40">
                  {filmJob.running ? <Loader2 className="size-3.5 animate-spin" /> : <Film className="size-3.5" />}
                  {filmJob.running ? "Filming…" : tour?.film ? "Re-render film" : "Render a film"}
                </button>
                <button type="button" onClick={() => void runFinal()} disabled={finalJob.running || !tour} className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted disabled:opacity-40">
                  {finalJob.running ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                  {finalJob.running ? "Rendering final quality…" : "Render final quality"}
                </button>
              </div>
            </div>
            {finalJob.job || finalJob.error ? <JobProgress title="Final 4K panoramas and hero stills" job={finalJob.job} events={finalJob.events} error={finalJob.error} onRetry={() => void runFinal()} compact={!finalJob.running} /> : null}
            {filmJob.job || filmJob.error ? <JobProgress title="Filming the guided tour" job={filmJob.job} events={filmJob.events} error={filmJob.error} onRetry={() => void runFilm()} compact={!filmJob.running} /> : null}
            {experienceMode === "tour" ? (
              tour ? <PanoramaTour pkg={tour} autoplay className="h-[560px] w-full rounded-lg" /> : <p className="body-sm text-ink-muted">No tour rendered yet.</p>
            ) : experienceMode === "film" ? (
              tour ? <div className="flex justify-center rounded-lg bg-black"><FilmPlayer pkg={tour} className="max-h-[560px] w-full rounded-lg" /></div> : null
            ) : (
              <Walkthrough3DView key={sceneId ?? "seed"} sceneId={sceneId ?? undefined} />
            )}
            <NavRow onBack={back} onNext={next} nextLabel="Save & share" />
          </StepShell>
        ) : null}

        {step.id === "share" ? (
          <StepShell title="Saved to your projects" subtitle="Share the walkthrough with family before you commit to anything. The link opens the 360° tour on any phone.">
            <div className="flex max-w-lg flex-col gap-3">
              <div className="flex items-center gap-2 rounded-md border p-3">
                <Check className="size-4 text-gold" />
                <p className="body-sm text-ink-soft">“{project?.name ?? "My Allure space"}” is saved to My Projects.</p>
              </div>
              <ShareLinkRow url={shareUrl} />
              {detail?.outputs.length ? (
                <ul className="flex flex-col gap-1 rounded-md border p-3 caption text-ink-muted">
                  {detail.outputs.slice(-6).map((o) => (
                    <li key={o.output_id} className="flex items-center gap-2">
                      <span className="w-28 shrink-0 text-ink-soft">{o.kind.replace(/_/g, " ")}</span>
                      <a href={api.fileUrl(o.url)} target="_blank" rel="noreferrer" className="truncate underline-offset-2 hover:underline">{o.path}</a>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            <NavRow onBack={back} onNext={next} nextLabel="Connect with a designer" />
          </StepShell>
        ) : null}

        {step.id === "designer" ? (
          <StepShell title="Bring a designer into it" subtitle="A curated match based on your moodboard direction and city — connecting is free.">
            <div className="grid gap-3 md:grid-cols-3">
              {DESIGNERS.filter((d) => d.vetting === "verified").slice(0, 3).map((designer) => (
                <div key={designer.id} className="flex flex-col gap-3 rounded-lg border p-4">
                  <div className="flex items-center gap-3">
                    <Image src={designer.avatar} alt={designer.name} width={40} height={40} className="rounded-full" />
                    <div className="flex flex-col">
                      <p className="body-sm font-medium text-ink-soft">{designer.name}</p>
                      <p className="caption text-ink-muted">{designer.studio} · {designer.city}</p>
                    </div>
                  </div>
                  <p className="caption text-ink-muted">{designer.style}</p>
                  {connectedDesigner === designer.id ? (
                    <p className="flex items-center gap-1.5 body-sm text-ink-soft"><Check className="size-4 text-gold" /> Request sent</p>
                  ) : (
                    <button type="button" onClick={() => setConnectedDesigner(designer.id)} className="flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted">
                      <Users className="size-3.5" /> Connect
                    </button>
                  )}
                </div>
              ))}
            </div>
            <NavRow onBack={back} />
          </StepShell>
        ) : null}
      </div>
    </div>
  );
}

/* ── Pieces ────────────────────────────────────────────────────────────── */

function StepShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h2 className="body text-lg font-medium text-ink-soft">{title}</h2>
        <p className="body-sm text-ink-muted">{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

function NavRow({ onBack, onNext, nextDisabled, nextLabel = "Continue" }: { onBack?: () => void; onNext?: () => void; nextDisabled?: boolean; nextLabel?: string }) {
  return (
    <div className="flex items-center justify-between border-t pt-4">
      {onBack ? (
        <button type="button" onClick={onBack} className="flex items-center gap-1.5 rounded-md px-3 py-1.5 body-sm text-ink-muted hover:bg-muted">
          <ArrowLeft className="size-3.5" /> Back
        </button>
      ) : <span />}
      {onNext ? (
        <button type="button" onClick={onNext} disabled={nextDisabled} className="flex items-center gap-1.5 rounded-md bg-gold px-4 py-2 body-sm font-medium text-ink hover:opacity-90 disabled:opacity-40">
          {nextLabel} <ArrowRight className="size-3.5" />
        </button>
      ) : <span />}
    </div>
  );
}

interface EngineErrorState {
  code: string;
  message: string;
}

const toEngineError = (err: unknown): EngineErrorState =>
  err instanceof ProjectsApiError
    ? { code: err.code, message: err.message }
    : { code: "UNKNOWN", message: err instanceof Error ? err.message : String(err) };

/**
 * The two codes below are boundaries rather than breakages, so they are shown
 * in the info tone with a line on what to do next — nothing is broken and
 * there is nothing to retry.
 */
const ERROR_HEADING: Record<string, string> = {
  OUT_OF_SCOPE: "That part sits outside what Allure designs",
  VERTICAL_LOCKED: "The vertical is already set for this project",
};

const ERROR_NEXT_STEP: Record<string, string> = {
  OUT_OF_SCOPE:
    "Describe the interior instead — layout, furniture, materials, lighting mood — and continue. Anything structural or code-related belongs with your own engineer.",
  VERTICAL_LOCKED: "Carry on with the vertical shown, or start a new project to design for a different one.",
};

function EngineError({ error }: { error: EngineErrorState }) {
  const heading = ERROR_HEADING[error.code];
  const nextStep = ERROR_NEXT_STEP[error.code];
  const boundary = Boolean(heading);
  return (
    <div
      role={boundary ? "status" : "alert"}
      className={`rounded-md border p-3 ${boundary ? "border-info/35 bg-info/8" : "border-warning/35 bg-warning/8"}`}
    >
      {heading ? <p className="body-sm font-medium text-ink-soft">{heading}</p> : null}
      <p className="body-sm text-ink-soft">{error.message}</p>
      {nextStep ? <p className="caption mt-1 text-ink-muted">{nextStep}</p> : null}
      {error.code === "NETWORK_ERROR" ? (
        <p className="caption mt-1 text-ink-muted">
          If the engine is down, start it with <code className="rounded bg-muted px-1 py-0.5">uvicorn app.main:app --port 8000</code> inside <code className="rounded bg-muted px-1 py-0.5">aether-backend/</code>.
        </p>
      ) : null}
    </div>
  );
}

/**
 * Which market the project is designed for. Three native radios in a fieldset:
 * arrow keys move between them for free, and the focus ring is drawn on the
 * card through :has() so the visually hidden input still shows focus.
 *
 * Locked is a read-only pill, not a disabled control — a disabled radio group
 * says "unavailable", this says "decided, and here is why".
 */
function VerticalField({ value, onChange, locked }: { value: Vertical; onChange: (value: Vertical) => void; locked: boolean }) {
  const chosen = VERTICAL_OPTIONS.find((o) => o.value === value) ?? VERTICAL_OPTIONS[0];

  if (locked) {
    return (
      <div className="flex flex-col gap-1.5">
        <span className="body-sm font-medium text-ink-soft">Vertical</span>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill label={chosen.label} tone="neutral" size="sm" />
          <span className="caption text-ink-muted">{chosen.blurb}</span>
        </div>
        <p className="flex items-start gap-1.5 caption text-ink-muted">
          <Lock className="mt-0.5 size-3 shrink-0" aria-hidden />
          Fixed once the project moves past setup — the moodboard and layout were composed for it. Start a new project to design for a different vertical.
        </p>
      </div>
    );
  }

  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="body-sm font-medium text-ink-soft">Vertical</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        {VERTICAL_OPTIONS.map((option) => (
          <label
            key={option.value}
            className="flex cursor-pointer flex-col gap-0.5 rounded-md border px-3 py-2 transition-colors hover:bg-muted has-[:checked]:border-gold has-[:checked]:bg-gold/10 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-gold"
          >
            <input
              type="radio"
              name="vertical"
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            <span className="body-sm font-medium text-ink-soft">{option.label}</span>
            <span className="caption text-ink-muted">{option.blurb}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function RoomRows({ rows, onChange, vertical }: { rows: RoomRow[]; onChange: (rows: RoomRow[]) => void; vertical: Vertical }) {
  const roomTypes = roomTypeOptions(vertical);
  const update = (key: string, patch: Partial<RoomRow>) => onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="body-sm font-medium text-ink-soft">Room sizes <span className="font-normal text-ink-muted">(optional)</span></span>
        <button type="button" onClick={() => onChange([...rows, { key: Date.now().toString(36), name: "", type: defaultRoomType(vertical), width: "", length: "" }])} className="caption text-ink-muted hover:text-ink-soft">
          + Add room
        </button>
      </div>
      {rows.length ? (
        <div className="flex flex-col gap-1.5">
          {rows.map((r) => (
            <div key={r.key} className="grid grid-cols-[1fr_1fr_5rem_5rem_1.5rem] items-center gap-1.5">
              <input value={r.name} placeholder="Name" onChange={(e) => update(r.key, { name: e.target.value })} className="rounded border bg-transparent px-2 py-1 caption text-ink-soft" />
              <select value={r.type} onChange={(e) => update(r.key, { type: e.target.value })} className="rounded border bg-transparent px-2 py-1 caption text-ink-soft">
                {roomTypes.map((t) => <option key={t} value={t}>{roomTypeLabel(t)}</option>)}
              </select>
              <input value={r.width} inputMode="decimal" placeholder="W m" onChange={(e) => update(r.key, { width: e.target.value })} className="rounded border bg-transparent px-2 py-1 caption tabular text-ink-soft" />
              <input value={r.length} inputMode="decimal" placeholder="L m" onChange={(e) => update(r.key, { length: e.target.value })} className="rounded border bg-transparent px-2 py-1 caption tabular text-ink-soft" />
              <button type="button" onClick={() => onChange(rows.filter((x) => x.key !== r.key))} aria-label="Remove row" className="text-ink-muted hover:text-danger"><X className="size-3.5" /></button>
            </div>
          ))}
        </div>
      ) : (
        <p className="caption text-ink-muted">Leave empty and the AI will list the rooms from your brief with estimated sizes.</p>
      )}
    </div>
  );
}

function ShareLinkRow({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-md border p-3">
      <Link2 className="size-4 shrink-0 text-ink-muted" />
      <a href={url || "#"} target="_blank" rel="noreferrer" className="body-sm truncate text-ink-muted underline-offset-2 hover:underline">{url || "Render the space to get a share link"}</a>
      <button
        type="button"
        disabled={!url}
        onClick={() => {
          void navigator.clipboard?.writeText(url).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
          });
        }}
        className="ml-auto shrink-0 rounded-md border px-3 py-1 body-sm text-ink-muted hover:bg-muted disabled:opacity-40"
      >
        {copied ? "Copied" : "Copy link"}
      </button>
    </div>
  );
}
