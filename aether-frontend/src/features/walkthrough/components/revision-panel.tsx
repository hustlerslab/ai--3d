"use client";

import { useState } from "react";
import { Loader2, Play, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/shared/button";
import { cn } from "@/lib/utils";

import { sceneVideoUrl } from "../api/walkthrough-api";
import type { WalkthroughScene } from "../types/walkthrough";
import { roomLabel } from "../utils/walkthrough-helpers";

/**
 * Pick the one room to re-film.
 *
 * The user has just watched a two-minute video and now has to say which part
 * was wrong. Room names alone are not enough to be sure — "Bedroom" could be
 * either of two. So each room can be previewed in place before committing,
 * which is why the engine exposes per-scene streaming at all.
 *
 * Only completed rooms are selectable. Offering to re-film a room that never
 * rendered would send the user down a path that cannot succeed.
 */
export function RevisionPanel({
  walkthroughId,
  scenes,
  version,
  onRevise,
  onCancel,
  pending = false,
}: {
  walkthroughId: string;
  scenes: WalkthroughScene[];
  version: number;
  onRevise: (position: number) => void;
  onCancel: () => void;
  pending?: boolean;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [previewing, setPreviewing] = useState<number | null>(null);

  const selectable = scenes.filter((scene) => scene.status === "completed");

  if (selectable.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-surface-raised px-6 py-5">
        <p className="body-sm text-ink-muted">
          No finished rooms are available to re-film yet.
        </p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-5 rounded-lg border border-copper/35 bg-copper/6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="flex flex-col gap-1">
          <h2 className="body font-medium text-ink-soft">Which room should we re-film?</h2>
          <p className="body-sm text-ink-muted">
            Only the room you pick is regenerated — the rest of the walkthrough is untouched.
            Preview any room first if you are not sure.
          </p>
        </div>

        <Button variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
          <X className="size-3.5" aria-hidden />
          Cancel
        </Button>
      </div>

      <fieldset className="flex flex-col gap-2" disabled={pending}>
        <legend className="sr-only">Choose a room to re-film</legend>

        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {selectable.map((scene) => {
            const isSelected = selected === scene.position;
            const isPreviewing = previewing === scene.position;

            return (
              <li key={scene.position} className="flex flex-col">
                <label
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-md border px-3.5 py-3",
                    "transition-colors duration-150 ease-out",
                    "focus-within:ring-2 focus-within:ring-gold focus-within:ring-offset-2 focus-within:ring-offset-surface",
                    isSelected
                      ? "border-copper bg-surface-raised shadow-sm"
                      : "border-border bg-surface-raised/60 hover:border-tan hover:bg-surface-raised",
                    pending && "cursor-not-allowed opacity-60",
                  )}
                >
                  <input
                    type="radio"
                    name="revision-room"
                    value={scene.position}
                    checked={isSelected}
                    onChange={() => setSelected(scene.position)}
                    className="size-4 shrink-0 accent-copper"
                  />

                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="body-sm font-medium text-ink-soft">
                      {roomLabel(scene.roomType)}
                    </span>
                    <span className="caption text-ink-muted">
                      Scene {scene.position}
                      {scene.cameraMove ? ` · ${scene.cameraMove.replace(/[-_]/g, " ")}` : null}
                    </span>
                  </span>

                  <button
                    type="button"
                    onClick={(event) => {
                      event.preventDefault();
                      setPreviewing(isPreviewing ? null : scene.position);
                    }}
                    aria-label={`${isPreviewing ? "Hide" : "Preview"} ${roomLabel(scene.roomType)}`}
                    aria-expanded={isPreviewing}
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-full border border-tan",
                      "text-ink-muted transition-colors duration-150",
                      "hover:border-ink-muted hover:bg-sand/50 hover:text-ink-soft",
                      "focus-visible:ring-2 focus-visible:ring-gold focus-visible:outline-none",
                    )}
                  >
                    {isPreviewing ? <X className="size-3" aria-hidden /> : <Play className="size-3" aria-hidden />}
                  </button>
                </label>

                {isPreviewing ? (
                  <video
                    key={`scene-${scene.position}-v${version}`}
                    src={sceneVideoUrl(walkthroughId, scene.position, version)}
                    controls
                    autoPlay
                    playsInline
                    preload="metadata"
                    className="mt-2 w-full rounded-md border border-border bg-ink"
                  >
                    Your browser cannot play this clip.
                  </video>
                ) : null}
              </li>
            );
          })}
        </ul>
      </fieldset>

      <div className="flex flex-wrap items-center gap-3 border-t border-copper/20 pt-4">
        <Button
          variant="primary"
          onClick={() => selected !== null && onRevise(selected)}
          disabled={selected === null || pending}
        >
          {pending ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <RotateCcw className="size-3.5" aria-hidden />
          )}
          {pending ? "Starting" : "Re-film this room"}
        </Button>

        <p className="caption text-ink-muted">
          {selected === null
            ? "Pick a room to continue."
            : `${roomLabel(selectable.find((s) => s.position === selected)?.roomType ?? null)} will be regenerated with a different camera move.`}
        </p>
      </div>
    </section>
  );
}
