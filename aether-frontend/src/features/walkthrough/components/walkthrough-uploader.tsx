"use client";

import { useCallback, useId, useRef, useState } from "react";
import { ImagePlus, Upload } from "lucide-react";

import { Button } from "@/components/shared/button";
import { cn } from "@/lib/utils";

import type { PendingImage } from "../types/walkthrough";

/**
 * The drop zone that starts a walkthrough.
 *
 * Deliberately a `<label>` wrapping a real file input rather than a div with a
 * click handler: that gives keyboard access, the native file picker, and screen
 * reader semantics for free, which a div would have to reimplement badly.
 *
 * Drag state is tracked with a counter, not a boolean. `dragleave` fires when
 * the pointer crosses onto a *child* element, so a boolean flickers the
 * highlight off mid-drag as the cursor passes over the icon.
 */
export function WalkthroughUploader({
  images,
  onAddFiles,
  disabled = false,
  busy = false,
}: {
  images: PendingImage[];
  onAddFiles: (files: FileList | File[]) => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      if (disabled) return;

      const files = event.dataTransfer?.files;
      if (files && files.length > 0) onAddFiles(files);
    },
    [disabled, onAddFiles],
  );

  const handleDragEnter = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (disabled) return;
      dragDepth.current += 1;
      setDragging(true);
    },
    [disabled],
  );

  const handleDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setDragging(false);
    }
  }, []);

  const count = images.length;

  return (
    <div className="flex flex-col gap-4">
      <label
        htmlFor={inputId}
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed px-8 py-14 text-center",
          "transition-colors duration-150 ease-out",
          "focus-within:ring-2 focus-within:ring-gold focus-within:ring-offset-2 focus-within:ring-offset-surface",
          dragging
            ? "border-gold bg-gold/8"
            : "border-tan bg-surface-raised hover:border-ink-muted hover:bg-sand/25",
          disabled && "pointer-events-none opacity-50",
        )}
      >
        <span
          className={cn(
            "flex size-14 items-center justify-center rounded-full transition-colors duration-150",
            dragging ? "bg-gold/20 text-gold" : "bg-sand text-ink-muted",
          )}
          aria-hidden
        >
          {dragging ? <Upload className="size-6" /> : <ImagePlus className="size-6" />}
        </span>

        <span className="flex flex-col gap-1.5">
          <span className="body font-medium text-ink-soft">
            {dragging ? "Drop your photos here" : "Add photos of the property"}
          </span>
          <span className="body-sm text-ink-muted">
            Drag them in, or click to browse. JPEG, PNG, or WebP — up to 50 photos, 20 MB each.
          </span>
          {/* One photo produces one four-second scene. Saying so here is
              cheaper than letting someone discover it after a full render. */}
          <span className="caption text-ink-muted">
            One room per photo, about four seconds each. Six to ten photos make a
            walkthrough that reads as a tour.
          </span>
        </span>

        <input
          ref={inputRef}
          id={inputId}
          type="file"
          multiple
          accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
          className="sr-only"
          disabled={disabled}
          onChange={(event) => {
            if (event.target.files) onAddFiles(event.target.files);
            // Reset so re-picking the same file fires change again
            event.target.value = "";
          }}
        />
      </label>

      {count > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="caption tabular text-ink-muted">
            {count} {count === 1 ? "photo" : "photos"} ready
          </p>
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled || busy}
            onClick={() => inputRef.current?.click()}
          >
            <ImagePlus className="size-3.5" aria-hidden />
            Add more
          </Button>
        </div>
      ) : null}
    </div>
  );
}
