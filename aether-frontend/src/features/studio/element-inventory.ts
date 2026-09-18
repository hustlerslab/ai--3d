import type { ElementDefinition, ElementInstance, SceneElement, SceneReadingDto } from "./types";

/**
 * P19: the review screen's view of the element inventory.
 *
 * This file JOINS backend records by the ids the backend put on them. It does
 * not count, group, merge, split or infer anything - the backend already did
 * that (app/intelligence/scene_reading.py resolve_elements), and the whole
 * point of the screen is to show that answer, not to second-guess it.
 *
 * Three stools are three instances of one canonical piece because the backend
 * says so in `summary.instances`; a kitchen island is "rejected: mismatch"
 * because `check` on its reading row says so. Nothing here is a heuristic.
 */

export type AssetState = "resolved" | "unresolved";
export type ElementState = "detected" | "validated" | "rejected" | "unresolved";

export interface InventoryInstance {
  instance_id: string;
  element: SceneElement | null;
  crop_url: string;
  room_id: string;
  bbox: [number, number, number, number] | null;
}

export interface InventoryGroup {
  element_id: string;
  label: string;
  room_id: string;
  semantic_type: string;
  instance_count: number;
  instances: InventoryInstance[];
  asset: AssetState;
  asset_id: string;
  /** From the backend's identity_method; never computed here. */
  identity: string;
  /** "validated" for a resolved piece; "unresolved" when the backend kept it
      apart for lack of evidence. */
  state: ElementState;
}

export interface RejectedElement {
  element: SceneElement;
  /** The backend check that removed it, or "unapproved" if a human said no. */
  reason: string;
  note: string;
}

export interface ElementInventoryView {
  /** Canonical pieces, one per backend definition, in backend order. */
  groups: InventoryGroup[];
  /** Reading rows that belong to no instance: the checks removed them. */
  rejected: RejectedElement[];
  detected_rows: number;
  canonical_count: number;
  instance_count: number;
  asset_count: number;
  /** True when the backend sent no inventory at all (pre-P17 reading). */
  unavailable: boolean;
}

const IDENTITY_TEXT: Record<string, string> = {
  room_type_dims_material_colour: "Same room and type, matching material, colour or size",
  unresolved: "Kept separate: no material, colour or size to compare",
};

export function humanIdentity(method: string): string {
  return IDENTITY_TEXT[method] ?? method.replace(/_/g, " ");
}

export function humanType(semanticType: string): string {
  return semanticType
    .split("_")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

export function buildElementInventory(data: SceneReadingDto): ElementInventoryView {
  const definitions: ElementDefinition[] = data.summary.definitions ?? [];
  const instances: ElementInstance[] = data.summary.instances ?? [];
  const elements = data.reading.elements ?? [];
  const byId = new Map(elements.map((e) => [e.element_id, e] as const));

  const unavailable = data.summary.definitions === undefined && data.summary.instances === undefined;

  const groups: InventoryGroup[] = definitions.map((def) => {
    const own = instances.filter((i) => i.element_id === def.element_id);
    const asset: AssetState = def.canonical_asset_id ? "resolved" : "unresolved";
    return {
      element_id: def.element_id,
      label: def.canonical_name || humanType(def.semantic_type),
      room_id: def.room_id,
      semantic_type: def.semantic_type,
      instance_count: def.instance_count,
      instances: own.map((i) => {
        const element = byId.get(i.source_element_id) ?? null;
        return {
          instance_id: i.instance_id,
          element,
          crop_url: element?.crop_url ?? "",
          room_id: i.room_id,
          bbox: i.bbox,
        };
      }),
      asset,
      asset_id: def.canonical_asset_id,
      identity: def.identity_method,
      state: def.identity_method === "unresolved" ? "unresolved" : "validated",
    };
  });

  // A row the backend attached to no instance was removed by a check, or
  // turned down by a human. The reason is the backend's own `check`.
  const claimed = new Set(instances.map((i) => i.source_element_id));
  const rejected: RejectedElement[] = unavailable
    ? []
    : elements
        .filter((e) => !claimed.has(e.element_id))
        .map((e) => ({
          element: e,
          reason: e.approved === false ? "unapproved" : e.check,
          note: e.check_note,
        }));

  return {
    groups,
    rejected,
    detected_rows: elements.length,
    canonical_count: groups.length,
    instance_count: instances.length,
    asset_count: groups.filter((g) => g.asset === "resolved").length,
    unavailable,
  };
}
