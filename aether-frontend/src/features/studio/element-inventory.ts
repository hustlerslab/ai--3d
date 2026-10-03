import type { Assumption, InventoryCounts } from "@/generated/api-types";

import type { ElementDefinition, ElementInstance, SceneElement, SceneReadingDto } from "./types";

/**
 * P19 / P1-FRONTEND-001: the review screen's view of the element inventory.
 *
 * This file JOINS backend records by the ids the backend put on them. It does
 * not count, group, merge, split, judge or infer anything:
 *   - the pieces and their instances are `summary.definitions` / `instances`
 *     (app/intelligence/scene_reading.py resolve_elements);
 *   - each row's state is `summary.element_states`, and the numbers printed are
 *     `summary.counts` (app/intelligence/element_states.py) - this file used to
 *     recount them (`groups.filter(...).length`), a second copy of the rule
 *     that could disagree with the first;
 *   - every estimate is `summary.assumptions`.
 * A backend too old to send counts gets no counts shown, never a recount.
 */

export type AssetState = "resolved" | "unresolved";
export type ElementState = "detected" | "validated" | "rejected" | "unresolved";

export interface InventoryInstance {
  instance_id: string;
  element: SceneElement | null;
  crop_url: string;
  room_id: string;
  bbox: [number, number, number, number] | null;
  /** The backend's state for this instance's reading row. */
  state: ElementState | null;
  /** The backend listed this piece's position as an estimate. */
  estimated_position: boolean;
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
  /** The backend's state for this piece (its rows share one decision). */
  state: ElementState | null;
  yours: boolean;
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
  /** Reading rows the backend marked rejected. */
  rejected: RejectedElement[];
  /** The backend's counts, verbatim. Null when the backend sent none. */
  counts: InventoryCounts | null;
  /** Every estimate the design rests on, in the backend's words. */
  assumptions: Assumption[];
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
  const states = data.summary.element_states ?? {};
  const assumptions = data.summary.assumptions ?? [];
  const byId = new Map(elements.map((e) => [e.element_id, e] as const));
  const estimated = new Set(assumptions.filter((a) => a.kind === "position").map((a) => a.ref));

  const unavailable = data.summary.definitions === undefined && data.summary.instances === undefined;

  const groups: InventoryGroup[] = definitions.map((def) => {
    const own = instances.filter((i) => i.element_id === def.element_id);
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
          state: states[i.source_element_id] ?? null,
          estimated_position: estimated.has(i.source_element_id),
        };
      }),
      asset: def.canonical_asset_id ? "resolved" : "unresolved",
      asset_id: def.canonical_asset_id,
      identity: def.identity_method,
      state: own.length ? (states[own[0].source_element_id] ?? null) : null,
      yours: !!def.client_owned,
    };
  });

  const rejected: RejectedElement[] = elements
    .filter((e) => states[e.element_id] === "rejected")
    .map((e) => ({ element: e, reason: e.approved === false ? "unapproved" : e.check, note: e.check_note }));

  return { groups, rejected, counts: data.summary.counts ?? null, assumptions, unavailable };
}
