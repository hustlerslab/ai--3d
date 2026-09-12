"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  approveWalkthrough,
  createWalkthrough,
  getHealth,
  getWalkthrough,
  reviseRoom,
  startGeneration,
} from "../api/walkthrough-api";
import {
  WalkthroughApiError,
  type WalkthroughDto,
} from "../types/walkthrough";

/**
 * Owns the walkthrough session: which walkthrough we are on, whether the
 * engine is reachable, and the actions that change server state.
 *
 * Two things here exist because of readme2 §67-add:
 *
 *   Refresh recovery (§67-add-10) — the in-flight walkthrough id is mirrored
 *   into sessionStorage. Losing it on refresh would orphan a render that costs
 *   real money and takes minutes, leaving the user with no way back to it.
 *   This is the single sanctioned exception to the no-storage rule; see
 *   CLAUDE.md. It is wrapped in try/catch because private-mode browsers throw
 *   on access rather than returning null.
 *
 *   Double-click protection (§67-add-11) — every action sets a pending flag and
 *   refuses to run twice. The backend enforces this too; the flag is here so
 *   the user sees a disabled button rather than a 409.
 */

const SESSION_KEY = "allure.walkthrough.id";

/* ── sessionStorage, defensively ───────────────────────────────────────── */

function readStoredId(): string | null {
  try {
    return window.sessionStorage.getItem(SESSION_KEY);
  } catch {
    // Private mode, or site data blocked. Recovery is a convenience, not a
    // requirement — carry on without it.
    return null;
  }
}

function writeStoredId(id: string | null): void {
  try {
    if (id === null) window.sessionStorage.removeItem(SESSION_KEY);
    else window.sessionStorage.setItem(SESSION_KEY, id);
  } catch {
    /* ignore — see readStoredId */
  }
}

/* ── Hook ──────────────────────────────────────────────────────────────── */

export type EngineHealth = "checking" | "online" | "offline";

export interface UseWalkthroughResult {
  walkthroughId: string | null;
  walkthrough: WalkthroughDto | null;
  engineHealth: EngineHealth;
  mockMode: boolean;

  /** True while any mutating action is in flight. */
  pending: boolean;
  /** Which action is running, for per-button disabling. */
  pendingAction: "create" | "generate" | "approve" | "revise" | null;
  error: WalkthroughApiError | null;

  /**
   * Each action takes an optional explicit id.
   *
   * This matters more than it looks. A caller that chains create → upload →
   * generate in one handler is running inside a closure captured BEFORE
   * `create` set the id in state, so reading `walkthroughId` from state there
   * yields null and the action silently does nothing. Passing the id the
   * previous step returned is the only correct way to chain them.
   */
  create: (title: string) => Promise<string | null>;
  generate: (id?: string) => Promise<boolean>;
  approve: (id?: string) => Promise<boolean>;
  revise: (position: number, id?: string) => Promise<boolean>;

  /** Re-read the full record — call when polling reports a terminal state. */
  reload: () => Promise<void>;
  /** Abandon this walkthrough and clear the recovered session. */
  reset: () => void;
  clearError: () => void;
  recheckEngine: () => void;
}

