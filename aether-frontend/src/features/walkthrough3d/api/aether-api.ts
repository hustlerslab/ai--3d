/**
 * HTTP client for the Aether walkthrough backend.
 *
 * Follows the same discipline as the photo-walkthrough client: this module is
 * the only place in the 3D feature that fetches, every failure surfaces as a
 * typed AetherApiError, and the base URL comes from one NEXT_PUBLIC_ var with
 * a working localhost default. No secrets ever appear here — the Gemini and
 * Meshy keys live in the backend's own .env.
 */

import {
  AetherApiError,
  type AetherHealth,
  type AetherScene,
  type CatalogItem,
  type HistoryInfo,
  type MaterialRecord,
  type PatchOperation,
  type ProposalPreview,
  type SpawnPoint,
  type TourPath,
  type Violation,
} from "../types/scene";

export const AETHER_BASE_URL = (
  process.env.NEXT_PUBLIC_AETHER_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

const API_ROOT = `${AETHER_BASE_URL}/api`;
const DEFAULT_TIMEOUT_MS = 15_000;

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;

  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ?? timeout.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (signal?.aborted) throw err;
    throw new AetherApiError(
      "NETWORK_ERROR",
      `Could not reach the Aether engine at ${AETHER_BASE_URL}. Is it running?`,
      0,
      { retryable: true },
    );
  }
  clearTimeout(timer);

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    throw new AetherApiError(
      "INTERNAL_ERROR",
      `The engine returned ${response.status} with an unreadable body.`,
      response.status,
      { retryable: response.status >= 500 },
    );
  }

  const record = payload as {
    success?: boolean;
    data?: unknown;
    error?: {
      code?: string;
      message?: string;
      retryable?: boolean;
      violations?: Violation[];
    };
  };

  if (!response.ok || record.success === false) {
    throw new AetherApiError(
      record.error?.code ?? "INTERNAL_ERROR",
      record.error?.message ?? `Request failed with status ${response.status}.`,
      response.status,
      {
        retryable: record.error?.retryable ?? response.status >= 500,
        violations: record.error?.violations ?? [],
      },
    );
  }

  return (record.data !== undefined ? record.data : payload) as T;
}

/* ── Health ────────────────────────────────────────────────────────────── */

export async function getHealth(signal?: AbortSignal): Promise<AetherHealth> {
  return request<AetherHealth>("/health", { signal, timeoutMs: 5_000 });
}

/* ── Scenes ────────────────────────────────────────────────────────────── */

export interface SceneSummary {
  scene_id: string;
  name: string;
  project_id: string;
  version: number;
  rooms: number;
  objects: number;
}

export async function listScenes(signal?: AbortSignal): Promise<SceneSummary[]> {
  return request<SceneSummary[]>("/scenes", { signal });
}

export async function createScene(
  name: string,
  projectId = "proj_seed",
): Promise<{ scene: AetherScene }> {
  return request("/scenes", {
    method: "POST",
    body: { project_id: projectId, name, from_seed: true },
  });
}

export async function getScene(
  sceneId: string,
  signal?: AbortSignal,
): Promise<{ scene: AetherScene; history: HistoryInfo }> {
  return request(`/scenes/${encodeURIComponent(sceneId)}`, { signal });
}

/* ── Patches / undo / redo ─────────────────────────────────────────────── */

export async function commitPatch(
  sceneId: string,
  baseVersion: number,
  operations: PatchOperation[],
): Promise<{ scene: AetherScene; version: number; history: HistoryInfo }> {
  return request(`/scenes/${encodeURIComponent(sceneId)}/patches`, {
    method: "POST",
    body: { base_version: baseVersion, operations, source: "user" },
  });
}

export async function undo(
  sceneId: string,
): Promise<{ scene: AetherScene; history: HistoryInfo }> {
  return request(`/scenes/${encodeURIComponent(sceneId)}/undo`, {
    method: "POST",
    body: {},
  });
}

export async function redo(
  sceneId: string,
): Promise<{ scene: AetherScene; history: HistoryInfo }> {
  return request(`/scenes/${encodeURIComponent(sceneId)}/redo`, {
    method: "POST",
    body: {},
  });
}

/* ── Walkthrough ───────────────────────────────────────────────────────── */

export async function getTour(sceneId: string, signal?: AbortSignal): Promise<TourPath> {
  return request<TourPath>(
    `/scenes/${encodeURIComponent(sceneId)}/walkthrough/tour`,
    { signal },
  );
}

export async function getSpawn(
  sceneId: string,
  signal?: AbortSignal,
): Promise<SpawnPoint> {
  return request<SpawnPoint>(
    `/scenes/${encodeURIComponent(sceneId)}/walkthrough/spawn`,
    { signal },
  );
}

/* ── Design ────────────────────────────────────────────────────────────── */

export async function createProposal(
  sceneId: string,
  instruction: string,
): Promise<ProposalPreview> {
  return request(`/scenes/${encodeURIComponent(sceneId)}/design/proposals`, {
    method: "POST",
    body: { instruction },
    timeoutMs: 70_000, // Gemini calls can be slow; mock is instant
  });
}

export async function applyProposal(
  sceneId: string,
  proposalId: string,
): Promise<{ scene: AetherScene; version: number; history: HistoryInfo }> {
  return request(
    `/scenes/${encodeURIComponent(sceneId)}/design/proposals/${encodeURIComponent(proposalId)}/apply`,
    { method: "POST", body: {} },
  );
}

export async function rejectProposal(
  sceneId: string,
  proposalId: string,
): Promise<{ proposal_id: string; status: string }> {
  return request(
    `/scenes/${encodeURIComponent(sceneId)}/design/proposals/${encodeURIComponent(proposalId)}/reject`,
    { method: "POST", body: {} },
  );
}

/* ── Catalog ───────────────────────────────────────────────────────────── */

export async function getCatalog(projectId = "", signal?: AbortSignal): Promise<CatalogItem[]> {
  // Scoped so the renderer can resolve the pieces generated for THIS project.
  // Without it they are absent from the catalog by design and every generated
  // mesh silently falls back to a parametric box.
  const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return request<CatalogItem[]>(`/catalog${q}`, { signal });
}

/**
 * Swap every parametric placeholder in the scene for the best real model of
 * its type. Goes through the commit pipeline; anything that no longer fits
 * is reported in `skipped` rather than forced.
 */
export async function upgradeSceneAssets(
  sceneId: string,
): Promise<{
  scene: AetherScene;
  history: HistoryInfo;
  replaced: Array<{ object_id: string; asset_id: string; name: string }>;
  skipped: Array<{ object_id: string; reason: string }>;
}> {
  return request(`/scenes/${encodeURIComponent(sceneId)}/assets/upgrade`, {
    method: "POST",
    body: {},
    timeoutMs: 30_000,
  });
}

export async function getMaterials(signal?: AbortSignal): Promise<MaterialRecord[]> {
  return request<MaterialRecord[]>("/materials", { signal });
}

/**
 * Absolute URL for a file the engine serves — normalized GLBs and material
 * maps. Accepts either an engine-relative "/files/..." path or a data-dir
 * relative path like "materials/wood_oak/color.jpg".
 */
export function fileUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  const clean = path.replace(/^\/+/, "");
  return clean.startsWith("files/")
    ? `${AETHER_BASE_URL}/${clean}`
    : `${AETHER_BASE_URL}/files/${clean}`;
}
