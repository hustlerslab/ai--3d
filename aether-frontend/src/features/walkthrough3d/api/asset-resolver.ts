/**
 * Resolves catalog asset ids to real model files, and material ids to PBR
 * records, from the engine's registries.
 *
 * Both are fetched once per session and cached as promises so every mesh in
 * the scene shares one request. The resolvers are Suspense-friendly: the
 * promises are stable, so React 19's `use()` can await them inside the
 * canvas's Suspense boundary without re-fetching.
 *
 * A miss (no real model registered for an asset id) resolves to null and
 * the renderer keeps its parametric shape — retrieval before generation,
 * primitives before nothing (plan §40 fallback ladder).
 */

import type { CatalogItem, MaterialRecord } from "../types/scene";
import { fileUrl, getCatalog, getMaterials } from "./aether-api";

let catalogPromise: Promise<Map<string, CatalogItem>> | null = null;
let materialsPromise: Promise<Map<string, MaterialRecord>> | null = null;

export function catalogIndex(): Promise<Map<string, CatalogItem>> {
  if (!catalogPromise) {
    catalogPromise = getCatalog()
      .then((items) => new Map(items.map((i) => [i.asset_id, i])))
      .catch(() => {
        catalogPromise = null; // allow retry after an engine hiccup
        return new Map<string, CatalogItem>();
      });
  }
  return catalogPromise;
}

export function materialsIndex(): Promise<Map<string, MaterialRecord>> {
  if (!materialsPromise) {
    materialsPromise = getMaterials()
      .then((items) => new Map(items.map((m) => [m.material_id, m])))
      .catch(() => {
        materialsPromise = null;
        return new Map<string, MaterialRecord>();
      });
  }
  return materialsPromise;
}

/** Absolute URL of the normalized GLB for an asset, or null for parametric. */
export async function resolveModelUrl(assetId: string | null): Promise<string | null> {
  if (!assetId) return null;
  const index = await catalogIndex();
  const item = index.get(assetId);
  return item?.model_url ? fileUrl(item.model_url) : null;
}

/** Drop the caches — after an ingest, so new assets show without a reload. */
export function invalidateAssetCaches(): void {
  catalogPromise = null;
  materialsPromise = null;
}
