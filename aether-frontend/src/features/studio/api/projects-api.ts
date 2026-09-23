/**
 * Client for the project pipeline routes (aether-backend app/api/projects_routes.py).
 * Long work never blocks: every POST that does work returns a job to poll.
 */

import {
  ProjectsApiError,
  type AnalysisDto,
  type AnalysisPatch,
  type BuildDto,
  type EventDto,
  type InputRecord,
  type JobDto,
  type ProjectDetail,
  type ProjectRecord,
  type RoomHint,
  type SceneSpecDto,
  type Vertical,
  type CreditsDto,
  type ElementImageSetDto,
  type SceneReadingDto,
} from "../types";

export const AETHER_BASE_URL = (
  process.env.NEXT_PUBLIC_AETHER_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");
const API = `${AETHER_BASE_URL}/api`;

export function fileUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${AETHER_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 20_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      ...init,
      // P0-SEC-002: the API is deny-by-default. `include` sends the httpOnly
      // `allure_session` cookie set by POST /api/auth/login. Script never reads
      // the token - that is what httpOnly buys - so this is the only way the
      // browser can authenticate.
      credentials: "include",
      signal: init.signal ?? controller.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (init.signal?.aborted) throw err;
    throw new ProjectsApiError("NETWORK_ERROR", `Could not reach the Aether engine at ${AETHER_BASE_URL}. Is it running?`, 0);
  }
  clearTimeout(timer);
  const body = await response.json().catch(() => null);
  if (!response.ok || body?.success === false) {
    const error = body?.error ?? {};
    throw new ProjectsApiError(error.code ?? "HTTP_ERROR", error.message ?? `Request failed (${response.status})`, response.status);
  }
  return body as T;
}

