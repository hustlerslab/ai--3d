"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Film, Loader2, Plus, WifiOff } from "lucide-react";

import { PageHeader } from "@/components/portal/page-header";
import { Button } from "@/components/shared/button";
import { StatusPill } from "@/components/shared/status-pill";

import { API_BASE_URL } from "../api/walkthrough-api";
import { useWalkthrough } from "../hooks/use-walkthrough";
import { useWalkthroughStatus } from "../hooks/use-walkthrough-status";
import { useWalkthroughUpload } from "../hooks/use-walkthrough-upload";
import { friendlyError, isTerminal } from "../utils/walkthrough-helpers";

import { ApprovalPanel } from "./approval-panel";
import { GenerationProgress } from "./generation-progress";
import { ImagePreviewGrid } from "./image-preview-grid";
import { RevisionPanel } from "./revision-panel";
import { WalkthroughPlayer } from "./walkthrough-player";
import { WalkthroughSummary } from "./walkthrough-summary";
import { WalkthroughUploader } from "./walkthrough-uploader";

/**
 * The walkthrough screen.
 *
 * One page, four phases: collect photos, watch it build, watch the result,
 * decide. They are phases of one object rather than separate screens, so the
 * whole thing lives on a single route and the user never loses their place.
 *
 * This is the only screen in the app backed by a live service, so it carries
 * two states nothing else needs: "the engine is not running", and "the engine
 * is in demo mode". Both are stated plainly rather than hidden, because a
 * silent failure here looks identical to a slow render.
 */
