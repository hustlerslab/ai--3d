"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getWalkthroughStatus } from "../api/walkthrough-api";
import {
  WalkthroughApiError,
  type WalkthroughStatusDto,
} from "../types/walkthrough";
import { isTerminal } from "../utils/walkthrough-helpers";

/**
 * Poll one walkthrough's status until it settles.
 *
 * Polling rules, from readme2 §27 and §28:
 *   - Poll roughly every 2s while work is in flight.
 *   - Stop the moment the walkthrough reaches a terminal state. A finished
 *     walkthrough polled forever is a bug, not a feature.
 *   - Never stack requests: the next poll is scheduled after the previous one
 *     resolves, so a slow engine slows the cadence instead of queueing calls.
 *   - Back off on repeated failure rather than hammering a dead engine.
 *
 * `refresh()` bumps a counter that re-runs the effect. That keeps one
 * definition of the loop — calling it after approve or revise restarts polling
 * from a terminal state without a second copy of the scheduling logic.
 */

const BASE_INTERVAL_MS = 2_000;
const MAX_INTERVAL_MS = 30_000;
/** Consecutive failures tolerated before the error is surfaced to the user. */
const FAILURES_BEFORE_SURFACING = 3;

export interface UseWalkthroughStatusResult {
  status: WalkthroughStatusDto | null;
  /** True until the first response arrives. */
  loading: boolean;
  error: WalkthroughApiError | null;
  /** Restart the loop immediately — use after an action changes server state. */
  refresh: () => void;
}

export function useWalkthroughStatus(
  walkthroughId: string | null,
  options: { enabled?: boolean } = {},
): UseWalkthroughStatusResult {
  const { enabled = true } = options;

  const [status, setStatus] = useState<WalkthroughStatusDto | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<WalkthroughApiError | null>(null);
  const [nonce, setNonce] = useState(0);

  // Refs, not state: mutating these must not restart the loop.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failuresRef = useRef(0);

  useEffect(() => {
    if (!walkthroughId || !enabled) {
      setStatus(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const controller = new AbortController();
    failuresRef.current = 0;
    setLoading(true);

    const clearTimer = () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const schedule = (delay: number) => {
      clearTimer();
      timerRef.current = setTimeout(() => void tick(), delay);
    };

    const tick = async () => {
      if (cancelled) return;

      try {
        const next = await getWalkthroughStatus(walkthroughId, controller.signal);
        if (cancelled) return;

        failuresRef.current = 0;
        setStatus(next);
        setError(null);
        setLoading(false);

        // Terminal means terminal. refresh() is how the loop resumes.
        if (isTerminal(next.status)) {
          clearTimer();
          return;
        }

        schedule(BASE_INTERVAL_MS);
      } catch (err) {
        // Our own cleanup aborting the request is not a failure.
        if (cancelled || controller.signal.aborted) return;

        failuresRef.current += 1;
        setLoading(false);

        // A walkthrough the engine has never heard of will not appear later.
        if (err instanceof WalkthroughApiError && err.code === "WALKTHROUGH_NOT_FOUND") {
          setError(err);
          clearTimer();
          return;
        }

        // Tolerate a blip; surface a sustained outage.
        if (failuresRef.current >= FAILURES_BEFORE_SURFACING) {
          setError(
            err instanceof WalkthroughApiError
              ? err
              : new WalkthroughApiError("NETWORK_ERROR", "Lost contact with the engine.", 0, {
                  retryable: true,
                }),
          );
        }

        // Exponential backoff, capped — check a dead engine occasionally,
        // not continuously.
        schedule(Math.min(BASE_INTERVAL_MS * 2 ** failuresRef.current, MAX_INTERVAL_MS));
      }
    };

    void tick();

    return () => {
      cancelled = true;
      clearTimer();
      controller.abort();
    };
  }, [walkthroughId, enabled, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  return { status, loading, error, refresh };
}
