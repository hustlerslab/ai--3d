"use client";

import { AlertCircle, Check, Loader2, RefreshCw } from "lucide-react";

import type { EventDto, JobDto } from "../types";

const STATUS_LABEL: Record<JobDto["status"], string> = {
  QUEUED: "Queued",
  RUNNING: "Working",
  SUCCEEDED: "Done",
  FAILED: "Failed",
  RETRYING: "Retrying",
  CANCELLED: "Cancelled",
};

function stageLabel(stage: string): string {
  return stage
    .replace(/^(analyze|plan|build|tour|resolve)\./, "")
    .replace(/[._]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * What the engine is doing right now: the job's status plus its event trail
 * (stage names in plain words, durations, warnings). A failed job offers a
 * retry, which resumes from the last checkpoint on the backend.
 */
export function JobProgress({
  title,
  job,
  events,
  error,
  onRetry,
  compact = false,
}: {
  title: string;
  job: JobDto | null;
  events: EventDto[];
  error?: string | null;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const status = job?.status ?? "QUEUED";
  const busy = status === "QUEUED" || status === "RUNNING" || status === "RETRYING";
  const failed = status === "FAILED" || Boolean(error && !busy);
  const visible = events.filter((e) => !["queued", "started"].includes(e.status));

  return (
    <section
      className={`flex flex-col gap-3 rounded-lg border p-4 ${failed ? "border-danger/35 bg-danger/6" : busy ? "border-gold/40 bg-gold/5" : "border-success/30 bg-success/6"}`}
      aria-live="polite"
    >
      <div className="flex items-center gap-2">
        {failed ? (
          <AlertCircle className="size-4 text-danger" aria-hidden />
        ) : busy ? (
          <Loader2 className="size-4 animate-spin text-gold" aria-hidden />
        ) : (
          <Check className="size-4 text-success" aria-hidden />
        )}
        <p className="body-sm font-medium text-ink-soft">{title}</p>
        <span className="ml-auto caption text-ink-muted">
          {STATUS_LABEL[status]}
          {job && job.attempt > 1 ? ` · attempt ${job.attempt}/${job.max_attempts}` : ""}
        </span>
      </div>
      {!compact && visible.length > 0 ? (
        <ol className="flex flex-col gap-1">
          {visible.slice(-8).map((e) => (
            <li key={e.event_id} className="flex items-baseline gap-2 caption text-ink-muted">
              <span className="w-32 shrink-0 truncate font-medium text-ink-soft">{stageLabel(e.stage)}</span>
              <span className="truncate">{e.message || e.status}</span>
              {e.duration_ms > 500 ? <span className="ml-auto shrink-0 tabular">{(e.duration_ms / 1000).toFixed(1)}s</span> : null}
            </li>
          ))}
        </ol>
      ) : null}
      {failed ? (
        <div className="flex flex-col gap-2">
          <p className="body-sm text-ink-soft">{error || job?.error}</p>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="flex w-fit items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted"
            >
              <RefreshCw className="size-3.5" /> Try again
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
