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

// Keyed by project: a project's own generated models are only in its own
// catalog, so one shared cache would serve the first project's answer to every
// other one and hide their meshes.
const catalogPromises = new Map<string, Promise<Map<string, CatalogItem>>>();
let materialsPromise: Promise<Map<string, MaterialRecord>> | null = null;

export function catalogIndex(projectId = ""): Promise<Map<string, CatalogItem>> {
  let promise = catalogPromises.get(projectId);
  if (!promise) {
    promise = getCatalog(projectId)
      .then((items) => new Map(items.map((i) => [i.asset_id, i])))
      .catch(() => {
        catalogPromises.delete(projectId); // allow retry after an engine hiccup
        return new Map<string, CatalogItem>();
      });
    catalogPromises.set(projectId, promise);
  }
  return promise;
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
export async function resolveModelUrl(assetId: string | null, projectId = ""): Promise<string | null> {
  if (!assetId) return null;
  const index = await catalogIndex(projectId);
  const item = index.get(assetId);
  return item?.model_url ? fileUrl(item.model_url) : null;
}

/** True when the model was generated for this project from its own material,
 *  so its textures are the client's and must not be re-skinned. */
export async function resolveOwnMaterials(assetId: string | null, projectId = ""): Promise<boolean> {
  if (!assetId) return false;
  const index = await catalogIndex(projectId);
  return Boolean(index.get(assetId)?.project_id);
}

/** Drop the caches — after an ingest, so new assets show without a reload. */
export function invalidateAssetCaches(): void {
  catalogPromises.clear();
  materialsPromise = null;
}
