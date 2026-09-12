"use client";

import { AlertCircle, Loader2 } from "lucide-react";

import { Button } from "@/components/shared/button";
import { cn } from "@/lib/utils";

import type { WalkthroughStatusDto } from "../types/walkthrough";
import { friendlyError, stageLabel } from "../utils/walkthrough-helpers";

import { SceneProgress } from "./scene-progress";

/**
 * What the engine is doing right now.
 *
 * Generation takes minutes, and an unexplained wait feels broken. Three things
 * make it legible: a stage name in plain language, a percentage that only ever
 * moves forward, and the per-room list so a slow run still shows visible
 * movement between stage changes.
 *
 * The progress bar is a real `role="progressbar"` with aria values rather than
 * a styled div — a screen reader user gets the same information sighted users
 * do, which readme2 §38 requires.
 */
export function GenerationProgress({
  status,
  onRetry,
  retrying = false,
}: {
  status: WalkthroughStatusDto;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const failed = status.status === "failed";
  const percent = status.progress ?? 0;

  if (failed) {
    const copy = friendlyError(status.error?.code, status.error?.message);

    return (
      <section
        className="flex flex-col gap-4 rounded-lg border border-danger/35 bg-danger/6 p-6"
        aria-live="polite"
      >
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
          <div className="flex flex-col gap-1.5">
            <h2 className="body font-medium text-ink-soft">{copy.title}</h2>
            <p className="body-sm text-ink-muted">{copy.detail}</p>
            {copy.action ? <p className="body-sm text-ink-muted">{copy.action}</p> : null}
          </div>
        </div>

        {onRetry && status.error?.retryable !== false ? (
          <div className="flex items-center gap-3">
            <Button variant="primary" size="sm" onClick={onRetry} disabled={retrying}>
              {retrying ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
              {retrying ? "Retrying" : "Try again"}
            </Button>
            <p className="caption text-ink-muted">Rooms that already finished are kept.</p>
          </div>
        ) : null}

        {status.scenes.length > 0 ? <SceneProgress scenes={status.scenes} /> : null}
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-6" aria-live="polite" aria-busy={!status.terminal}>
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-raised p-6 shadow-sm">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <div className="flex items-center gap-2.5">
            {!status.terminal ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-gold" aria-hidden />
            ) : null}
            <h2 className="body font-medium text-ink-soft">{stageLabel(status.status)}</h2>
          </div>
          <p className="numeric-lg text-ink-soft">{percent}%</p>
        </div>

        <div
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Walkthrough generation progress"
          className="h-1.5 w-full overflow-hidden rounded-pill bg-sand"
        >
          <div
            className={cn(
              "h-full rounded-pill bg-gold",
              // 600ms because the jumps between stages are large; a faster
              // tween reads as a glitch rather than movement.
              "transition-[width] duration-600 ease-out",
              "motion-reduce:transition-none",
            )}
            style={{ width: `${percent}%` }}
          />
        </div>

        <p className="caption text-ink-muted">
          This usually takes a few minutes. You can leave this page open — progress is saved.
        </p>
      </div>

      {status.scenes.length > 0 ? <SceneProgress scenes={status.scenes} /> : null}
    </section>
  );
}
