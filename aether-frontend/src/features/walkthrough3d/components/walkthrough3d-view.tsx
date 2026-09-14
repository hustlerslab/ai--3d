"use client";

/**
 * The 3D walkthrough view — composes the canvas, camera modes, the design
 * chat, and the inspector into the portal shell.
 *
 * Everything on screen is a projection of the backend's canonical scene.
 * Every mutation goes through the backend patch pipeline; a rejected edit
 * shows the engine's violation, never a silent failure.
 */

import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import {
  AlertTriangle,
  Box,
  Check,
  Eye,
  Loader2,
  Lock,
  Pause,
  Play,
  Redo2,
  RotateCw,
  Route,
  Sparkles,
  Trash2,
  Undo2,
  User,
  X,
} from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { formatINR } from "@/lib/format";

import * as api from "../api/aether-api";
import type {
  CatalogItem,
  AetherHealth,
  AetherScene,
  CameraMode,
  HistoryInfo,
  ProposalPreview,
  SpawnPoint,
  TourPath,
  Vec3,
} from "../types/scene";
import { AetherApiError } from "../types/scene";
import { buildWalkWorld } from "../utils/collision";
import { FirstPersonRig, TourRig } from "./camera-rigs";
import { SceneEnvironment } from "./canvas-environment";
import { SceneMeshes } from "./scene-meshes";

const DEFAULT_SCENE_ID = "scene_seed_apartment";

type EngineState = "checking" | "up" | "down";