export function WalkthroughView() {
  const {
    walkthroughId,
    walkthrough,
    engineHealth,
    mockMode,
    pendingAction,
    error: actionError,
    create,
    generate,
    approve,
    revise,
    reload,
    reset,
    clearError,
    recheckEngine,
  } = useWalkthrough();

  const upload = useWalkthroughUpload();

  // Polling runs only while a walkthrough exists and the engine is up.
  const { status, refresh } = useWalkthroughStatus(walkthroughId, {
    enabled: engineHealth === "online",
  });

  const [title, setTitle] = useState("");
  const [choosingRoom, setChoosingRoom] = useState(false);

  // When the engine reaches a terminal state, re-read the full record — the
  // polling DTO is deliberately lightweight and carries no QA checks, costs,
  // or camera moves.
  const settledAt = status && isTerminal(status.status) ? status.videoVersion : null;
  useEffect(() => {
    if (settledAt !== null) void reload();
  }, [settledAt, status?.status, reload]);

  // A finished revision closes the picker on its own; leaving it open would
  // invite a second revision before the user has seen the first result.
  useEffect(() => {
    if (status?.status === "ready" || status?.status === "completed") {
      setChoosingRoom(false);
    }
  }, [status?.status]);

  /* ── Actions ─────────────────────────────────────────────────────────── */

  /**
   * The one primary action: get from "photos on my laptop" to "walkthrough
   * building". Create the workspace if needed, send any pending photos, then
   * start generation. Three calls behind one button — the user should not have
   * to understand the sequence, or press three things in order.
   *
   * `id` is threaded through explicitly rather than read back from state: this
   * whole function runs inside the closure captured before create() set it, so
   * `walkthroughId` here is still null on a first run.
   */
  const handleStart = useCallback(async () => {
    const id = walkthroughId ?? (await create(title));
    if (!id) return;

    // Photos already on the server and nothing new staged — just build.
    if (upload.validImages.length > 0) {
      const uploaded = await upload.upload(id);
      if (!uploaded) return;
    }

    const started = await generate(id);
    if (started) refresh();
  }, [walkthroughId, create, title, upload, generate, refresh]);

  const handleApprove = useCallback(async () => {
    const ok = await approve();
    if (ok) refresh();
  }, [approve, refresh]);

  const handleRevise = useCallback(
    async (position: number) => {
      const ok = await revise(position);
      if (ok) {
        setChoosingRoom(false);
        refresh();
      }
    },
    [revise, refresh],
  );

  const handleRetry = useCallback(async () => {
    const started = await generate();
    if (started) refresh();
  }, [generate, refresh]);

  const handleStartOver = useCallback(() => {
    upload.clearAll();
    setChoosingRoom(false);
    setTitle("");
    reset();
  }, [upload, reset]);

  /* ── Engine down ─────────────────────────────────────────────────────── */

  if (engineHealth === "offline") {
    return (
      <div className="flex flex-col gap-8">
        <PageHeader
          overline="Marketing"
          title="Cinematic Walkthrough"
          meta="Turn property photos into a walkthrough film"
        />

        <section className="flex flex-col items-start gap-4 rounded-lg border border-warning/35 bg-warning/8 p-6">
          <div className="flex items-start gap-3">
            <WifiOff className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden />
            <div className="flex flex-col gap-1.5">
              <h2 className="body font-medium text-ink-soft">The walkthrough engine is not running</h2>
              <p className="body-sm text-ink-muted">
                This is the one part of Allure that needs a service behind it. Nothing else in the
                portal is affected.
              </p>
              <p className="caption tabular text-ink-muted">Expected at {API_BASE_URL}</p>
            </div>
          </div>

          <Button variant="secondary" size="sm" onClick={recheckEngine}>
            Check again
          </Button>
        </section>
      </div>
    );
  }

  if (engineHealth === "checking") {
    return (
      <div className="flex flex-col gap-8">
        <PageHeader
          overline="Marketing"
          title="Cinematic Walkthrough"
          meta="Turn property photos into a walkthrough film"
        />
        <div className="flex items-center gap-2.5 text-ink-muted">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          <p className="body-sm">Connecting to the walkthrough engine…</p>
        </div>
      </div>
    );
  }

  /* ── Derived view state ──────────────────────────────────────────────── */

  const currentStatus = status?.status ?? walkthrough?.status ?? "created";
  const working = status ? !status.terminal && currentStatus !== "created" && currentStatus !== "uploaded" : false;
  const finished = currentStatus === "ready" || currentStatus === "completed";
  const showUploader = !working && !finished;

  // Photos already accepted by the engine, as opposed to staged locally.
  const uploadedCount = walkthrough?.photos?.length ?? 0;
  // Start is possible with new photos staged, or with photos already uploaded.
  const canStart = upload.validImages.length > 0 || uploadedCount > 0;

  const busyError = actionError ?? upload.error;
  const errorCopy = busyError ? friendlyError(busyError.code, busyError.message) : null;

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        overline="Marketing"
        title="Cinematic Walkthrough"
        meta={
          <>
            <span>Turn property photos into a walkthrough film</span>
            {mockMode ? (
              <StatusPill label="Demo mode — no real rendering" tone="info" size="sm" />
            ) : null}
          </>
        }
        actions={
          walkthroughId ? (
            <Button variant="ghost" size="sm" onClick={handleStartOver}>
              <Plus className="size-3.5" aria-hidden />
              New walkthrough
            </Button>
          ) : null
        }
      />

      {/* Action-level errors. Pipeline failures render inside GenerationProgress. */}
      {errorCopy && !working ? (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-md border border-danger/35 bg-danger/6 px-4 py-3"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
          <div className="flex flex-1 flex-col gap-0.5">
            <p className="body-sm font-medium text-ink-soft">{errorCopy.title}</p>
            <p className="caption text-ink-muted">{errorCopy.detail}</p>
            {errorCopy.action ? <p className="caption text-ink-muted">{errorCopy.action}</p> : null}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              clearError();
              upload.clearError();
            }}
          >
            Dismiss
          </Button>
        </div>
      ) : null}

      {/* ── Phase 1 — collect photos ───────────────────────────────────── */}
      {showUploader ? (
        <section className="flex flex-col gap-6">
          <div className="flex max-w-xl flex-col gap-2">
            <label htmlFor="walkthrough-title" className="overline text-ink-muted">
              Property name
            </label>
            <input
              id="walkthrough-title"
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Ashoka Residence, Patna"
              disabled={Boolean(walkthroughId) || upload.uploading}
              className="body-sm rounded-md border border-border bg-surface-raised px-3.5 py-2.5 text-ink-soft placeholder:text-ink-muted/70 focus-visible:border-gold focus-visible:ring-2 focus-visible:ring-gold/30 focus-visible:outline-none disabled:opacity-60"
            />
            <p className="caption text-ink-muted">
              Used to name the walkthrough. You can leave it blank.
            </p>
          </div>

          <WalkthroughUploader
            images={upload.images}
            onAddFiles={upload.addFiles}
            disabled={upload.uploading}
            busy={upload.uploading}
          />

          <ImagePreviewGrid
            images={upload.images}
            onRemove={upload.removeImage}
            rejections={upload.rejections}
            disabled={upload.uploading}
          />

          {upload.uploading ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between">
                <p className="body-sm text-ink-soft">Uploading photos</p>
                <p className="caption tabular text-ink-muted">{upload.progress}%</p>
              </div>
              <div
                role="progressbar"
                aria-valuenow={upload.progress}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Upload progress"
                className="h-1.5 w-full overflow-hidden rounded-pill bg-sand"
              >
                <div
                  className="h-full rounded-pill bg-gold transition-[width] duration-300 ease-out motion-reduce:transition-none"
                  style={{ width: `${upload.progress}%` }}
                />
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              onClick={handleStart}
              disabled={!canStart || upload.uploading || pendingAction !== null}
            >
              {upload.uploading || pendingAction ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Film className="size-3.5" aria-hidden />
              )}
              {upload.uploading
                ? "Uploading"
                : pendingAction === "generate"
                  ? "Starting"
                  : "Create walkthrough"}
            </Button>

            {upload.validImages.length > 0 ? (
              <p className="caption tabular text-ink-muted">
                {upload.validImages.length}{" "}
                {upload.validImages.length === 1 ? "photo" : "photos"} will be used
                {upload.validImages.length < 3 ? (
                  <span className="text-warning">
                    {" "}
                    — that makes a {upload.validImages.length * 4}-second clip, not a tour
                  </span>
                ) : (
                  <span> — about {upload.validImages.length * 4} seconds</span>
                )}
              </p>
            ) : uploadedCount > 0 ? (
              <p className="caption tabular text-ink-muted">
                {uploadedCount} {uploadedCount === 1 ? "photo" : "photos"} already uploaded
              </p>
            ) : (
              <p className="caption text-ink-muted">Add at least one photo to begin.</p>
            )}
          </div>
        </section>
      ) : null}

      {/* ── Phase 2 — building ─────────────────────────────────────────── */}
      {status && (working || currentStatus === "failed") ? (
        <GenerationProgress
          status={status}
          onRetry={handleRetry}
          retrying={pendingAction === "generate"}
        />
      ) : null}

      {/* ── Phase 3 — the result ───────────────────────────────────────── */}
      {finished && walkthroughId ? (
        <section className="flex flex-col gap-6">
          <WalkthroughPlayer
            walkthroughId={walkthroughId}
            version={status?.videoVersion ?? walkthrough?.videoVersion ?? 1}
          />

          {walkthrough ? (
            <WalkthroughSummary
              qa={walkthrough.qa}
              costs={walkthrough.costs}
              revisionCount={walkthrough.approval?.revisionCount ?? 0}
            />
          ) : null}

          {/* ── Phase 4 — decide ─────────────────────────────────────── */}
          {choosingRoom ? (
            <RevisionPanel
              walkthroughId={walkthroughId}
              scenes={walkthrough?.scenes ?? []}
              version={status?.videoVersion ?? walkthrough?.videoVersion ?? 1}
              onRevise={handleRevise}
              onCancel={() => setChoosingRoom(false)}
              pending={pendingAction === "revise"}
            />
          ) : (
            <ApprovalPanel
              approved={currentStatus === "completed"}
              revisionCount={walkthrough?.approval?.revisionCount ?? 0}
              onApprove={handleApprove}
              onReject={() => setChoosingRoom(true)}
              pending={pendingAction === "approve"}
            />
          )}

          {currentStatus === "completed" && !choosingRoom ? (
            <div>
              <Button variant="secondary" size="sm" onClick={() => setChoosingRoom(true)}>
                Change a room
              </Button>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
