"use client";

import { Check, History, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import type { DesignVersion } from "@/generated/api-types";

import { listVersions, restoreVersion, saveVersion } from "../api/projects-api";

/**
 * P1-FRONTEND-004: protect an accepted design from a later experiment.
 *
 * Save the design as it stands, mark one as accepted, and make any saved
 * version current again. Nothing here deletes anything: making a version
 * current commits it as the live design and leaves every other version - and
 * the undo history - exactly as it was.
 *
 * Only labels, dates and plain states reach the page: never a version id,
 * scene id or hash (those live in handlers only).
 */

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function VersionList({
  versions,
  unsavedChanges,
  busy,
  onSave,
  onMakeCurrent,
}: {
  versions: DesignVersion[];
  unsavedChanges: boolean;
  busy: boolean;
  onSave: (accept: boolean) => void;
  onMakeCurrent: (version: DesignVersion) => void;
}) {
  return (
    <section aria-label="Design versions" className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 body-sm font-medium text-ink">
          <History className="size-4" aria-hidden />
          Design versions
        </h3>
        <div className="flex gap-2">
          <button type="button" disabled={busy} onClick={() => onSave(false)}
            className="caption inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 disabled:opacity-50">
            <Save className="size-3.5" aria-hidden /> Save this design
          </button>
          <button type="button" disabled={busy} onClick={() => onSave(true)}
            className="caption inline-flex items-center gap-1 rounded-md bg-ink px-2 py-1 text-cream disabled:opacity-50">
            <Check className="size-3.5" aria-hidden /> Save and accept
          </button>
        </div>
      </header>

      {unsavedChanges ? (
        <p className="caption text-warning">
          The design has changes that aren&apos;t in any saved version yet.
        </p>
      ) : null}

      {versions.length === 0 ? (
        <p className="caption text-ink-muted">
          Nothing saved yet. Save the design before trying a variation, and you can always come back to it.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {[...versions].reverse().map((v) => (
            <li key={v.version_id} className="flex flex-wrap items-center justify-between gap-2">
              <span className="body-sm text-ink">
                {v.label}
                {v.accepted ? <span className="ml-2 caption rounded bg-success/15 px-1.5 text-success">Accepted</span> : null}
                {v.is_current ? <span className="ml-2 caption rounded bg-ink/10 px-1.5 text-ink">Current</span> : null}
                <span className="ml-2 caption text-ink-muted">{when(v.created_at)}</span>
              </span>
              {v.is_current ? null : (
                <button type="button" disabled={busy} onClick={() => onMakeCurrent(v)}
                  className="caption rounded-md border border-border px-2 py-1 disabled:opacity-50">
                  Make current
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function DesignVersions({
  projectId,
  refreshKey,
  onRestored,
}: {
  projectId: string;
  refreshKey: string | number;
  /** Called after a version is made current, so the page reloads the scene. */
  onRestored: () => void;
}) {
  const [versions, setVersions] = useState<DesignVersion[]>([]);
  const [unsaved, setUnsaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    const data = await listVersions(projectId, signal);
    setVersions(data.versions);
    setUnsaved(data.unsaved_changes);
  }, [projectId]);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal).catch(() => undefined);
    return () => ctrl.abort();
  }, [load, refreshKey]);

  const act = async (work: () => Promise<unknown>, after?: () => void) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
      await load();
      after?.();
    } catch {
      setProblem("That didn't go through. Nothing was changed - please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <VersionList
        versions={versions}
        unsavedChanges={unsaved}
        busy={busy}
        onSave={(accept) => void act(() => saveVersion(projectId, { accept, label: accept ? "Accepted design" : "" }))}
        onMakeCurrent={(v) => void act(() => restoreVersion(projectId, v.version_id), onRestored)}
      />
      {problem ? <p className="caption text-danger">{problem}</p> : null}
    </div>
  );
}
