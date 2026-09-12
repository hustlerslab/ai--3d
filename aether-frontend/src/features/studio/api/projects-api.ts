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
    response = await fetch(`${API}${path}`, { ...init, signal: init.signal ?? controller.signal });
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

export const analyze = (projectId: string, force = false) => enqueue(`/projects/${projectId}/analyze`, { force });
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
