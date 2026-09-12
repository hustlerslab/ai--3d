"use client";

import { Check, Loader2, RotateCcw } from "lucide-react";

import { Button } from "@/components/shared/button";

/**
 * The decision the whole flow builds to: keep it, or change one room.
 *
 * Rejection is not a dead end here. readme2 §16 and §17 are clear that "no"
 * means "one room is wrong", not "throw it away" — so the reject path opens the
 * room picker rather than discarding minutes of finished work.
 *
 * Once approved the panel resolves in place instead of disappearing, matching
 * how ActionCard handles a decided action elsewhere in the portal: a control
 * that vanishes on click leaves people unsure whether it registered.
 */
export function ApprovalPanel({
  approved,
  revisionCount,
  onApprove,
  onReject,
  pending = false,
  disabled = false,
}: {
  approved: boolean;
  revisionCount: number;
  onApprove: () => void;
  onReject: () => void;
  pending?: boolean;
  disabled?: boolean;
}) {
  if (approved) {
    return (
      <section className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-success/35 bg-success/8 px-6 py-5">
        <span
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-success/15 text-success"
          aria-hidden
        >
          <Check className="size-4" />
        </span>
        <div className="flex flex-col gap-0.5">
          <p className="body font-medium text-ink-soft">Walkthrough approved</p>
          <p className="caption text-ink-muted">
            {revisionCount > 0
              ? `Approved after ${revisionCount} ${revisionCount === 1 ? "revision" : "revisions"}. You can still re-film a room below.`
              : "Ready to share. You can still re-film a room below if you change your mind."}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-gold/30 bg-gold/6 px-6 py-5">
      <div className="flex flex-col gap-1">
        <h2 className="body font-medium text-ink-soft">How does it look?</h2>
        <p className="body-sm text-ink-muted">
          Approve it, or pick the one room you would like re-filmed. Every other room stays exactly
          as it is.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={onApprove} disabled={pending || disabled}>
          {pending ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Check className="size-3.5" aria-hidden />
          )}
          {pending ? "Approving" : "Approve walkthrough"}
        </Button>

        <Button variant="secondary" onClick={onReject} disabled={pending || disabled}>
          <RotateCcw className="size-3.5" aria-hidden />
          Change a room
        </Button>

        {revisionCount > 0 ? (
          <p className="caption tabular text-ink-muted">
            {revisionCount} {revisionCount === 1 ? "revision" : "revisions"} so far
          </p>
        ) : null}
      </div>
    </section>
  );
}
