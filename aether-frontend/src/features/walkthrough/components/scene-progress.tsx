"use client";

import { Check, Loader2, RotateCcw, SkipForward, X } from "lucide-react";

import { cn } from "@/lib/utils";

import type { SceneProgressItem, SceneStatus } from "../types/walkthrough";
import { roomLabel, sceneStatusLabel } from "../utils/walkthrough-helpers";

/**
 * Per-room progress while the walkthrough is being filmed.
 *
 * Rooms are generated in parallel, so this is a status list, not a sequence —
 * showing it as a stepper would imply an order that does not exist and make a
 * finished room 6 look wrong while room 3 is still running.
 *
 * Status is never colour alone: every row carries an icon and a word, per the
 * same rule that governs StatusPill.
 */

const ICON: Record<SceneStatus, typeof Check> = {
  pending: Loader2,
  queued: Loader2,
  running: Loader2,
  retrying: RotateCcw,
  completed: Check,
  failed: X,
  skipped: SkipForward,
};

const TONE: Record<SceneStatus, string> = {
  pending: "border-border bg-surface-raised text-ink-muted",
  queued: "border-border bg-surface-raised text-ink-muted",
  running: "border-info/40 bg-info/8 text-info",
  retrying: "border-warning/40 bg-warning/8 text-warning",
  completed: "border-success/35 bg-success/8 text-success",
  failed: "border-danger/40 bg-danger/8 text-danger",
  skipped: "border-warning/40 bg-warning/8 text-warning",
};

export function SceneProgress({ scenes }: { scenes: SceneProgressItem[] }) {
  if (scenes.length === 0) return null;

  const done = scenes.filter((s) => s.status === "completed").length;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="overline text-ink-muted">Rooms</h2>
        <p className="caption tabular text-ink-muted">
          {done} of {scenes.length} filmed
        </p>
      </div>

      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {scenes.map((scene) => {
          const Icon = ICON[scene.status] ?? Loader2;
          const spinning = scene.status === "running" || scene.status === "queued" || scene.status === "pending";

          return (
            <li
              key={scene.position}
              className={cn(
                "flex items-center gap-3 rounded-md border px-3.5 py-2.5",
                "transition-colors duration-200 ease-out",
                TONE[scene.status] ?? TONE.pending,
              )}
            >
              <span
                className="flex size-6 shrink-0 items-center justify-center rounded-full bg-surface-raised/70"
                aria-hidden
              >
                <Icon className={cn("size-3.5", spinning && "animate-spin")} />
              </span>

              <span className="flex min-w-0 flex-1 flex-col">
                <span className="body-sm truncate font-medium text-ink-soft">
                  {roomLabel(scene.roomType)}
                </span>
                <span className="caption text-ink-muted">
                  Scene {scene.position} · {sceneStatusLabel(scene.status)}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
