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

import { Box, Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { StatusPill, type StatusTone } from "@/components/shared/status-pill";
import { formatDate } from "@/lib/format";

import { listProjects } from "../api/projects-api";
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
}

export function ProjectHistory({ activeProjectId, onOpen, onCreateNew }: ProjectHistoryProps) {
  const [projects, setProjects] = useState<ProjectRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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

      {projects && projects.length > 0 ? (
        <ul className="divide-y rounded-md border">
          {projects.map((p) => {
            const isActive = p.project_id === activeProjectId;
            const scenes = p.scene_ids.length;
            return (
              <li key={p.project_id}>
                <button
                  type="button"
                  onClick={() => onOpen(p.project_id)}
                  aria-current={isActive ? "true" : undefined}
                  className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-gold ${
                    isActive ? "bg-gold/10" : ""
                  }`}
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
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
