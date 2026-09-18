"use client";

import { Check, Loader2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fileUrl } from "../api/projects-api";
import { buildElementImages, humanType } from "../element-images";
import type { ElementImageSetDto } from "../types";

function human(id: string): string {
  return id.replace(/_/g, " ");
}

/**
 * Element-first, stage 1: the pieces the room will hold, each pictured on its
 * own BEFORE any room is painted. What is shown is what the backend decided
 * from the photos and the brief; the picture is the same one Meshy will get.
 *
 * The decision made here - build it, or leave it out - is the decision. It is
 * saved on the canonical piece and carried onto the moodboard reading later,
 * so nobody is asked about the same stool twice.
 */
export function ElementImagesReview({
  data,
  onSave,
  onContinue,
  saving = false,
  continuing = false,
}: {
  data: ElementImageSetDto;
  /** Persist {element_id: build?} on the backend. Absent on read-only screens. */
  onSave?: (decisions: Record<string, boolean>) => Promise<void>;
  /** The next step once the pieces are decided: paint the room. */
  onContinue?: () => Promise<void>;
  saving?: boolean;
  continuing?: boolean;
}) {
  const view = useMemo(() => buildElementImages(data), [data]);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  useEffect(() => {
    // Backend truth first: decisions already saved are the starting point.
    setDecisions(Object.fromEntries(
      (data.definitions ?? []).filter((d) => d.approved !== null && d.approved !== undefined)
        .map((d) => [d.element_id, Boolean(d.approved)])));
  }, [data]);
  const decide = (id: string, yes: boolean) => setDecisions((d) => ({ ...d, [id]: yes }));
  const undecided = view.cards.filter((c) => decisions[c.element_id] === undefined).length;
  const building = view.cards.filter((c) => decisions[c.element_id] === true).length;

  const approveAll = () =>
    setDecisions(Object.fromEntries(view.cards.map((c) => [c.element_id, decisions[c.element_id] ?? true])));

  const saveAndContinue = async () => {
    if (onSave) await onSave(decisions);
    if (onContinue) await onContinue();
  };

  if (!view.cards.length) {
    return (
      <div className="rounded-md border border-dashed px-4 py-6 text-center body-sm text-ink-muted">
        No pieces were planned from the photos and brief yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 rounded-lg border border-gold/40 bg-gold/5 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="body text-ink">The pieces your room will hold</h3>
          <span className="caption text-ink-muted tabular">
            {view.canonical_count} piece{view.canonical_count === 1 ? "" : "s"} · {view.instance_count} instance
            {view.instance_count === 1 ? "" : "s"} · {view.painted} pictured
            {view.failed ? ` · ${view.failed} failed` : ""}
          </span>
        </div>
        <p className="caption text-ink-muted">
          Each piece is pictured once, on its own. The same picture is used to build its 3D model,
          so what you see here is what gets made. A piece that appears several times is one picture
          and several placements.
        </p>
      </div>

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {view.cards.map((c) => (
          <li key={c.element_id} className="flex flex-col overflow-hidden rounded-md border">
            {c.picture === "painted" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={fileUrl(c.image_url)} alt={c.label} title={`seed ${c.seed}`}
                   className="h-40 w-full bg-muted object-contain" />
            ) : (
              <div className="flex h-40 w-full items-center justify-center bg-muted caption text-ink-muted">
                {c.picture === "failed" ? "No picture" : "Not pictured yet"}
              </div>
            )}
            <div className="flex flex-1 flex-col gap-1.5 p-2">
              <span className="body-sm text-ink-soft">{humanType(c.semantic_type)}</span>
              <span className="caption text-ink-muted">
                {human(c.room_id)}{c.material ? ` · ${c.material}` : ""}
              </span>
              <span className="caption text-ink-muted tabular">
                {c.instance_count} instance{c.instance_count === 1 ? "" : "s"} · 1 picture
              </span>
              <span className={`w-fit rounded-full border px-2 py-0.5 caption ${
                c.source === "photo" ? "border-gold/60 text-ink-soft" : "text-ink-muted"}`}>
                {c.source === "photo" ? "From your photo" : "From the brief"}
              </span>
              {c.error ? <span className="caption text-ink-muted">{c.error}</span> : null}
              {onSave ? (
                <div className="mt-auto flex gap-1.5 pt-1.5">
                  <button type="button" onClick={() => decide(c.element_id, true)}
                    className={`flex flex-1 items-center justify-center gap-1 rounded-md border px-2 py-1 caption ${
                      decisions[c.element_id] === true ? "border-gold bg-gold/10 text-ink" : "text-ink-muted hover:bg-muted"}`}>
                    <Check className="size-3" /> Build
                  </button>
                  <button type="button" onClick={() => decide(c.element_id, false)}
                    className={`flex flex-1 items-center justify-center gap-1 rounded-md border px-2 py-1 caption ${
                      decisions[c.element_id] === false ? "border-ink-muted bg-muted text-ink" : "text-ink-muted hover:bg-muted"}`}>
                    <X className="size-3" /> Skip
                  </button>
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      {onSave ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="caption text-ink-muted tabular">
            {building} to build{undecided ? ` · ${undecided} still to decide` : ""}
          </span>
          <div className="flex gap-2">
            {undecided ? (
              <button type="button" onClick={approveAll}
                className="rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted">
                Build all remaining
              </button>
            ) : null}
            <button type="button" onClick={() => void saveAndContinue()}
              disabled={saving || continuing || undecided > 0 || building === 0}
              className="flex items-center gap-2 rounded-md bg-gold px-4 py-2 body-sm font-medium text-ink hover:opacity-90 disabled:opacity-40">
              {saving || continuing ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
              {continuing ? "Painting the room…" : "Approve and paint the room"}
            </button>
          </div>
        </div>
      ) : null}

      {view.warnings.length ? (
        <ul className="rounded-md border border-dashed p-3 caption text-ink-muted">
          {view.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      ) : null}
    </div>
  );
}