export function useWalkthrough(): UseWalkthroughResult {
  const [walkthroughId, setWalkthroughId] = useState<string | null>(null);
  const [walkthrough, setWalkthrough] = useState<WalkthroughDto | null>(null);
  const [engineHealth, setEngineHealth] = useState<EngineHealth>("checking");
  const [mockMode, setMockMode] = useState(false);
  const [pendingAction, setPendingAction] =
    useState<UseWalkthroughResult["pendingAction"]>(null);
  const [error, setError] = useState<WalkthroughApiError | null>(null);
  const [healthNonce, setHealthNonce] = useState(0);

  // Guards a double-submit within the same tick, before React re-renders.
  const inFlightRef = useRef(false);

  /* ── Engine health ───────────────────────────────────────────────────── */

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    setEngineHealth("checking");

    getHealth(controller.signal)
      .then((health) => {
        if (cancelled) return;
        setEngineHealth("online");
        setMockMode(health.mockMode);
      })
      .catch(() => {
        if (!cancelled) setEngineHealth("offline");
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [healthNonce]);

  /* ── Refresh recovery ────────────────────────────────────────────────── */

  useEffect(() => {
    // Only attempt recovery once the engine is known to be up; otherwise the
    // fetch fails and we would wrongly discard a valid id.
    if (engineHealth !== "online") return;

    const stored = readStoredId();
    if (!stored) return;

    let cancelled = false;

    getWalkthrough(stored)
      .then((dto) => {
        if (cancelled) return;
        setWalkthroughId(dto.id);
        setWalkthrough(dto);
      })
      .catch((err) => {
        if (cancelled) return;
        // The engine has forgotten it (workspace deleted, engine restarted
        // against a different output dir). Drop the stale pointer rather than
        // leaving the UI stuck on an id that will never resolve.
        if (err instanceof WalkthroughApiError && err.code === "WALKTHROUGH_NOT_FOUND") {
          writeStoredId(null);
        }
      });

    return () => {
      cancelled = true;
    };
    // Runs once per transition into "online" — recovery should not re-fire on
    // every subsequent state change.
  }, [engineHealth]);

  /* ── Action wrapper ──────────────────────────────────────────────────── */

  /**
   * Run a mutating action under the double-submit guard.
   * Returns `fallback` if another action is already running.
   */
  const runAction = useCallback(
    async <T,>(
      kind: NonNullable<UseWalkthroughResult["pendingAction"]>,
      fn: () => Promise<T>,
      fallback: T,
    ): Promise<T> => {
      if (inFlightRef.current) return fallback;

      inFlightRef.current = true;
      setPendingAction(kind);
      setError(null);

      try {
        return await fn();
      } catch (err) {
        setError(
          err instanceof WalkthroughApiError
            ? err
            : new WalkthroughApiError("INTERNAL_ERROR", "Unexpected error.", 0),
        );
        return fallback;
      } finally {
        inFlightRef.current = false;
        setPendingAction(null);
      }
    },
    [],
  );

  /* ── Actions ─────────────────────────────────────────────────────────── */

  const create = useCallback(
    (title: string) =>
      runAction(
        "create",
        async () => {
          const created = await createWalkthrough(title.trim() || "Untitled Property");
          setWalkthroughId(created.walkthroughId);
          writeStoredId(created.walkthroughId);

          const dto = await getWalkthrough(created.walkthroughId);
          setWalkthrough(dto);
          return created.walkthroughId;
        },
        null as string | null,
      ),
    [runAction],
  );

  const generate = useCallback(
    (id?: string) =>
      runAction(
        "generate",
        async () => {
          const target = id ?? walkthroughId;
          if (!target) return false;
          await startGeneration(target);
          return true;
        },
        false,
      ),
    [runAction, walkthroughId],
  );

  const approve = useCallback(
    (id?: string) =>
      runAction(
        "approve",
        async () => {
          const target = id ?? walkthroughId;
          if (!target) return false;
          await approveWalkthrough(target, true);
          setWalkthrough(await getWalkthrough(target));
          return true;
        },
        false,
      ),
    [runAction, walkthroughId],
  );

  const revise = useCallback(
    (position: number, id?: string) =>
      runAction(
        "revise",
        async () => {
          const target = id ?? walkthroughId;
          if (!target) return false;
          await reviseRoom(target, { position });
          return true;
        },
        false,
      ),
    [runAction, walkthroughId],
  );

  const reload = useCallback(async () => {
    if (!walkthroughId) return;
    try {
      setWalkthrough(await getWalkthrough(walkthroughId));
    } catch (err) {
      if (err instanceof WalkthroughApiError) setError(err);
    }
  }, [walkthroughId]);

  const reset = useCallback(() => {
    writeStoredId(null);
    setWalkthroughId(null);
    setWalkthrough(null);
    setError(null);
  }, []);

  const clearError = useCallback(() => setError(null), []);
  const recheckEngine = useCallback(() => setHealthNonce((n) => n + 1), []);

  return {
    walkthroughId,
    walkthrough,
    engineHealth,
    mockMode,
    pending: pendingAction !== null,
    pendingAction,
    error,
    create,
    generate,
    approve,
    revise,
    reload,
    reset,
    clearError,
    recheckEngine,
  };
}
