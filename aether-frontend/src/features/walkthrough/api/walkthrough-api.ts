/**
 * The walkthrough engine HTTP client.
 *
 * This is the ONLY module in the app permitted to make network calls, and it
 * may only ever talk to the walkthrough engine — see the walkthrough exception
 * in CLAUDE.md. Components and hooks call these functions; they never call
 * `fetch` themselves.
 *
 * Every function throws `WalkthroughApiError` on failure, carrying the engine's
 * structured error code so callers switch on `code` rather than parsing prose.
 */

import {
  WalkthroughApiError,
  type ApproveResponse,
  type CreateWalkthroughResponse,
  type GenerateResponse,
  type HealthResponse,
  type ReviseResponse,
  type UploadImagesResponse,
  type WalkthroughDto,
  type WalkthroughScene,
  type WalkthroughStatusDto,
} from "../types/walkthrough";

/**
 * Engine base URL.
 *
 * The default keeps the demo working with no environment set up at all: an
 * unset var means localhost, and if nothing is listening there the health
 * check fails cleanly and the route renders its "engine unavailable" state.
 * The rest of the app never depends on this.
 *
 * Never put a secret in a NEXT_PUBLIC_ var — this is a plain origin, and the
 * Apify and Higgsfield keys stay server-side in the engine's own .env.
 */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_WALKTHROUGH_API_URL ?? "http://localhost:4000"
).replace(/\/+$/, "");

const API_ROOT = `${API_BASE_URL}/api`;

/** Requests that should never hang the UI. Uploads get their own budget. */
const DEFAULT_TIMEOUT_MS = 15_000;

/* ── Core request helper ───────────────────────────────────────────────── */

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/**
 * Perform a JSON request and unwrap the engine's response envelope.
 *
 * The engine answers with `{ success, data }` on reads and a flat object on
 * writes, and with `{ success: false, error: {...} }` on failure. This
 * normalises all three so callers only ever see the payload or an exception.
 */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;

  // Compose the caller's signal with our own timeout, so either can cancel.
  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), timeoutMs);
  const composed = anySignal([signal, timeoutController.signal]);

  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: composed,
    });
  } catch (err) {
    clearTimeout(timer);

    // A caller-initiated abort is not an error worth surfacing — rethrow it so
    // effects can distinguish "we unmounted" from "the engine is down".
    if (signal?.aborted) throw err;

    if (timeoutController.signal.aborted) {
      throw new WalkthroughApiError(
        "SERVER_UNAVAILABLE",
        "The walkthrough engine did not respond in time.",
        0,
        { retryable: true },
      );
    }

    throw new WalkthroughApiError(
      "NETWORK_ERROR",
      `Could not reach the walkthrough engine at ${API_BASE_URL}. Is it running?`,
      0,
      { retryable: true },
    );
  }
  clearTimeout(timer);

  return unwrap<T>(response);
}

/**
 * Turn a Response into a payload or a typed error.
 */
async function unwrap<T>(response: Response): Promise<T> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // A non-JSON body from a proxy or crashed process
    if (!response.ok) {
      throw new WalkthroughApiError(
        "SERVER_UNAVAILABLE",
        `The engine returned ${response.status} with an unreadable body.`,
        response.status,
        { retryable: response.status >= 500 },
      );
    }
    throw new WalkthroughApiError(
      "INTERNAL_ERROR",
      "The engine returned a response that could not be parsed.",
      response.status,
    );
  }

  const record = payload as {
    success?: boolean;
    data?: unknown;
    error?: { code?: string; message?: string; stage?: string | null; retryable?: boolean };
  };

  if (!response.ok || record.success === false) {
    const error = record.error;
    throw new WalkthroughApiError(
      error?.code ?? "INTERNAL_ERROR",
      error?.message ?? `Request failed with status ${response.status}.`,
      response.status,
      { stage: error?.stage ?? null, retryable: error?.retryable ?? response.status >= 500 },
    );
  }

  // Reads wrap the payload in `data`; writes return it flat.
  return (record.data !== undefined ? record.data : payload) as T;
}

/**
 * Combine several AbortSignals into one.
 * `AbortSignal.any` is not available in every browser this demo must run in,
 * so fall back to manual wiring rather than assuming it.
 */
function anySignal(signals: Array<AbortSignal | undefined>): AbortSignal {
  const real = signals.filter((s): s is AbortSignal => Boolean(s));
  if (real.length === 1) return real[0];

  if (typeof AbortSignal !== "undefined" && "any" in AbortSignal) {
    return (AbortSignal as unknown as { any(s: AbortSignal[]): AbortSignal }).any(real);
  }

  const controller = new AbortController();
  for (const signal of real) {
    if (signal.aborted) {
      controller.abort();
      break;
    }
    signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return controller.signal;
}

/* ── Health ────────────────────────────────────────────────────────────── */

/**
 * Is the engine reachable? Used to render the "engine unavailable" state
 * rather than letting the first real action fail.
 */
export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>("/health", { signal, timeoutMs: 5_000 });
}

/* ── Lifecycle ─────────────────────────────────────────────────────────── */