export function Walkthrough3DView({
  sceneId = DEFAULT_SCENE_ID,
}: {
  /** Which canonical scene to load. Defaults to the seed apartment. */
  sceneId?: string;
} = {}) {
  const [engineState, setEngineState] = useState<EngineState>("checking");
  const [health, setHealth] = useState<AetherHealth | null>(null);
  const [scene, setScene] = useState<AetherScene | null>(null);
  const [history, setHistory] = useState<HistoryInfo | null>(null);
  const [mode, setMode] = useState<CameraMode>("orbit");
  const [spawn, setSpawn] = useState<SpawnPoint | null>(null);
  const [tour, setTour] = useState<TourPath | null>(null);
  const [tourPlaying, setTourPlaying] = useState(false);
  const [tourLabel, setTourLabel] = useState("");
  const [pointerLocked, setPointerLocked] = useState(false);
  const [walkHintDismissed, setWalkHintDismissed] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [proposing, setProposing] = useState(false);
  const [proposal, setProposal] = useState<ProposalPreview | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [addRoomId, setAddRoomId] = useState<string>("");
  const [addAssetId, setAddAssetId] = useState<string>("");

  const walkWorld = useMemo(
    () => (scene ? buildWalkWorld(scene) : null),
    [scene],
  );

  /* ── Boot: health then scene ─────────────────────────────────────────── */

  const loadAll = useCallback(async (signal?: AbortSignal) => {
    try {
      const h = await api.getHealth(signal);
      setHealth(h);
      setEngineState("up");
      const [record, spawnPoint, tourPath] = await Promise.all([
        api.getScene(sceneId, signal),
        api.getSpawn(sceneId, signal),
        api.getTour(sceneId, signal),
      ]);
      setScene(record.scene);
      setHistory(record.history);
      setSpawn(spawnPoint);
      setTour(tourPath);
    } catch (err) {
      if (signal?.aborted) return;
      setEngineState("down");
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }, [sceneId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadAll(controller.signal);
    return () => controller.abort();
  }, [loadAll]);

  useEffect(() => {
    if (engineState !== "up") return;
    const controller = new AbortController();
    api
      .getCatalog(scene?.project_id ?? "", controller.signal)
      .then((items) => setCatalog(items))
      .catch(() => setCatalog([]));
    return () => controller.abort();
  }, [engineState, scene?.project_id]);

  /* ── Scene refresh after any mutation ────────────────────────────────── */

  const applySceneUpdate = useCallback(
    async (updated: AetherScene, updatedHistory: HistoryInfo) => {
      setScene(updated);
      setHistory(updatedHistory);
      // Tour and spawn are derived from the scene; refresh them quietly.
      try {
        const [spawnPoint, tourPath] = await Promise.all([
          api.getSpawn(sceneId),
          api.getTour(sceneId),
        ]);
        setSpawn(spawnPoint);
        setTour(tourPath);
      } catch {
        /* non-fatal — walkthrough data refreshes on next action */
      }
    },
    [sceneId],
  );

  const runAction = useCallback(
    async (action: () => Promise<{ scene: AetherScene; history: HistoryInfo }>) => {
      setBusy(true);
      setActionError(null);
      try {
        const result = await action();
        await applySceneUpdate(result.scene, result.history);
      } catch (err) {
        if (err instanceof AetherApiError) {
          const detail = err.violations.map((v) => v.message).join(" ");
          setActionError(detail || err.message);
        } else {
          setActionError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        setBusy(false);
      }
    },
    [applySceneUpdate],
  );

  /* ── Object edits (nudge / rotate / delete) ──────────────────────────── */

  const selectedObject = scene?.objects.find((o) => o.object_id === selectedId) ?? null;

  const nudge = useCallback(
    (dx: number, dz: number) => {
      if (!scene || !selectedObject) return;
      const next: Vec3 = [
        selectedObject.position[0] + dx,
        selectedObject.position[1],
        selectedObject.position[2] + dz,
      ];
      void runAction(() =>
        api.commitPatch(scene.scene_id, scene.version, [
          { type: "move_object", object_id: selectedObject.object_id, position: next },
        ]),
      );
    },
    [scene, selectedObject, runAction],
  );

  const rotateSelected = useCallback(() => {
    if (!scene || !selectedObject) return;
    void runAction(() =>
      api.commitPatch(scene.scene_id, scene.version, [
        {
          type: "rotate_object",
          object_id: selectedObject.object_id,
          rotation_y: selectedObject.rotation_y + Math.PI / 2,
        },
      ]),
    );
  }, [scene, selectedObject, runAction]);

  const deleteSelected = useCallback(() => {
    if (!scene || !selectedObject) return;
    setSelectedId(null);
    void runAction(() =>
      api.commitPatch(scene.scene_id, scene.version, [
        { type: "remove_object", object_id: selectedObject.object_id },
      ]),
    );
  }, [scene, selectedObject, runAction]);

  const replaceSelected = useCallback(
    (assetId: string) => {
      if (!scene || !selectedObject || !assetId) return;
      void runAction(() =>
        api.commitPatch(scene.scene_id, scene.version, [
          { type: "replace_asset", object_id: selectedObject.object_id, asset_id: assetId },
        ]),
      );
    },
    [scene, selectedObject, runAction],
  );

  const recolourSelected = useCallback(
    (color: string) => {
      if (!scene || !selectedObject) return;
      void runAction(() =>
        api.commitPatch(scene.scene_id, scene.version, [
          { type: "update_object", object_id: selectedObject.object_id, color },
        ]),
      );
    },
    [scene, selectedObject, runAction],
  );

  /**
   * Add a catalog piece: the engine's planner finds a valid spot for the type
   * (validated like every edit), then the chosen model is swapped in if the
   * planner picked a different one of the same type.
   */
  const addFromCatalog = useCallback(async () => {
    if (!scene || !addAssetId) return;
    const item = catalog.find((c) => c.asset_id === addAssetId);
    const room = scene.rooms.find((r) => r.room_id === addRoomId) ?? scene.rooms[0];
    if (!item || !room) return;
    setBusy(true);
    setActionError(null);
    try {
      const before = new Set(scene.objects.map((o) => o.object_id));
      const typeLabel = item.semantic_type.replace(/_/g, " ");
      const preview = await api.createProposal(scene.scene_id, "add a " + typeLabel + " to " + room.name);
      const applied = await api.applyProposal(scene.scene_id, preview.proposal.proposal_id);
      const added = applied.scene.objects.find(
        (o) => !before.has(o.object_id) && o.semantic_type === item.semantic_type,
      );
      if (!added) {
        setActionError("The planner found no valid spot for a " + typeLabel + " in " + room.name + ".");
        await applySceneUpdate(applied.scene, applied.history);
        return;
      }
      if (added.asset_id !== item.asset_id) {
        const swapped = await api.commitPatch(applied.scene.scene_id, applied.scene.version, [
          { type: "replace_asset", object_id: added.object_id, asset_id: item.asset_id },
        ]);
        await applySceneUpdate(swapped.scene, swapped.history);
      } else {
        await applySceneUpdate(applied.scene, applied.history);
      }
      setSelectedId(added.object_id);
    } catch (err) {
      if (err instanceof AetherApiError) {
        const detail = err.violations.map((v) => v.message).join(" ");
        setActionError(detail || err.message);
      } else {
        setActionError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  }, [scene, addAssetId, addRoomId, catalog, applySceneUpdate]);

  /* ── Design proposals ────────────────────────────────────────────────── */

  const submitInstruction = useCallback(async () => {
    if (!scene || !instruction.trim() || proposing) return;
    setProposing(true);
    setActionError(null);
    setProposal(null);
    try {
      const preview = await api.createProposal(scene.scene_id, instruction.trim());
      setProposal(preview);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setProposing(false);
    }
  }, [scene, instruction, proposing]);

  const approveProposal = useCallback(() => {
    if (!scene || !proposal) return;
    const id = proposal.proposal.proposal_id;
    setProposal(null);
    setInstruction("");
    void runAction(() => api.applyProposal(scene.scene_id, id));
  }, [scene, proposal, runAction]);

  const dismissProposal = useCallback(() => {
    if (scene && proposal) {
      void api.rejectProposal(scene.scene_id, proposal.proposal.proposal_id).catch(() => {});
    }
    setProposal(null);
  }, [scene, proposal]);

  /* ── Render states ───────────────────────────────────────────────────── */

  if (engineState === "checking") {
    return (
      <div className="flex items-center gap-2.5 text-ink-muted">
        <Loader2 className="size-4 animate-spin" />
        <span className="body-sm">Connecting to the Aether engine…</span>
      </div>
    );
  }

  if (engineState === "down" || !scene) {
    return (
      <div className="flex flex-col items-start gap-4 rounded-lg border border-warning/35 bg-warning/8 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warning" />
          <div className="flex flex-col gap-1.5">
            <p className="body font-medium text-ink-soft">
              The Aether engine is not running
            </p>
            <p className="body-sm text-ink-muted">
              Start it with{" "}
              <code className="rounded bg-muted px-1.5 py-0.5">
                uvicorn app.main:app --port 8000
              </code>{" "}
              inside <code className="rounded bg-muted px-1.5 py-0.5">aether-backend/</code>,
              then retry.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            setEngineState("checking");
            void loadAll();
          }}
          className="rounded-md border px-4 py-2 body-sm font-medium text-ink-soft hover:bg-muted"
        >
          Retry
        </button>
      </div>
    );
  }

  const modeButton = (m: CameraMode, icon: React.ReactNode, label: string) => (
    <button
      type="button"
      onClick={() => {
        setMode(m);
        setTourPlaying(m === "tour");
        setSelectedId(null);
        setWalkHintDismissed(false);
      }}
      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 body-sm font-medium transition-colors ${
        mode === m
          ? "bg-gold text-ink"
          : "border text-ink-muted hover:bg-muted hover:text-ink-soft"
      }`}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <h1 className="body font-medium text-ink-soft">{scene.name}</h1>
          <p className="caption text-ink-muted">
            v{scene.version} · {scene.rooms.length} rooms · {scene.objects.length}{" "}
            objects · AI:{" "}
            {health?.providers.gemini.mode === "live" ? "Gemini" : "deterministic mock"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {modeButton("orbit", <Eye className="size-3.5" />, "Orbit")}
          {modeButton("first_person", <User className="size-3.5" />, "Walk")}
          {modeButton("tour", <Route className="size-3.5" />, "Guided tour")}
          <span className="mx-1 h-5 w-px bg-border" />
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void runAction(async () => {
                const result = await api.upgradeSceneAssets(scene.scene_id);
                if (result.skipped.length) {
                  const reasons = result.skipped
                    .map((s) => s.reason)
                    .filter((r, i, all) => all.indexOf(r) === i)
                    .slice(0, 3)
                    .join("; ");
                  // Surfaced through the same banner as engine rejections so
                  // a partial upgrade never reads as a silent success.
                  setTimeout(
                    () =>
                      setActionError(
                        `Swapped ${result.replaced.length} piece${result.replaced.length === 1 ? "" : "s"} for real models. Left as placeholders: ${reasons}.`,
                      ),
                    0,
                  );
                }
                return result;
              })
            }
            className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 caption text-ink-muted transition-colors hover:bg-muted disabled:opacity-40"
            title="Replace placeholder furniture with real 3D models from the library"
          >
            <Box className="size-3.5" />
            Use real furniture
          </button>
          <button
            type="button"
            disabled={!history?.can_undo || busy}
            onClick={() =>
              void runAction(() => api.undo(scene.scene_id))
            }
            className="rounded-md border p-1.5 text-ink-muted hover:bg-muted disabled:opacity-40"
            aria-label="Undo"
          >
            <Undo2 className="size-4" />
          </button>
          <button
            type="button"
            disabled={!history?.can_redo || busy}
            onClick={() =>
              void runAction(() => api.redo(scene.scene_id))
            }
            className="rounded-md border p-1.5 text-ink-muted hover:bg-muted disabled:opacity-40"
            aria-label="Redo"
          >
            <Redo2 className="size-4" />
          </button>
        </div>
      </div>

      {actionError ? (
        <div className="flex items-center gap-2 rounded-md border border-warning/35 bg-warning/8 px-3 py-2">
          <AlertTriangle className="size-4 shrink-0 text-warning" />
          <p className="body-sm text-ink-soft">{actionError}</p>
          <button
            type="button"
            onClick={() => setActionError(null)}
            className="ml-auto text-ink-muted hover:text-ink-soft"
            aria-label="Dismiss"
          >
            <X className="size-4" />
          </button>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        {/* Canvas */}
        <div
          className="relative aspect-[16/10] overflow-hidden rounded-lg border bg-ink"
          onPointerDown={() => {
            if (mode === "first_person") setWalkHintDismissed(true);
          }}
        >
          <Canvas
            // "percentage" = PCFShadowMap; three r185 deprecated PCFSoftShadowMap
            // (what shadows={true} selects) and silently falls back to this anyway.
            shadows="percentage"
            camera={{ position: [10, 8, 10], fov: 55 }}
            gl={{ antialias: true }}
            onPointerMissed={() => setSelectedId(null)}
          >
            <color attach="background" args={["#15130f"]} />
            <SceneEnvironment />
            <Suspense fallback={null}>
              <SceneMeshes
                scene={scene}
                showCeilings={mode !== "orbit"}
                selectedId={mode === "orbit" ? selectedId : null}
                onSelect={(id) => (mode === "orbit" ? setSelectedId(id) : null)}
                ghostObjects={proposal?.added}
              />
            </Suspense>
            {mode === "orbit" ? (
              <OrbitControls
                target={[5, 0, 2.25]}
                maxPolarAngle={Math.PI / 2 - 0.02}
                minDistance={2}
                maxDistance={30}
              />
            ) : null}
            {mode === "first_person" && walkWorld && spawn ? (
              <FirstPersonRig
                world={walkWorld}
                spawn={spawn}
                onLockChange={setPointerLocked}
              />
            ) : null}
            {mode === "tour" && tour ? (
              <TourRig
                tour={tour}
                playing={tourPlaying}
                onProgress={(_, label) => setTourLabel(label)}
                onEnd={() => setTourPlaying(false)}
              />
            ) : null}
          </Canvas>

          {/* Overlays */}
          {mode === "first_person" && !pointerLocked && !walkHintDismissed ? (
            <div
              className="pointer-events-none absolute inset-0 flex items-center justify-center bg-ink/50"
              aria-hidden
            >
              <p className="rounded-md bg-ink/80 px-4 py-2 body-sm text-cream">
                Click to walk · WASD to move · mouse (or drag) to look · Esc to release
              </p>
            </div>
          ) : null}
          {mode === "tour" ? (
            <div className="absolute bottom-3 left-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => setTourPlaying((p) => !p)}
                className="flex items-center gap-1.5 rounded-md bg-ink/80 px-3 py-1.5 body-sm text-cream hover:bg-ink"
              >
                {tourPlaying ? (
                  <Pause className="size-3.5" />
                ) : (
                  <Play className="size-3.5" />
                )}
                {tourPlaying ? "Pause" : "Play"}
              </button>
              {tourLabel ? (
                <span className="rounded-md bg-ink/70 px-3 py-1.5 caption text-cream">
                  {tourLabel}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* Side panel */}
        <div className="flex flex-col gap-4">
          {/* Design chat */}
          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-gold" />
              <h2 className="body-sm font-medium text-ink-soft">AI design</h2>
            </div>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder='e.g. "add a bookshelf and a floor lamp to the living room"'
              rows={2}
              className="w-full resize-none rounded-md border bg-transparent px-3 py-2 body-sm text-ink-soft placeholder:text-ink-muted/60 focus:outline-none focus:ring-1 focus:ring-gold"
            />
            <button
              type="button"
              onClick={() => void submitInstruction()}
              disabled={proposing || !instruction.trim()}
              className="flex items-center justify-center gap-2 rounded-md bg-gold px-3 py-2 body-sm font-medium text-ink hover:opacity-90 disabled:opacity-40"
            >
              {proposing ? <Loader2 className="size-4 animate-spin" /> : null}
              {proposing ? "Thinking…" : "Propose changes"}
            </button>

            {proposal ? (
              <div className="flex flex-col gap-2.5 rounded-md border border-gold/40 bg-gold/5 p-3">
                <p className="body-sm text-ink-soft">{proposal.proposal.summary}</p>
                <ul className="flex flex-col gap-1">
                  {proposal.added.map((o) => (
                    <li key={o.object_id} className="caption text-ink-muted">
                      + {o.semantic_type.replace(/_/g, " ")}
                    </li>
                  ))}
                  {proposal.removed.map((o) => (
                    <li key={o.object_id} className="caption text-ink-muted">
                      − {o.semantic_type.replace(/_/g, " ")}
                    </li>
                  ))}
                </ul>
                {proposal.proposal.warnings.length > 0 ? (
                  <p className="caption text-warning">
                    {proposal.proposal.warnings.join(" ")}
                  </p>
                ) : null}
                {proposal.proposal.estimated_cost_inr > 0 ? (
                  <p className="caption tabular text-ink-muted">
                    Estimated {formatINR(proposal.proposal.estimated_cost_inr)}
                  </p>
                ) : null}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={approveProposal}
                    disabled={proposal.added.length + proposal.removed.length === 0}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-gold px-3 py-1.5 body-sm font-medium text-ink hover:opacity-90 disabled:opacity-40"
                  >
                    <Check className="size-3.5" /> Apply
                  </button>
                  <button
                    type="button"
                    onClick={dismissProposal}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted"
                  >
                    <X className="size-3.5" /> Reject
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          {/* Inspector */}
          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <h2 className="body-sm font-medium text-ink-soft">Inspector</h2>
            {selectedObject ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <span
                    className="size-3 rounded-sm border"
                    style={{ backgroundColor: selectedObject.color }}
                  />
                  <p className="body-sm text-ink-soft">
                    {selectedObject.semantic_type.replace(/_/g, " ")}
                  </p>
                  {selectedObject.locked ? (
                    <Lock className="size-3.5 text-ink-muted" />
                  ) : null}
                </div>
                <p className="caption tabular text-ink-muted">
                  {selectedObject.dimensions[0].toFixed(2)} ×{" "}
                  {selectedObject.dimensions[1].toFixed(2)} ×{" "}
                  {selectedObject.dimensions[2].toFixed(2)} m · pos{" "}
                  {selectedObject.position[0].toFixed(2)},{" "}
                  {selectedObject.position[2].toFixed(2)}
                </p>
                {!selectedObject.locked ? (
                  <>
                    <div className="grid grid-cols-3 gap-1.5">
                      <span />
                      <NudgeButton label="↑" onClick={() => nudge(0, -0.25)} disabled={busy} />
                      <span />
                      <NudgeButton label="←" onClick={() => nudge(-0.25, 0)} disabled={busy} />
                      <NudgeButton label="↓" onClick={() => nudge(0, 0.25)} disabled={busy} />
                      <NudgeButton label="→" onClick={() => nudge(0.25, 0)} disabled={busy} />
                    </div>
                    <label className="flex flex-col gap-1">
                      <span className="caption text-ink-muted">Replace with</span>
                      <select
                        value={selectedObject.asset_id ?? ""}
                        disabled={busy}
                        onChange={(e) => replaceSelected(e.target.value)}
                        className="rounded-md border bg-transparent px-2 py-1 body-sm text-ink-soft"
                      >
                        {catalog
                          .filter((c) => c.semantic_type === selectedObject.semantic_type)
                          .sort((a, b) => Number(Boolean(b.model_url)) - Number(Boolean(a.model_url)))
                          .map((c) => (
                            <option key={c.asset_id} value={c.asset_id}>
                              {c.name}
                              {c.model_url ? " · 3D model" : " · simple"}
                              {c.price_inr ? " · " + formatINR(c.price_inr) : ""}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="flex items-center gap-2">
                      <span className="caption text-ink-muted">Colour</span>
                      <input
                        type="color"
                        value={/^#[0-9a-fA-F]{6}$/.test(selectedObject.color) ? selectedObject.color : "#8a7862"}
                        disabled={busy}
                        onChange={(e) => recolourSelected(e.target.value)}
                        className="h-7 w-10 cursor-pointer rounded border bg-transparent"
                        aria-label="Object colour"
                      />
                      <span className="caption tabular text-ink-muted">{selectedObject.color}</span>
                    </label>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={rotateSelected}
                        disabled={busy}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted disabled:opacity-40"
                      >
                        <RotateCw className="size-3.5" /> Rotate 90°
                      </button>
                      <button
                        type="button"
                        onClick={deleteSelected}
                        disabled={busy}
                        className="flex items-center justify-center gap-1.5 rounded-md border border-danger/40 px-3 py-1.5 body-sm text-danger hover:bg-danger/10 disabled:opacity-40"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="caption text-ink-muted">
                    This object is protected and cannot be edited.
                  </p>
                )}
              </div>
            ) : (
              <p className="caption text-ink-muted">
                {mode === "orbit"
                  ? "Click a furniture piece to inspect and edit it. Every edit is validated by the engine — collisions and blocked doorways are rejected."
                  : "Switch to Orbit mode to select and edit objects."}
              </p>
            )}
          </div>

          {/* Add furniture from the catalog */}
          <div className="flex flex-col gap-2 rounded-lg border p-4">
            <h2 className="body-sm font-medium text-ink-soft">Add furniture</h2>
            <div className="flex flex-col gap-2">
              <select
                value={addRoomId || scene.rooms[0]?.room_id || ""}
                onChange={(e) => setAddRoomId(e.target.value)}
                className="rounded-md border bg-transparent px-2 py-1 body-sm text-ink-soft"
                aria-label="Room"
              >
                {scene.rooms.map((r) => (
                  <option key={r.room_id} value={r.room_id}>{r.name}</option>
                ))}
              </select>
              <select
                value={addAssetId}
                onChange={(e) => setAddAssetId(e.target.value)}
                className="rounded-md border bg-transparent px-2 py-1 body-sm text-ink-soft"
                aria-label="Catalog item"
              >
                <option value="">Choose a piece…</option>
                {[...catalog]
                  .sort((a, b) => a.semantic_type.localeCompare(b.semantic_type) || Number(Boolean(b.model_url)) - Number(Boolean(a.model_url)))
                  .map((c) => (
                    <option key={c.asset_id} value={c.asset_id}>
                      {c.semantic_type.replace(/_/g, " ")} · {c.name}{c.model_url ? " (3D)" : ""}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                onClick={() => void addFromCatalog()}
                disabled={busy || !addAssetId || mode !== "orbit"}
                className="flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 body-sm text-ink-muted hover:bg-muted disabled:opacity-40"
              >
                <Box className="size-3.5" /> Place in room
              </button>
              <p className="caption text-ink-muted">The engine picks a valid spot; nudge or rotate it afterwards.</p>
            </div>
          </div>

          {/* Rooms */}
          <div className="flex flex-col gap-2 rounded-lg border p-4">
            <h2 className="body-sm font-medium text-ink-soft">Rooms</h2>
            {scene.rooms.map((room) => (
              <div key={room.room_id} className="flex items-center justify-between">
                <span className="body-sm text-ink-muted">{room.name}</span>
                <span className="caption tabular text-ink-muted">
                  {scene.objects.filter((o) => o.room_id === room.room_id).length}{" "}
                  objects
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function NudgeButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border py-1 body-sm text-ink-muted hover:bg-muted disabled:opacity-40"
      aria-label={`Nudge ${label}`}
    >
      {label}
    </button>
  );
}