const json = (data: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

// ── projects ─────────────────────────────────────────────────────────────

export async function createProject(input: { name: string; description?: string; room_hints?: RoomHint[]; vertical?: Vertical }) {
  const body = await request<{ project: ProjectRecord }>("/projects", json(input));
  return body.project;
}

/** Every project the engine holds, most recently touched first. */
export async function listProjects(signal?: AbortSignal): Promise<ProjectRecord[]> {
  const body = await request<{ data: ProjectRecord[] }>("/projects", { signal });
  // updated_at is ISO-8601 with a UTC offset, so a string sort is a time sort.
  return [...body.data].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export async function getProject(projectId: string, signal?: AbortSignal): Promise<ProjectDetail> {
  const body = await request<{ data: ProjectDetail }>(`/projects/${projectId}`, { signal });
  return body.data;
}

/** Sending the vertical a project already has is a no-op; changing it after CREATED fails with VERTICAL_LOCKED (409). */
export async function updateProject(projectId: string, patch: { name?: string; description?: string; room_hints?: RoomHint[]; vertical?: Vertical }) {
  const body = await request<{ project: ProjectRecord }>(`/projects/${projectId}`, { ...json(patch), method: "PATCH" });
  return body.project;
}

/** Everything uploaded to a project, oldest first. */
export async function listInputs(projectId: string, signal?: AbortSignal): Promise<InputRecord[]> {
  const body = await request<{ data: InputRecord[] }>(`/projects/${projectId}/inputs`, { signal });
  return body.data;
}

/** Remove one upload and its file. The reference cap is a dead end without it. */
export async function deleteInput(projectId: string, inputId: string): Promise<void> {
  await request<{ data: unknown }>(`/projects/${projectId}/inputs/${inputId}`, { method: "DELETE" });
}

/** What survived a delete. The expensive half outlives the project. */
export interface DeletedProject {
  deleted: string;
  kept: { moodboard_rooms: number; references?: number; scene_crops?: number; asset_ids: string[] };
}

/** Delete a project. Its moodboard renders and any meshes generated from them
 *  are archived rather than removed — they cost real minutes and real credits.
 *  The caller is told what survived so it can say so instead of leaving the
 *  user to guess whether the work is gone. */
export async function deleteProject(projectId: string): Promise<DeletedProject> {
  const body = await request<{ data: DeletedProject }>(`/projects/${projectId}`, { method: "DELETE" });
  return body.data;
}

/** Multipart upload with real progress (XHR: fetch has no upload progress). */
export function uploadInputs(
  projectId: string,
  input: { description?: string; dimensions?: RoomHint[]; files: File[] },
  onProgress?: (fraction: number) => void,
): Promise<{ project: ProjectRecord; rejected: { filename: string; reason: string }[] }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    if (input.description) form.append("description", input.description);
    if (input.dimensions && input.dimensions.length) form.append("dimensions", JSON.stringify(input.dimensions));
    for (const file of input.files) form.append("references", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/projects/${projectId}/inputs`);
    // XHR needs this set separately from fetch's `credentials` option.
    xhr.withCredentials = true;
    xhr.timeout = 10 * 60 * 1000;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: { success?: boolean; error?: { code: string; message: string }; project?: ProjectRecord; rejected?: { filename: string; reason: string }[] } | null = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300 && body?.success !== false && body?.project) {
        resolve({ project: body.project, rejected: body.rejected ?? [] });
      } else {
        reject(new ProjectsApiError(body?.error?.code ?? "UPLOAD_FAILED", body?.error?.message ?? `Upload failed (${xhr.status})`, xhr.status));
      }
    };
    xhr.onerror = () => reject(new ProjectsApiError("NETWORK_ERROR", "Upload failed: could not reach the engine.", 0));
    xhr.ontimeout = () => reject(new ProjectsApiError("TIMEOUT", "Upload timed out.", 0));
    xhr.send(form);
  });
}

// ── pipeline stages (each returns a job) ─────────────────────────────────

async function enqueue(path: string, body: unknown): Promise<JobDto> {
  const res = await request<{ job: JobDto }>(path, json(body));
  return res.job;
}

/** `paint=false` is the element-first entry: analysis, crops and style without
 *  painting rooms, so the pieces can be pictured before any room exists. */
export const analyze = (projectId: string, force = false, paint = true) =>
  enqueue(`/projects/${projectId}/analyze`, { force, paint });

/** One isolated picture per canonical piece, from the photos and the brief.
 *  Local GPU; no per-image cost. */
export const elementImages = (projectId: string, force = false) =>
  enqueue(`/projects/${projectId}/element-images`, { force });

/** The client's decision per pictured piece, keyed by canonical element id. */
export async function reviewElementImages(projectId: string, decisions: Record<string, boolean>): Promise<ElementImageSetDto> {
  const body = await request<{ data: ElementImageSetDto }>(
    `/projects/${projectId}/element-images`, { ...json({ decisions }), method: "PATCH" });
  return body.data;
}

export async function getElementImages(projectId: string, signal?: AbortSignal): Promise<ElementImageSetDto> {
  const body = await request<{ data: ElementImageSetDto }>(`/projects/${projectId}/element-images`, { signal });
  return body.data;
}

/** Redraw one room's moodboard image on a fresh seed, leaving the reading, the
 *  style and the other rooms alone. The same prompt gives a complete bathroom
 *  on one seed and a bathtub in an alcove on another, and no wording tells them
 *  apart — so the reviewer draws again (ADR-002 §1). */
export const repaintRoom = (projectId: string, roomId: string) =>
  enqueue(`/projects/${projectId}/moodboard/rooms/${roomId}/repaint`, {});
export const scenePlan = (projectId: string, force = false) => enqueue(`/projects/${projectId}/scene-plan`, { force });
export const resolveAssets = (projectId: string) => enqueue(`/projects/${projectId}/assets/resolve`, {});
export const build = (projectId: string, opts: { force?: boolean; preview?: boolean; preview_profile?: string } = {}) =>
  enqueue(`/projects/${projectId}/build`, { force: false, preview: true, preview_profile: "preview", ...opts });
export const preview = (projectId: string, opts: { force?: boolean; profile?: string } = {}) =>
  enqueue(`/projects/${projectId}/preview`, { force: false, profile: "pano_preview", ...opts });
export const walkthrough = (projectId: string, opts: { force?: boolean; profile?: string; hero_stills?: number } = {}) =>
  enqueue(`/projects/${projectId}/walkthrough`, { force: false, profile: "pano_final", hero_stills: 2, ...opts });
export const film = (projectId: string, opts: { force?: boolean; profile?: string } = {}) =>
  enqueue(`/projects/${projectId}/film`, { force: false, profile: "preview", ...opts });

// ── reads ────────────────────────────────────────────────────────────────

export async function getAnalysis(projectId: string, signal?: AbortSignal): Promise<AnalysisDto> {
  const body = await request<{ data: AnalysisDto }>(`/projects/${projectId}/analysis`, { signal });
  return body.data;
}

export async function patchAnalysis(projectId: string, patch: AnalysisPatch) {
  return request<{ analysis: AnalysisDto["analysis"]; style: AnalysisDto["style"] }>(
    `/projects/${projectId}/analysis`,
    { ...json(patch), method: "PATCH" },
  );
}

export async function getSceneSpec(projectId: string, signal?: AbortSignal): Promise<SceneSpecDto> {
  const body = await request<{ data: SceneSpecDto }>(`/projects/${projectId}/scene-spec`, { signal });
  return body.data;
}

export async function getBuild(projectId: string, signal?: AbortSignal): Promise<BuildDto> {
  const body = await request<{ data: BuildDto }>(`/projects/${projectId}/build`, { signal });
  return body.data;
}

export async function getJob(jobId: string, signal?: AbortSignal): Promise<{ job: JobDto; events: EventDto[] }> {
  const body = await request<{ data: { job: JobDto; events: EventDto[] } }>(`/jobs/${jobId}`, { signal }, 10_000);
  return body.data;
}

export async function getEvents(projectId: string, after = 0, signal?: AbortSignal): Promise<{ events: EventDto[]; last_id: number }> {
  const body = await request<{ data: { events: EventDto[]; last_id: number } }>(`/projects/${projectId}/events?after=${after}`, { signal });
  return body.data;
}

export const TERMINAL: JobDto["status"][] = ["SUCCEEDED", "FAILED", "CANCELLED"];
export const isTerminal = (status: JobDto["status"]) => TERMINAL.includes(status);

/** The crops read out of the approved moodboard, each with the label the scene
 *  read gave it and the verdict of the isolated second look. */
export async function getSceneReading(projectId: string, signal?: AbortSignal): Promise<SceneReadingDto> {
  const body = await request<{ data: SceneReadingDto }>(`/projects/${projectId}/scene-reading`, { signal });
  return body.data;
}

/** Record confirm/reject per element. Keyed by element_id, never by position:
 *  the list is re-read and re-ordered between the render and the click. */
export async function reviewSceneReading(projectId: string, decisions: Record<string, boolean>) {
  const body = await request<{ data: SceneReadingDto }>(
    `/projects/${projectId}/scene-reading`,
    { ...json({ decisions }), method: "PATCH" },
  );
  return body.data;
}

/** Remaining Meshy credits. Never throws the page: the backend answers
 *  `available: false` with a reason rather than failing, because a missing
 *  balance is not a reason to stop someone planning a room. */
export async function getCredits(signal?: AbortSignal): Promise<CreditsDto> {
  const body = await request<{ data: CreditsDto }>(`/credits`, { signal });
  return body.data;
}

/** The paid step: turn approved crops into meshes.
 *
 *  Unwraps to the job like every other trigger, so it composes with `useJob`.
 *  The cost is deliberately not read back from here — the caller re-fetches the
 *  reading afterwards, because what was actually spent is the server's answer,
 *  not the quote the button happened to be pressed on. */
export const generateElements = (projectId: string, limit?: number) =>
  enqueue(`/projects/${projectId}/elements/generate`, limit === undefined ? {} : { limit });
