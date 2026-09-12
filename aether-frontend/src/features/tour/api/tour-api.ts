import { TourApiError, type TourPackage } from "../types";

export const AETHER_BASE_URL = (
  process.env.NEXT_PUBLIC_AETHER_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

/** Absolute URL for a backend-served file (`/files/...`). */
export function fileUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${AETHER_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function getTour(projectId: string, signal?: AbortSignal): Promise<TourPackage> {
  let response: Response;
  try {
    response = await fetch(`${AETHER_BASE_URL}/api/projects/${encodeURIComponent(projectId)}/tour`, {
      signal,
      cache: "no-store",
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new TourApiError("NETWORK_ERROR", `Could not reach the Aether engine at ${AETHER_BASE_URL}.`, 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.success) {
    const error = body?.error ?? {};
    throw new TourApiError(error.code ?? "HTTP_ERROR", error.message ?? `Request failed (${response.status})`, response.status);
  }
  return body.data as TourPackage;
}
