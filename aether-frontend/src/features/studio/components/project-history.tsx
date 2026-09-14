"use client";

/**
 * Every project the engine holds, so a browser session is not the only way back
 * to one.
 *
 * Before this, the Studio kept a single project id in sessionStorage: close the
 * tab and the work was unreachable even though all of it was still on disk.
 * This lists them, most recently touched first, and hands the chosen id back to
 * the Studio, which resumes it at the furthest stage it reached.
 */

import { Box, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { StatusPill, type StatusTone } from "@/components/shared/status-pill";
import { formatDate } from "@/lib/format";

import { deleteProject, listProjects } from "../api/projects-api";
import { stageLabel } from "../stages";
import type { ProjectRecord, ProjectStage } from "../types";
import { VERTICAL_OPTIONS } from "../verticals";

const STAGE_TONE: Partial<Record<ProjectStage, StatusTone>> = {
  COMPLETED: "success",
  PREVIEW_RENDERING: "success",
  FAILED: "danger",
  CREATED: "neutral",
};

const verticalLabel = (v: string): string =>
  VERTICAL_OPTIONS.find((o) => o.value === v)?.label ?? v;

export interface ProjectHistoryProps {
  /** Highlighted as "open"; usually the project the Studio currently holds. */
  activeProjectId?: string | null;
  onOpen: (projectId: string) => void;
  onCreateNew?: () => void;
  /** Told which project went, so the Studio can let go of it if it was open. */
  onDeleted?: (projectId: string) => void;
}

export function ProjectHistory({ activeProjectId, onOpen, onCreateNew, onDeleted }: ProjectHistoryProps) {
  const [projects, setProjects] = useState<ProjectRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [kept, setKept] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      setProjects(await listProjects(signal));
    } catch (e) {
      if ((e as { name?: string }).name === "AbortError") return;
      setError(e instanceof Error ? e.message : "Could not load your projects.");
    } finally {
      setLoading(false);
    }
  }, []);

  /** Delete after an explicit yes, then say what was kept.
   *
   *  The confirmation names the project and spells out that the moodboard and
   *  any 3D pieces survive — deleting is otherwise indistinguishable from
   *  losing an afternoon of generation, and this is the one irreversible
   *  control on the screen. */
  const remove = useCallback(
    async (p: ProjectRecord) => {
      const label = p.name || "this untitled project";
      if (!window.confirm(
        `Delete ${label}?\n\nThis cannot be undone. The project and `
        + `its progress are removed. Your uploaded photos, its moodboard images and `
        + `any 3D pieces already built are kept, so they can be reused.`)) {
        return;
      }
      setDeleting(p.project_id);
      setError(null);
      try {
        const res = await deleteProject(p.project_id);
        const pieces = res.kept.asset_ids.length;
        const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;
        const parts = [plural(res.kept.references ?? 0, "uploaded photo"),
                       plural(res.kept.moodboard_rooms, "moodboard image")];
        if (pieces) parts.push(plural(pieces, "3D piece"));
        setKept(`Deleted ${label}. Kept ${parts.join(", ")}.`);
        onDeleted?.(p.project_id);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not delete that project.");
      } finally {
        setDeleting(null);
      }
    },
    [load, onDeleted],
  );

  useEffect(() => {
    const ac = new AbortController();
    void load(ac.signal);
    return () => ac.abort();
  }, [load]);

  return (
    <section aria-labelledby="project-history-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 id="project-history-heading" className="body font-medium text-ink">
            Your projects
          </h3>
          <p className="caption text-ink-muted">
            {projects === null
              ? "Loading…"
              : projects.length === 0
                ? "Nothing here yet — your first project will appear once you create it."
                : `${projects.length} project${projects.length === 1 ? "" : "s"} on this engine. Open one to pick up where it stopped.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted transition-colors hover:bg-muted hover:text-ink-soft disabled:opacity-50"
          >
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
            Refresh
          </button>
          {onCreateNew ? (
            <button
              type="button"
              onClick={onCreateNew}
              className="flex items-center gap-1.5 rounded-md bg-gold px-3 py-1.5 body-sm font-medium text-ink transition-opacity hover:opacity-90"
            >
              <Plus className="size-3.5" aria-hidden />
              New project
            </button>
          ) : null}
        </div>
      </div>

      {error ? (
        <div role="alert" className="rounded-md border px-4 py-3 body-sm text-ink-soft">
          <p className="font-medium text-ink">Could not load your projects</p>
          <p className="mt-1 text-ink-muted">{error}</p>
          <button type="button" onClick={() => void load()} className="mt-2 underline underline-offset-2">
            Try again
          </button>
        </div>
      ) : null}

      {/* Says what survived, because "deleted" on its own reads as "all of it
          is gone" — and the moodboard and generated pieces are not. */}
      {kept ? (
        <div role="status" className="flex items-start justify-between gap-3 rounded-md border border-gold/40 bg-gold/5 px-4 py-3 body-sm text-ink-soft">
          <span>{kept}</span>
          <button type="button" onClick={() => setKept(null)} aria-label="Dismiss" className="shrink-0 text-ink-muted hover:text-ink">
            ×
          </button>
        </div>
      ) : null}

      {projects && projects.length > 0 ? (
        <ul className="divide-y rounded-md border">
          {projects.map((p) => {
            const isActive = p.project_id === activeProjectId;
            const scenes = p.scene_ids.length;
            return (
              <li key={p.project_id} className={`flex items-center ${isActive ? "bg-gold/10" : ""}`}>
                <button
                  type="button"
                  onClick={() => onOpen(p.project_id)}
                  aria-current={isActive ? "true" : undefined}
                  className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-gold"
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex items-center gap-2">
                      <span className="truncate body-sm font-medium text-ink">{p.name || "Untitled project"}</span>
                      {isActive ? (
                        <span className="shrink-0 rounded-sm border border-gold px-1 caption text-ink-soft">Open</span>
                      ) : null}
                    </span>
                    <span className="truncate caption text-ink-muted">
                      {verticalLabel(p.vertical)}
                      {scenes > 0 ? ` · ${scenes} scene${scenes === 1 ? "" : "s"}` : ""}
                      {p.description ? ` · ${p.description}` : ""}
                    </span>
                  </span>
                  <span className="shrink-0 caption tabular text-ink-muted">{formatDate(p.updated_at)}</span>
                  <StatusPill label={stageLabel(p.stage)} tone={STAGE_TONE[p.stage] ?? "info"} size="sm" />
                  <Box className="size-3.5 shrink-0 text-ink-muted" aria-hidden />
                </button>
                {/* Its own control, beside the row rather than inside it: a
                    button cannot be nested in a button, and a delete that can
                    be hit while aiming for "open" is worse than no delete. */}
                <button
                  type="button"
                  onClick={() => void remove(p)}
                  disabled={deleting === p.project_id}
                  title="Delete this project (the moodboard and any 3D pieces are kept)"
                  aria-label={`Delete ${p.name || "untitled project"}`}
                  className="mr-2 shrink-0 rounded-md p-2 text-ink-muted transition-colors hover:bg-danger/10 hover:text-danger focus-visible:outline-2 focus-visible:outline-gold disabled:opacity-40"
                >
                  {deleting === p.project_id
                    ? <Loader2 className="size-4 animate-spin" />
                    : <Trash2 className="size-4" />}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
