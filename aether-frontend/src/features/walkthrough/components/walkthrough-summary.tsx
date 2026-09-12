"use client";

import { Check, Minus, TriangleAlert } from "lucide-react";

import { StatusPill } from "@/components/shared/status-pill";
import { cn } from "@/lib/utils";

import type { QaCheck, WalkthroughCosts, QaResult } from "../types/walkthrough";
import { formatCost } from "../utils/walkthrough-helpers";

/**
 * The quality report and generation cost for a finished walkthrough.
 *
 * Two constraints from readme2 shape the copy:
 *
 *   §49 — report the automated checks, but do not claim the walkthrough looks
 *   good. These checks verify that a valid, complete, correctly-ordered video
 *   exists. They say nothing about whether the kitchen is flattering, and the
 *   heading says so explicitly rather than letting "100%" imply otherwise.
 *
 *   §48 — never invent or fake a price. A null total renders no cost block at
 *   all, and an estimate is always labelled as one.
 */

/** Engine check names are snake_case; these are what a person should read. */
const CHECK_LABELS: Record<string, string> = {
  output_exists: "Video file created",
  file_size: "File size looks right",
  ffprobe: "Video is readable",
  duration_reasonable: "Duration is sensible",
  scene_count: "All rooms included",
  no_missing_scenes: "No missing room clips",
  scene_order: "Rooms in walkthrough order",
  social_ratio_exists: "Vertical cut created",
  skipped_rooms: "Rooms skipped",
};

function checkLabel(name: string): string {
  return CHECK_LABELS[name] ?? name.replace(/_/g, " ");
}

function CheckRow({ check }: { check: QaCheck }) {
  const isPass = check.result === "PASS";
  const isFail = check.result === "FAIL";

  const Icon = isPass ? Check : isFail ? TriangleAlert : Minus;

  return (
    <li className="flex items-start gap-2.5">
      <span
        className={cn(
          "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full",
          isPass && "bg-success/15 text-success",
          isFail && "bg-danger/15 text-danger",
          !isPass && !isFail && "bg-sand text-ink-muted",
        )}
        aria-hidden
      >
        <Icon className="size-2.5" />
      </span>

      <span className="flex min-w-0 flex-col">
        <span className="body-sm text-ink-soft">{checkLabel(check.name)}</span>
        <span className="caption text-ink-muted">{check.detail}</span>
      </span>

      <span className="sr-only">{check.result}</span>
    </li>
  );
}

export function WalkthroughSummary({
  qa,
  costs,
  revisionCount,
}: {
  qa: QaResult;
  costs: WalkthroughCosts | null;
  revisionCount: number;
}) {
  const costLabel = formatCost(costs);
  const checks = qa.checks ?? [];
  const hasScore = qa.score !== null && qa.score !== undefined;

  // Derived here rather than trusting qa.hasWarnings, so a record written by an
  // older engine build still renders its warnings.
  const warnings = checks.filter((check) => check.result === "WARN");
  const hasWarnings = warnings.length > 0;
  const scoredChecks = checks.filter((check) => check.result !== "WARN");

  if (!hasScore && checks.length === 0 && !costLabel) return null;

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-border bg-surface-raised p-6 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h2 className="overline text-ink-muted">Walkthrough quality</h2>
        {hasScore ? (
          <StatusPill
            label={
              !qa.passed
                ? `Checks incomplete — ${qa.score}%`
                : hasWarnings
                  ? `Passed with notes — ${qa.score}%`
                  : `Checks passed — ${qa.score}%`
            }
            tone={!qa.passed ? "danger" : hasWarnings ? "warning" : "success"}
            size="sm"
          />
        ) : null}
      </div>

      {/* Warnings are not scored, so without this a warned result would read as
          a clean pass — which is how a one-room clip came to show "100%". */}
      {warnings.length > 0 ? (
        <ul className="flex flex-col gap-2 rounded-md border border-warning/30 bg-warning/8 px-4 py-3">
          {warnings.map((warning) => (
            <li key={warning.name} className="flex items-start gap-2.5">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
              <span className="caption text-ink-soft">{warning.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {/* Warnings are called out above, so the grid lists only the pass/fail
          checks — repeating them reads as two separate problems. */}
      {scoredChecks.length > 0 ? (
        <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {scoredChecks.map((check) => (
            <CheckRow key={check.name} check={check} />
          ))}
        </ul>
      ) : null}

      <p className="caption text-ink-muted">
        These checks confirm the video is complete, playable, and in the right order. They do not
        judge how the rooms look — that part is for you.
      </p>

      {(costLabel || revisionCount > 0) && (
        <dl className="flex flex-wrap gap-x-10 gap-y-3 border-t border-border pt-4">
          {costLabel ? (
            <div className="flex flex-col gap-0.5">
              <dt className="overline text-ink-muted">
                {costs?.estimated ? "Estimated generation cost" : "Generation cost"}
              </dt>
              <dd className="body-sm tabular text-ink-soft">{costLabel}</dd>
            </div>
          ) : null}

          {revisionCount > 0 ? (
            <div className="flex flex-col gap-0.5">
              <dt className="overline text-ink-muted">Revisions</dt>
              <dd className="body-sm tabular text-ink-soft">
                {revisionCount} {revisionCount === 1 ? "room re-filmed" : "rooms re-filmed"}
              </dd>
            </div>
          ) : null}
        </dl>
      )}
    </section>
  );
}
