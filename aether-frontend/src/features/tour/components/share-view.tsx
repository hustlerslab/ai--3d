"use client";

/**
 * Public walkthrough page: the client opens a link and sees the tour.
 * Reads only the tour package; the Explore tab reuses the 3D viewer.
 */

import { useEffect, useState } from "react";

import { Walkthrough3DView } from "@/features/walkthrough3d/components/walkthrough3d-view";

import { fileUrl, getTour } from "../api/tour-api";
import { setShareToken } from "../share-token";
import { TourApiError, type TourPackage } from "../types";
import { PanoramaTour } from "./panorama-tour";

type Mode = "tour" | "explore" | "film";

export function FilmPlayer({ pkg, className }: { pkg: TourPackage; className?: string }) {
  if (!pkg.film?.mp4_url) return <p className="text-sm text-ink-muted">No film rendered yet.</p>;
  return (
    <video
      className={className}
      controls
      playsInline
      preload="metadata"
      poster={pkg.film.poster_url ? fileUrl(pkg.film.poster_url) : undefined}
      src={fileUrl(pkg.film.mp4_url)}
    >
      Your browser cannot play this video.
    </video>
  );
}

export function ShareView({ projectId, token }: { projectId: string; token?: string }) {
  const [pkg, setPkg] = useState<TourPackage | null>(null);
  const [error, setError] = useState<{ code: string; message: string; status: number } | null>(null);
  const [mode, setMode] = useState<Mode>("tour");

  // Set before the first fetch, and before any <img> or texture URL is built.
  // Every asset on this page authorises through it - see features/tour/share-token.
  setShareToken(token);

  useEffect(() => {
    const controller = new AbortController();
    setPkg(null);
    setError(null);
    getTour(projectId, controller.signal, token)
      .then(setPkg)
      .catch((err) => {
        if (controller.signal.aborted) return;
        const e = err instanceof TourApiError ? err : new TourApiError("UNKNOWN", String(err), 0);
        setError({ code: e.code, message: e.message, status: e.status });
      });
    return () => controller.abort();
  }, [projectId, token]);

  if (error) {
    return (
      <div className="mx-auto max-w-lg px-6 py-24 text-center">
        <p className="font-serif text-2xl">
          {error.status === 401
            ? "This link doesn’t work"
            : "This walkthrough isn’t ready yet"}
        </p>
        <p className="mt-3 text-sm text-ink-muted">
          {error.code === "TOUR_NOT_READY"
            ? "The panoramas are still being rendered. Check back in a few minutes."
            : error.status === 401
              ? "This link has expired or been turned off. Ask whoever shared it with you for a new one."
              : error.message}
        </p>
      </div>
    );
  }
  if (!pkg) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-sm text-ink-muted" aria-live="polite">
        Loading walkthrough…
      </div>
    );
  }

  const styleName = pkg.style?.name?.replace(/_/g, " ");
  return (
    <div className="flex h-[calc(100vh-64px)] min-h-[560px] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div>
          <h1 className="font-serif text-xl leading-tight">{pkg.project_name}</h1>
          <p className="text-xs text-ink-muted">
            {styleName ? `${styleName} · ` : ""}
            {pkg.rooms.length} rooms · {pkg.tour.nodes.length} viewpoints
            {pkg.style?.palette?.length ? (
              <span className="ml-2 inline-flex gap-1 align-middle">
                {pkg.style.palette.slice(0, 5).map((c) => (
                  <span key={c} className="inline-block h-3 w-3 rounded-full border border-black/10" style={{ background: c }} title={c} />
                ))}
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex gap-1 rounded-full border border-black/10 p-1" role="tablist" aria-label="View mode">
          {(["tour", "explore", ...(pkg.film?.mp4_url ? (["film"] as Mode[]) : [])] as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              type="button"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
                mode === m ? "bg-black text-white" : "text-ink-muted hover:text-black"
              }`}
            >
              {m === "tour" ? "360° Tour" : m === "explore" ? "Explore in 3D" : "Film"}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 px-5 pb-5">
        {mode === "tour" ? (
          <PanoramaTour pkg={pkg} autoplay className="h-full w-full rounded-2xl" />
        ) : mode === "film" ? (
          <div className="flex h-full items-center justify-center rounded-2xl bg-black">
            <FilmPlayer pkg={pkg} className="max-h-full w-full rounded-2xl" />
          </div>
        ) : (
          <div className="h-full overflow-auto rounded-2xl border border-black/10">
            <Walkthrough3DView sceneId={pkg.explore.scene_id} />
          </div>
        )}
      </div>
    </div>
  );
}
