"use client";

import type { ProvenanceChain } from "@/generated/api-types";

import { fileUrl } from "../api/aether-api";
import type { SceneObject } from "../types/scene";

/**
 * P2-VIEWER-001: what a selected piece IS, in five plain answers - name,
 * dimensions, material, kept-or-new, and origin (which photo it came from).
 * The origin comes from the backend's provenance chain (P1-IDENTITY-005);
 * nothing here guesses it. No internal id reaches the page.
 */

const human = (s: string) => {
  const t = s.replace(/_/g, " ").trim();
  return t ? t[0].toUpperCase() + t.slice(1) : "";
};

export function nameOf(obj: SceneObject): string {
  return obj.name?.trim() ? human(obj.name) : human(obj.semantic_type);
}

export function dimensionsOf(obj: SceneObject): string {
  const [w, h, d] = obj.dimensions.map((v, i) => v * obj.scale[i]);
  return `${w.toFixed(2)} × ${h.toFixed(2)} × ${d.toFixed(2)} m (W × H × D)`;
}

/** The client's own word first ("linen"), then the style material assigned. */
export function materialOf(obj: SceneObject): string {
  const read = obj.visual?.material?.trim() || obj.visual?.upholstery?.trim();
  if (read) return human(read);
  const assigned = obj.material_overrides?.primary;
  if (assigned) return human(assigned);
  return "Not specified";
}

export function keptOrNew(obj: SceneObject): string {
  if (obj.client_owned) return "Yours - kept, not built";
  switch (obj.source_strategy) {
    case "generated":
      return "New - made for this design";
    case "local_asset":
    case "local_modified":
      return "New - from the catalogue";
    default:
      return "New - a simple stand-in shape";
  }
}

export interface Origin {
  text: string;
  photos: { url: string; filename: string }[];
}

export function originOf(chain: ProvenanceChain | null | undefined): Origin {
  if (!chain) return { text: "Looking up where this came from…", photos: [] };
  const photos = (chain.source_images ?? [])
    .map((p) => ({ url: String(p.url ?? ""), filename: String(p.filename ?? "") }))
    .filter((p) => p.url);
  if (photos.length) {
    return { text: photos.length === 1 ? "From your photo" : `From ${photos.length} of your photos`, photos };
  }
  if (chain.terminus === "moodboard") return { text: "From the moodboard you approved", photos: [] };
  if (chain.origin === "planner_catalog") {
    return { text: "Chosen by the planner - not from one of your photos", photos: [] };
  }
  return { text: "Where this came from couldn't be traced", photos: [] };
}

export function IdentityPanel({ obj, chain }: { obj: SceneObject; chain: ProvenanceChain | null | undefined }) {
  const origin = originOf(chain);
  const rows: [string, string][] = [
    ["Name", nameOf(obj)],
    ["Size", dimensionsOf(obj)],
    ["Material", materialOf(obj)],
    ["Kept or new", keptOrNew(obj)],
    ["Origin", origin.text],
  ];
  return (
    <section aria-label="What this piece is" className="flex flex-col gap-2">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 caption">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-muted">{k}</dt>
            <dd className="text-ink-soft">{v}</dd>
          </div>
        ))}
      </dl>
      {origin.photos.length ? (
        <div className="flex flex-wrap gap-1.5">
          {origin.photos.slice(0, 4).map((p, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={i} src={fileUrl(p.url)} alt={p.filename ? `Your photo ${p.filename}` : "Your photo"}
                 className="h-14 w-14 rounded border object-cover" />
          ))}
        </div>
      ) : null}
    </section>
  );
}
