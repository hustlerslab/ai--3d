import { withShareToken } from "../share-token";
import { TourApiError, type TourPackage } from "../types";

export const AETHER_BASE_URL = (
  process.env.NEXT_PUBLIC_AETHER_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

/** Absolute URL for a backend-served file (`/files/...`).
 *
 * Carries the share token when there is one: P0-SEC-005 closed `/files/*`, and
 * an `<img>` or a WebGL texture cannot send a header, so a visitor with no
 * account authorises each asset through the query string.
 */
export function fileUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return withShareToken(path);
  return withShareToken(`${AETHER_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`);
}

export async function getTour(
  projectId: string,
  signal?: AbortSignal,
  token?: string,
): Promise<TourPackage> {
  let response: Response;
  // P0-SEC-004: the project id no longer authorises anything. A visitor with
  // no account carries a capability token in the link; a signed-in owner
  // carries a session cookie instead, which is why both are sent.
  const query = token ? `?k=${encodeURIComponent(token)}` : "";
  try {
    response = await fetch(
      `${AETHER_BASE_URL}/api/projects/${encodeURIComponent(projectId)}/tour${query}`,
      {
        signal,
        cache: "no-store",
        credentials: "include",
      },
    );
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
