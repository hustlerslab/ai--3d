"use client";

import { AlertTriangle, X } from "lucide-react";

import { cn } from "@/lib/utils";

import type { PendingImage, UploadRejection } from "../types/walkthrough";

/**
 * Thumbnails of what the user is about to upload, each removable.
 *
 * Uses a plain `<img>`, not `next/image`. These are `blob:` object URLs for
 * files that exist only in this browser session — there is nothing for the
 * Next image optimiser to fetch, and `next.config.ts` deliberately allows no
 * remote patterns.
 *
 * Files that fail local validation stay in the grid rather than vanishing.
 * A photo that silently disappears reads as a bug; one shown dimmed with the
 * reason attached tells the user what to fix.
 */
export function ImagePreviewGrid({
  images,
  onRemove,
  rejections = [],
  disabled = false,
}: {
  images: PendingImage[];
  onRemove: (id: string) => void;
  /** Server-side rejections from the last upload attempt. */
  rejections?: UploadRejection[];
  disabled?: boolean;
}) {
  if (images.length === 0 && rejections.length === 0) return null;

  const invalidCount = images.filter((img) => img.error !== null).length;

  return (
    <div className="flex flex-col gap-4">
      {images.length > 0 ? (
        <>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {images.map((image) => (
              <li
                key={image.id}
                className={cn(
                  "group relative overflow-hidden rounded-md border bg-surface-raised shadow-sm",
                  image.error ? "border-danger/40" : "border-border",
                )}
              >
                <div className="aspect-4/3 overflow-hidden bg-sand">
                  {/* eslint-disable-next-line @next/next/no-img-element -- blob: URL, nothing for the optimiser to fetch */}
                  <img
                    src={image.previewUrl}
                    alt={image.file.name}
                    className={cn(
                      "size-full object-cover",
                      image.error && "opacity-40 grayscale",
                    )}
                  />
                </div>

                <div className="flex flex-col gap-0.5 px-2.5 py-2">
                  <p className="caption truncate text-ink-soft" title={image.file.name}>
                    {image.file.name}
                  </p>
                  {image.error ? (
                    <p className="caption flex items-start gap-1 text-danger">
                      <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
                      <span>{image.error}</span>
                    </p>
                  ) : (
                    <p className="caption tabular text-ink-muted">{image.sizeLabel}</p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => onRemove(image.id)}
                  disabled={disabled}
                  aria-label={`Remove ${image.file.name}`}
                  className={cn(
                    "absolute top-2 right-2 flex size-7 items-center justify-center rounded-full",
                    "bg-ink/70 text-cream backdrop-blur-sm",
                    "transition-opacity duration-150 ease-out",
                    // Always visible on touch, where there is no hover to reveal it
                    "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
                    "[@media(hover:none)]:opacity-100",
                    "hover:bg-danger disabled:pointer-events-none disabled:opacity-30",
                    "focus-visible:ring-2 focus-visible:ring-gold focus-visible:outline-none",
                  )}
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </li>
            ))}
          </ul>

          {invalidCount > 0 ? (
            <p className="caption flex items-center gap-1.5 text-danger">
              <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
              {invalidCount} {invalidCount === 1 ? "photo cannot" : "photos cannot"} be used and{" "}
              {invalidCount === 1 ? "will" : "will"} be skipped.
            </p>
          ) : null}
        </>
      ) : null}

      {rejections.length > 0 ? (
        <div className="rounded-md border border-warning/30 bg-warning/8 px-4 py-3">
          <p className="caption font-medium text-ink-soft">
            {rejections.length} {rejections.length === 1 ? "photo was" : "photos were"} set aside
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {rejections.map((rejection, index) => (
              <li key={`${rejection.originalName}-${index}`} className="caption text-ink-muted">
                <span className="text-ink-soft">{rejection.originalName}</span> — {rejection.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
