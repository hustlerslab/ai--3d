"use client";

import { AlertTriangle, CheckCircle2, Circle, Pencil, RefreshCw, ThumbsDown, ThumbsUp, XCircle } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import type { ReviewView } from "@/generated/api-types";

import { fileUrl, getReview, saveVersion } from "../api/projects-api";
import type { SceneReadingDto } from "../types";
import { ElementInventory } from "./element-review";

/**
 * P1-FRONTEND-002: the one place a person judges the design.
 *
 * Render, 3D scene, inventory with its assumptions, verification in plain
 * words, open issues, the repair counter - and four decisions:
 *
 *   Approve     saves the design as an accepted version (P1-FRONTEND-004)
 *   Edit        opens the 3D editor
 *   Regenerate  re-plans the room
 *   Reject      saves the design as a version marked rejected. NOTHING is
 *               deleted: the rejected design stays recoverable.
 *
 * Every sentence comes from the backend (app/review_surface.py), which
 * guarantees no code or internal id; this renders it and never rephrases. The
 * two machine fields (`status`, `outcome`) become icons and words here, never
 * printed raw.
 */

const OUTCOME: Record<ReviewView["checks"][number]["outcome"], { word: string; icon: ReactNode }> = {
  passed: { word: "Checked", icon: <CheckCircle2 className="size-4 text-success" aria-hidden /> },
  failed: { word: "Needs a look", icon: <XCircle className="size-4 text-danger" aria-hidden /> },
  not_checked: { word: "Not checked yet", icon: <Circle className="size-4 text-ink-muted" aria-hidden /> },
};

const STATUS_TONE: Record<ReviewView["status"], string> = {
  verified: "border-success/40 bg-success/5",
  needs_attention: "border-warning/50 bg-warning/5",
  not_verified: "border-border",
  not_ready: "border-border",
};

export type Decision = "approve" | "edit" | "regenerate" | "reject";

export function ReviewPanel({
  view,
  reading,
  scene,
  busy,
  notice,
  onDecide,
}: {
  view: ReviewView;
  reading: SceneReadingDto | null;
  /** The live 3D view, supplied by the page that owns it. */
  scene: ReactNode;
  busy: boolean;
  notice: string | null;
  onDecide: (d: Decision) => void;
}) {
  return (
    <section aria-label="Review your design" className="flex flex-col gap-4">
      <div className={`flex items-start gap-2 rounded-lg border p-4 ${STATUS_TONE[view.status]}`}>
        {view.status === "needs_attention" ? (
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden />
        ) : view.status === "verified" ? (
          <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
        ) : (
          <Circle className="mt-0.5 size-5 shrink-0 text-ink-muted" aria-hidden />
        )}
        <p className="body-sm text-ink">{view.status_text}</p>
      </div>

      {view.repair ? <p className="caption text-ink-soft">{view.repair.text}</p> : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <figure className="flex flex-col gap-2">
          {view.render ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={fileUrl(view.render.url)} alt="The rendered room" className="w-full rounded-lg border object-cover" />
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-lg border caption text-ink-muted">
              Not rendered yet
            </div>
          )}
          <figcaption className="caption text-ink-muted">The render</figcaption>
        </figure>
        <div className="flex flex-col gap-2">
          {scene}
          <span className="caption text-ink-muted">The 3D scene</span>
        </div>
      </div>

      {view.checks.length ? (
        <div className="flex flex-col gap-2 rounded-lg border p-4">
          <h4 className="body-sm font-medium text-ink-soft">What was checked</h4>
          <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {view.checks.map((c) => (
              <li key={c.label} className="flex items-center gap-2 caption">
                {OUTCOME[c.outcome].icon}
                <span className="text-ink-soft">{c.label}</span>
                <span className="text-ink-muted">· {OUTCOME[c.outcome].word}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {view.issues.length ? (
        <div className="flex flex-col gap-2 rounded-lg border border-warning/50 p-4">
          <h4 className="body-sm font-medium text-ink-soft">Things to look at</h4>
          <ul className="flex flex-col gap-2">
            {view.issues.map((i, n) => (
              <li key={n} className="caption">
                <span className="text-ink-soft">{i.text}</span> {i.next ? <span className="text-ink-muted">{i.next}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {reading ? <ElementInventory data={reading} /> : null}

      <div className="flex flex-wrap gap-2" role="group" aria-label="Your decision">
        <button type="button" disabled={busy || !view.can_decide} onClick={() => onDecide("approve")}
          className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 body-sm text-cream disabled:opacity-40">
          <ThumbsUp className="size-4" aria-hidden /> Approve
        </button>
        <button type="button" disabled={busy || !view.can_decide} onClick={() => onDecide("edit")}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm disabled:opacity-40">
          <Pencil className="size-4" aria-hidden /> Edit
        </button>
        <button type="button" disabled={busy || !view.can_decide} onClick={() => onDecide("regenerate")}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm disabled:opacity-40">
          <RefreshCw className="size-4" aria-hidden /> Regenerate
        </button>
        <button type="button" disabled={busy || !view.can_decide} onClick={() => onDecide("reject")}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 body-sm disabled:opacity-40">
          <ThumbsDown className="size-4" aria-hidden /> Reject
        </button>
      </div>
      {notice ? <p className="caption text-ink-soft" role="status">{notice}</p> : null}
    </section>
  );
}

/** Approve and Reject, as the person's decision is recorded. Both SAVE a
 *  version; neither deletes anything - a rejected design stays recoverable. */
export async function recordDecision(projectId: string, d: "approve" | "reject"): Promise<string> {
  if (d === "approve") {
    await saveVersion(projectId, { accept: true, label: "Approved design" });
    return "Approved. This design is saved, and a later experiment can never replace it.";
  }
  const v = await saveVersion(projectId, { accept: false, label: "Rejected design" });
  return `Rejected - and kept as saved version ${v.number}. Nothing was deleted; edit or regenerate to try again.`;
}

export function ReviewSurface({
  projectId,
  refreshKey,
  reading,
  scene,
  onEdit,
  onRegenerate,
}: {
  projectId: string;
  refreshKey: string | number;
  reading: SceneReadingDto | null;
  scene: ReactNode;
  onEdit: () => void;
  onRegenerate: () => void;
}) {
  const [view, setView] = useState<ReviewView | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => getReview(projectId, signal).then(setView), [projectId]);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal).catch(() => setView(null));
    return () => ctrl.abort();
  }, [load, refreshKey]);

  const decide = async (d: Decision) => {
    if (d === "edit") return onEdit();
    if (d === "regenerate") return onRegenerate();
    setBusy(true);
    setNotice(null);
    try {
      setNotice(await recordDecision(projectId, d));
      await load();
    } catch {
      setNotice("That didn't go through. Nothing was changed - please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (!view) return null;
  return <ReviewPanel view={view} reading={reading} scene={scene} busy={busy} notice={notice} onDecide={(d) => void decide(d)} />;
}
