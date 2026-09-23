import { AETHER_BASE_URL } from "@/features/studio/api/projects-api";

/**
 * The browser's half of P0-SEC-002.
 *
 * The session lives in an httpOnly cookie, so there is deliberately no token
 * here to read, store or accidentally log. Every call sends
 * `credentials: "include"` and the browser attaches it.
 */

export interface AuthUser {
  user_id: string;
  email: string;
  role: string;
}

export class AuthError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "AuthError";
  }
}

async function post(path: string, body: unknown): Promise<AuthUser> {
  let response: Response;
  try {
    response = await fetch(`${AETHER_BASE_URL}/api/auth/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
  } catch {
    throw new AuthError(
      "NETWORK_ERROR",
      `Could not reach the Aether engine at ${AETHER_BASE_URL}. Is it running?`,
      0,
    );
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.success === false) {
    // FastAPI wraps a raised HTTPException under `detail`; our own error
    // responses are flat. Read both, rather than showing "Request failed".
    const error = payload?.error ?? payload?.detail?.error ?? {};
    throw new AuthError(
      error.code ?? "HTTP_ERROR",
      error.message ?? `Request failed (${response.status})`,
      response.status,
    );
  }
  return payload.data.user as AuthUser;
}

export const signIn = (email: string, password: string) => post("login", { email, password });
export const register = (email: string, password: string) => post("register", { email, password });

/**
 * Who is signed in, or null. Never throws for "nobody" — that is a normal
 * state, not an error, and treating it as one makes every first page load look
 * like a failure.
 */
export async function currentUser(signal?: AbortSignal): Promise<AuthUser | null> {
  try {
    const response = await fetch(`${AETHER_BASE_URL}/api/auth/session`, {
      credentials: "include",
      cache: "no-store",
      signal,
    });
    if (!response.ok) return null;
    const payload = await response.json();
    return payload?.data?.authenticated ? (payload.data.user as AuthUser) : null;
  } catch {
    return null;
  }
}

export async function signOut(): Promise<void> {
  try {
    await fetch(`${AETHER_BASE_URL}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Signing out must not be able to fail in the UI. The cookie is cleared by
    // the response when it arrives; if the request never lands, the session
    // still expires on its own.
  }
}
