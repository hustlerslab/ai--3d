"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, Download } from "lucide-react";

import { cn } from "@/lib/utils";

import { downloadUrl, videoUrl } from "../api/walkthrough-api";

/**
 * Plays the finished walkthrough.
 *
 * Two details do the real work here:
 *
 *   The `key` on <video> is the version. React reuses a DOM node across
 *   re-renders, and a <video> whose `src` attribute changes keeps playing the
 *   already-buffered file. After a revision that means the user watches the
 *   OLD cut and concludes the revision failed. Keying on version forces a new
 *   element, so the browser refetches. The engine also sends no-cache headers
 *   and a versioned ETag; this is the client half of the same guarantee.
 *
 *   The download is a plain <a download>, not a fetch-and-blob. The engine
 *   streams with range support and the correct Content-Disposition, so the
 *   browser's own downloader handles a large file better than anything built
 *   here — and never buffers hundreds of megabytes into a tab.
 */
export function WalkthroughPlayer({
  walkthroughId,
  version,
  poster,
  className,
}: {
  walkthroughId: string;
  version: number;
  poster?: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  // A new version means a genuinely different file; clear any prior failure so
  // a transient error does not stick to the replacement.
  useEffect(() => {
    setFailed(false);
  }, [version]);

  const src = videoUrl(walkthroughId, version);

  return (
    <figure className={cn("flex flex-col gap-3", className)}>
      <div className="overflow-hidden rounded-lg border border-border bg-ink shadow-md">
        {failed ? (
          <div className="flex aspect-video flex-col items-center justify-center gap-3 px-6 text-center">
            <AlertCircle className="size-6 text-cream/70" aria-hidden />
            <p className="body-sm text-cream/80">This walkthrough could not be played.</p>
            <p className="caption text-cream/50">
              The engine may have stopped, or the file may still be assembling.
            </p>
          </div>
        ) : (
          <video
            // Forces a fresh element — see the note above.
            key={`${walkthroughId}-v${version}`}
            ref={videoRef}
            src={src}
            poster={poster}
            controls
            playsInline
            preload="metadata"
            className="aspect-video w-full bg-ink"
            onError={() => setFailed(true)}
          >
            Your browser cannot play this video.
          </video>
        )}
      </div>

      <figcaption className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p className="caption text-ink-muted">
          Silent master, 16:9. {version > 1 ? `Version ${version}.` : null}
        </p>

        <a
          href={downloadUrl(walkthroughId, version)}
          download
          className={cn(
            "pressable inline-flex items-center gap-2 rounded-pill border border-tan px-3.5 py-1.5 text-xs font-medium",
            "text-ink-soft transition-all duration-150 ease-out",
            "hover:-translate-y-px hover:border-ink-muted hover:bg-sand/40 active:translate-y-0",
            "focus-visible:ring-2 focus-visible:ring-gold focus-visible:ring-offset-2 focus-visible:outline-none",
          )}
        >
          <Download className="size-3.5" aria-hidden />
          Download
        </a>
      </figcaption>
    </figure>
  );
}
