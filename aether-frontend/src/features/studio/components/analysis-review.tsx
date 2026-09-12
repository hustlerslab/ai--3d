"use client";

import { Check, Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { fileUrl } from "../api/projects-api";
import type { AnalysisDto, AnalysisPatch, RoomAnalysis } from "../types";

const ROOM_TYPES = [
  "living_room", "bedroom", "master_bedroom", "kids_bedroom", "kitchen", "dining_room",
  "bathroom", "study", "balcony", "entry", "other",
];
const MOODS = ["warm_daylight", "cool_daylight", "evening", "studio"] as const;

const human = (s: string) => s.replace(/_/g, " ");

/**
 * Analysis Review: what the AI read from the brief and photos, with the
 * fields a client is most likely to correct (room sizes, constraints, light).
 * Read-only when `onSave` is absent (the moodboard step); editable on Refine.
 */
export function AnalysisReview({
  data,
  onSave,
  saving = false,
}: {
  data: AnalysisDto;
  onSave?: (patch: AnalysisPatch) => Promise<void>;
  saving?: boolean;
}) {
  const { analysis, style, moodboard, provider } = data;
  const [rooms, setRooms] = useState<RoomAnalysis[]>(analysis.rooms);
  const [removed, setRemoved] = useState<string[]>([]);
  const [constraints, setConstraints] = useState(analysis.constraints.join("\n"));
  const [mood, setMood] = useState(style?.lighting_mood ?? "warm_daylight");
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setRooms(analysis.rooms);
    setRemoved([]);
    setConstraints(analysis.constraints.join("\n"));
    setMood(style?.lighting_mood ?? "warm_daylight");
    setDirty(false);
  }, [analysis, style]);

  const editable = Boolean(onSave);

  const updateRoom = (id: string, patch: Partial<RoomAnalysis>) => {
    setRooms((rs) => rs.map((r) => (r.room_id === id ? { ...r, ...patch } : r)));
    setDirty(true);
  };
  const removeRoom = (id: string) => {
    setRooms((rs) => rs.filter((r) => r.room_id !== id));
    setRemoved((x) => [...x, id]);
    setDirty(true);
  };
  const addRoom = () => {
    const n = rooms.length + 1;
    setRooms((rs) => [
      ...rs,
      { room_id: `room_${n}_${Date.now().toString(36)}`, name: `Room ${n}`, type: "other", width_m: 3.5, length_m: 3.5, height_m: 3, estimated: true, notes: "" },
    ]);
    setDirty(true);
  };

  const save = async () => {
    if (!onSave) return;
    const patch: AnalysisPatch = {
      rooms: rooms.map((r) => ({
        room_id: r.room_id, name: r.name, type: r.type, width_m: r.width_m, length_m: r.length_m, height_m: r.height_m, estimated: r.estimated,
      })),
      remove_rooms: removed,
      constraints: constraints.split("\n").map((s) => s.trim()).filter(Boolean),
      style: { lighting_mood: mood },
    };
    await onSave(patch);
    setDirty(false);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="flex flex-col gap-5">
      {/* moodboard strip */}
      <div className="flex flex-col gap-3 rounded-lg border border-gold/40 bg-gold/5 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <p className="body font-medium text-ink-soft">{moodboard?.title ?? human(style?.name ?? "direction")}</p>
            <p className="body-sm text-ink-muted">{style?.description || analysis.intent}</p>
          </div>
          <span className="caption text-ink-muted">
            {provider.mode === "live" ? "Gemini vision" : "estimated locally"} · confidence {(analysis.confidence * 100).toFixed(0)}%
          </span>
        </div>
        {/* The scene Gemini painted from the references and the brief. */}
        {moodboard?.scene_url ? (
          <div className="space-y-1.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl(moodboard.scene_url)}
              alt="The room Allure is proposing, generated from your references and brief"
              /* Never wider than it was actually rendered. `w-full` alone
                 stretched a 704 px image across a ~1400 px card: enormous, and
                 blurry with it, because that is a 2x upscale. The cap matches
                 scene_image_width in aether-backend app/core/config.py, and the
                 image still shrinks below it on narrow screens. */
              className="w-full max-w-[704px] rounded-md border"
            />
            {moodboard.reference_resolved === false ? (
              // A render that never saw the user's furniture looks exactly like
              // one that did. Saying so is the only way they can tell.
              <p className="caption text-amber-700" role="status">
                Generic room — none of your photos could be used
                {moodboard.reference_note ? `: ${moodboard.reference_note}` : "."} Re-upload the
                piece you want in the scene and run the analysis again.
              </p>
            ) : moodboard.reference_note ? (
              <p className="caption text-ink-muted">Based on {moodboard.reference_note}</p>
            ) : null}
          </div>
        ) : moodboard?.scene_error ? (
          <div className="rounded-md border border-dashed px-4 py-3">
            <p className="body-sm font-medium text-ink">No scene image for this moodboard</p>
            <p className="mt-1 caption text-ink-muted">{moodboard.scene_error}</p>
          </div>
        ) : null}

        {/* No image strip here by design. The board shows the GENERATED scene
            or nothing: crops of the user's own uploads are the upload step
            played back, which is what they replaced and what they looked like.
            The crops are still produced — they texture rugs and wall art in the
            Blender build — they simply are not a moodboard. */}
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-1.5" aria-label="Palette">
            {(style?.palette ?? []).map((hex, i) => (
              <span key={`${hex}-${i}`} title={hex} className="size-6 rounded-full border" style={{ backgroundColor: hex }} />
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(style?.tags ?? []).map((t, i) => (
              <span key={`${t}-${i}`} className="rounded-full border px-2 py-0.5 caption text-ink-muted">{human(t)}</span>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(style?.materials ?? []).map((m, i) => (
              <span key={`${m}-${i}`} className="rounded-sm bg-muted px-2 py-0.5 caption text-ink-soft">{human(m)}</span>
            ))}
          </div>
        </div>
      </div>

      {/* rooms */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <p className="body-sm font-medium text-ink-soft">Rooms</p>
          {editable ? (
            <button type="button" onClick={addRoom} className="flex items-center gap-1 caption text-ink-muted hover:text-ink-soft">
              <Plus className="size-3.5" /> Add room
            </button>
          ) : null}
        </div>
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-left caption">
            <thead className="bg-muted/60 text-ink-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Width (m)</th>
                <th className="px-3 py-2 font-medium">Length (m)</th>
                <th className="px-3 py-2 font-medium">Size</th>
                {editable ? <th className="px-3 py-2" /> : null}
              </tr>
            </thead>
            <tbody>
              {rooms.map((r) => (
                <tr key={r.room_id} className="border-t">
                  <td className="px-3 py-1.5">
                    {editable ? (
                      <input value={r.name} onChange={(e) => updateRoom(r.room_id, { name: e.target.value })} className="w-32 rounded border bg-transparent px-2 py-1 text-ink-soft" />
                    ) : (
                      <span className="text-ink-soft">{r.name}</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    {editable ? (
                      <select value={r.type} onChange={(e) => updateRoom(r.room_id, { type: e.target.value })} className="rounded border bg-transparent px-2 py-1 text-ink-soft">
                        {ROOM_TYPES.map((t) => (
                          <option key={t} value={t}>{human(t)}</option>
                        ))}
                      </select>
                    ) : (
                      human(r.type)
                    )}
                  </td>
                  {(["width_m", "length_m"] as const).map((k) => (
                    <td key={k} className="px-3 py-1.5">
                      {editable ? (
                        <input
                          type="number" step="0.1" min="1" value={r[k]}
                          onChange={(e) => updateRoom(r.room_id, { [k]: Number(e.target.value), estimated: false })}
                          className="w-20 rounded border bg-transparent px-2 py-1 tabular text-ink-soft"
                        />
                      ) : (
                        <span className="tabular">{r[k].toFixed(1)}</span>
                      )}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 text-ink-muted">
                    <span className="tabular">{(r.width_m * r.length_m).toFixed(1)} m²</span>
                    {r.estimated ? <span className="ml-2 rounded-sm border px-1 text-[10px] uppercase tracking-wide">estimated</span> : null}
                  </td>
                  {editable ? (
                    <td className="px-3 py-1.5 text-right">
                      <button type="button" onClick={() => removeRoom(r.room_id)} aria-label={`Remove ${r.name}`} className="text-ink-muted hover:text-danger">
                        <Trash2 className="size-3.5" />
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <p className="body-sm font-medium text-ink-soft">Must-haves and constraints</p>
          {editable ? (
            <textarea
              value={constraints} rows={4}
              onChange={(e) => { setConstraints(e.target.value); setDirty(true); }}
              placeholder="One per line"
              className="resize-none rounded-md border bg-transparent px-3 py-2 body-sm text-ink-soft focus:outline-none focus:ring-1 focus:ring-gold"
            />
          ) : analysis.constraints.length ? (
            <ul className="list-disc pl-5 body-sm text-ink-muted">
              {analysis.constraints.map((c) => <li key={c}>{c}</li>)}
            </ul>
          ) : (
            <p className="body-sm text-ink-muted">None mentioned.</p>
          )}
        </div>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <p className="body-sm font-medium text-ink-soft">Spotted in your brief and photos</p>
            <div className="flex flex-wrap gap-1.5">
              {analysis.spotted_objects.length ? analysis.spotted_objects.map((o, i) => (
                <span
                  key={`${o.semantic_type}-${i}`}
                  className="rounded-full bg-muted px-2 py-0.5 caption text-ink-soft"
                  title={[o.notes, o.placement === "on_surface" && o.support ? `on ${o.support}` : o.placement === "wall" ? "on the wall" : "", o.crop_ref ? "cut from your photo" : ""].filter(Boolean).join(" · ")}
                >
                  {o.name || human(o.semantic_type)}{o.count > 1 ? ` ×${o.count}` : ""}
                </span>
              )) : <span className="caption text-ink-muted">Nothing specific yet.</span>}
            </div>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="body-sm font-medium text-ink-soft">Light</span>
            {editable ? (
              <select value={mood} onChange={(e) => { setMood(e.target.value as typeof mood); setDirty(true); }} className="w-fit rounded-md border bg-transparent px-3 py-1.5 body-sm text-ink-soft">
                {MOODS.map((m) => <option key={m} value={m}>{human(m)}</option>)}
              </select>
            ) : (
              <span className="body-sm text-ink-muted">{human(mood)}</span>
            )}
          </label>
        </div>
      </div>

      {analysis.warnings.length || style?.warnings?.length ? (
        <ul className="rounded-md border border-warning/35 bg-warning/8 p-3 caption text-ink-muted">
          {[...analysis.warnings, ...(style?.warnings ?? [])].map((w) => <li key={w}>{w}</li>)}
        </ul>
      ) : null}

      {editable ? (
        <div className="flex items-center gap-3">
          <button
            type="button" onClick={() => void save()} disabled={!dirty || saving}
            className="flex items-center gap-2 rounded-md border px-3 py-1.5 body-sm text-ink-soft hover:bg-muted disabled:opacity-40"
          >
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : saved ? <Check className="size-3.5 text-success" /> : null}
            {saved ? "Saved" : "Save corrections"}
          </button>
          {dirty ? <span className="caption text-ink-muted">Unsaved changes: save before planning the space.</span> : null}
        </div>
      ) : null}
    </div>
  );
}