export async function createWalkthrough(
  title: string,
  signal?: AbortSignal,
): Promise<CreateWalkthroughResponse> {
  return request<CreateWalkthroughResponse>("/walkthroughs", {
    method: "POST",
    body: { inputMode: "upload", title },
    signal,
  });
}

export async function getWalkthrough(
  id: string,
  signal?: AbortSignal,
): Promise<WalkthroughDto> {
  return request<WalkthroughDto>(`/walkthroughs/${encodeURIComponent(id)}`, { signal });
}

export async function getWalkthroughStatus(
  id: string,
  signal?: AbortSignal,
): Promise<WalkthroughStatusDto> {
  return request<WalkthroughStatusDto>(`/walkthroughs/${encodeURIComponent(id)}/status`, {
    signal,
    // Polling must fail fast; a slow status call should not stack up requests.
    timeoutMs: 8_000,
  });
}

/* ── Upload ────────────────────────────────────────────────────────────── */

/**
 * Upload images with real progress.
 *
 * Uses XMLHttpRequest rather than fetch on purpose: fetch still has no upload
 * progress event, and readme2 §67-add-9 requires a real percentage rather than
 * an indeterminate spinner for what can be tens of megabytes.
 */
export function uploadImages(
  id: string,
  files: File[],
  handlers: {
    onProgress?: (percent: number) => void;
    signal?: AbortSignal;
  } = {},
): Promise<UploadImagesResponse> {
  const { onProgress, signal } = handlers;

  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const file of files) form.append("images[]", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_ROOT}/walkthroughs/${encodeURIComponent(id)}/images`);

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      let payload: unknown;
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        reject(
          new WalkthroughApiError(
            "UPLOAD_FAILED",
            `The engine returned ${xhr.status} with an unreadable body.`,
            xhr.status,
          ),
        );
        return;
      }

      const record = payload as {
        success?: boolean;
        error?: { code?: string; message?: string; retryable?: boolean };
      };

      if (xhr.status < 200 || xhr.status >= 300 || record.success === false) {
        reject(
          new WalkthroughApiError(
            record.error?.code ?? "UPLOAD_FAILED",
            record.error?.message ?? `Upload failed with status ${xhr.status}.`,
            xhr.status,
            { retryable: record.error?.retryable ?? false },
          ),
        );
        return;
      }

      resolve(payload as UploadImagesResponse);
    });

    xhr.addEventListener("error", () => {
      reject(
        new WalkthroughApiError(
          "NETWORK_ERROR",
          `Could not reach the walkthrough engine at ${API_BASE_URL}. Is it running?`,
          0,
          { retryable: true },
        ),
      );
    });

    xhr.addEventListener("abort", () => {
      reject(new WalkthroughApiError("UPLOAD_FAILED", "Upload cancelled.", 0));
    });

    signal?.addEventListener("abort", () => xhr.abort(), { once: true });

    xhr.send(form);
  });
}

/* ── Generation ────────────────────────────────────────────────────────── */

export async function startGeneration(
  id: string,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  return request<GenerateResponse>(`/walkthroughs/${encodeURIComponent(id)}/generate`, {
    method: "POST",
    body: {},
    signal,
  });
}

/* ── Review ────────────────────────────────────────────────────────────── */

export async function approveWalkthrough(
  id: string,
  approved: boolean,
  signal?: AbortSignal,
): Promise<ApproveResponse> {
  return request<ApproveResponse>(`/walkthroughs/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    body: { approved },
    signal,
  });
}

/**
 * Request regeneration of one room. Every other scene is left untouched by the
 * engine — this is the surgical path, not a rebuild.
 */
export async function reviseRoom(
  id: string,
  reference: { room: string } | { scene: string } | { position: number },
  signal?: AbortSignal,
): Promise<ReviseResponse> {
  return request<ReviseResponse>(`/walkthroughs/${encodeURIComponent(id)}/revise`, {
    method: "POST",
    body: reference,
    signal,
  });
}

export async function listScenes(
  id: string,
  signal?: AbortSignal,
): Promise<{ count: number; scenes: WalkthroughScene[] }> {
  const payload = await request<{
    walkthroughId: string;
    count: number;
    scenes: WalkthroughScene[];
  }>(`/walkthroughs/${encodeURIComponent(id)}/scenes`, { signal });

  return { count: payload.count, scenes: payload.scenes };
}

/* ── Media URLs ────────────────────────────────────────────────────────── */

/**
 * Absolute URL for the finished master.
 *
 * `version` is appended because the engine rewrites the master in place on
 * every revision. Without it the browser replays the cached first cut and the
 * user concludes the revision silently failed (readme2 §67-add-7).
 */
export function videoUrl(id: string, version: number): string {
  return `${API_ROOT}/walkthroughs/${encodeURIComponent(id)}/video?v=${version}`;
}

export function downloadUrl(id: string, version: number): string {
  return `${API_ROOT}/walkthroughs/${encodeURIComponent(id)}/download?v=${version}`;
}

export function sceneVideoUrl(id: string, position: number, version: number): string {
  return `${API_ROOT}/walkthroughs/${encodeURIComponent(id)}/scenes/${position}/video?v=${version}`;
}
