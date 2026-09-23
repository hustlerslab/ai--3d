/**
 * PBR materials for the 3D walkthrough, driven by the engine's material
 * registry (plan §34).
 *
 * A scene references materials by id ("wood_oak", "paint_white"). The
 * registry says what that id looks like: base colour + roughness always,
 * and colour/normal/roughness/AO maps once the CC0 texture sets have been
 * sourced. This module turns a record into a three.js material, tiled in
 * physical meters so a 2 m plank reads as 2 m on every surface.
 *
 * Until maps exist, the built-in material photos in /images/materials keep
 * floors from looking flat — the same fallback ladder as furniture.
 */

import { useLoader } from "@react-three/fiber";
import { withSessionCredentials } from "../api/loader-credentials";
import { use, useMemo } from "react";
import * as THREE from "three";

import { fileUrl } from "../api/aether-api";
import { materialsIndex } from "../api/asset-resolver";
import type { MaterialRecord } from "../types/scene";

/** Local photo fallbacks for material ids that have no registry maps yet. */
const LOCAL_FALLBACK_MAPS: Record<string, { src: string; repeat: number }> = {
  wood_oak: { src: "/images/materials/material-oak.avif", repeat: 0.55 },
  wood_oak_herringbone: { src: "/images/materials/material-oak.avif", repeat: 0.7 },
  wood_walnut: { src: "/images/materials/material-walnut.avif", repeat: 0.55 },
  wood_dark: { src: "/images/materials/material-walnut.avif", repeat: 0.55 },
  marble: { src: "/images/materials/material-marble.avif", repeat: 0.35 },
  tile_ivory: { src: "/images/materials/material-marble.avif", repeat: 0.8 },
  terrazzo: { src: "/images/materials/material-terrazzo.avif", repeat: 0.5 },
  veneer_oak: { src: "/images/materials/material-oak.avif", repeat: 1.2 },
  veneer_walnut: { src: "/images/materials/material-walnut.avif", repeat: 1.2 },
};

/** 1x1 transparent PNG — lets useTexture run with a stable hook count when a
 * material has no maps at all. */
const BLANK_TEXTURE =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

const FALLBACK_RECORD: MaterialRecord = {
  material_id: "fallback",
  name: "Fallback",
  category: "paint",
  base_color: "#cfc6b8",
  roughness: 0.85,
  metalness: 0,
  maps: { color: null, normal: null, roughness: null, ao: null },
  tile_size_m: 1,
  finish: "matte",
  style_tags: [],
  applies_to: [],
};

/** The registry record for an id, resolved through Suspense. */
export function useMaterialRecord(materialId: string): MaterialRecord {
  const index = use(materialsIndex());
  return index.get(materialId) ?? { ...FALLBACK_RECORD, material_id: materialId };
}

interface TextureSet {
  map?: THREE.Texture;
  normalMap?: THREE.Texture;
  roughnessMap?: THREE.Texture;
  aoMap?: THREE.Texture;
  /** Texture repeats per meter for UV-in-meters geometry. */
  perMeter: number;
}

/**
 * Load the maps for a material. Registry maps win; a local photo fills in
 * for a known id; otherwise no maps (flat colour). Always the same hook
 * count regardless of which branch runs.
 */
function useTextureSet(record: MaterialRecord): TextureSet {
  const registryUrls = {
    map: record.maps.color ? fileUrl(record.maps.color) : null,
    normalMap: record.maps.normal ? fileUrl(record.maps.normal) : null,
    roughnessMap: record.maps.roughness ? fileUrl(record.maps.roughness) : null,
    aoMap: record.maps.ao ? fileUrl(record.maps.ao) : null,
  };
  const local = LOCAL_FALLBACK_MAPS[record.material_id];
  const useRegistry = registryUrls.map !== null;

  const urls: string[] = useRegistry
    ? (Object.values(registryUrls).filter(Boolean) as string[])
    : local
      ? [local.src]
      : [BLANK_TEXTURE];
  // fiber's useLoader rather than drei's useTexture: only the former takes a
  // loader extension, and the loader has to send the session cookie.
  const loaded = useLoader(THREE.TextureLoader, urls, withSessionCredentials);
  const textures = Array.isArray(loaded) ? loaded : [loaded];

  return useMemo(() => {
    if (useRegistry) {
      const keys = (Object.keys(registryUrls) as Array<keyof typeof registryUrls>).filter(
        (k) => registryUrls[k] !== null,
      );
      const set: TextureSet = { perMeter: 1 / Math.max(0.05, record.tile_size_m) };
      keys.forEach((key, i) => {
        const tex = textures[i];
        if (key === "map") tex.colorSpace = THREE.SRGBColorSpace;
        set[key] = tex;
      });
      return set;
    }
    if (local) {
      textures[0].colorSpace = THREE.SRGBColorSpace;
      return { map: textures[0], perMeter: local.repeat };
    }
    return { perMeter: 1 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useRegistry, local, record.tile_size_m, ...textures]);
}

function prepare(tex: THREE.Texture | undefined, repeatX: number, repeatY: number): THREE.Texture | null {
  if (!tex) return null;
  const clone = tex.clone();
  clone.wrapS = clone.wrapT = THREE.RepeatWrapping;
  clone.repeat.set(repeatX, repeatY);
  clone.anisotropy = 8;
  clone.needsUpdate = true;
  return clone;
}

/**
 * A material for a surface whose UVs are in world meters (room floors from
 * ShapeGeometry). Tiling comes straight from tile_size_m.
 */
export function useSurfaceMaterial(materialId: string): THREE.MeshStandardMaterial {
  const record = useMaterialRecord(materialId);
  const set = useTextureSet(record);
  return useMemo(() => {
    const r = set.perMeter;
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(set.map ? "#ffffff" : record.base_color),
      roughness: set.roughnessMap ? 1 : record.roughness,
      metalness: record.metalness,
      map: prepare(set.map, r, r),
      normalMap: prepare(set.normalMap, r, r),
      roughnessMap: prepare(set.roughnessMap, r, r),
      aoMap: prepare(set.aoMap, r, r),
      side: THREE.DoubleSide,
    });
    if (material.normalMap) material.normalScale.set(0.8, 0.8);
    return material;
  }, [record, set]);
}

/**
 * A material for a box whose UVs run 0–1 per face: tiling is derived from
 * the face's physical width/height so the texture keeps its real-world size.
 */
export function useBoxMaterial(materialId: string, widthM: number, heightM: number): THREE.MeshStandardMaterial {
  const record = useMaterialRecord(materialId);
  const set = useTextureSet(record);
  return useMemo(() => {
    const rx = Math.max(0.05, widthM * set.perMeter);
    const ry = Math.max(0.05, heightM * set.perMeter);
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(set.map ? "#ffffff" : record.base_color),
      roughness: set.roughnessMap ? 1 : record.roughness,
      metalness: record.metalness,
      map: prepare(set.map, rx, ry),
      normalMap: prepare(set.normalMap, rx, ry),
      roughnessMap: prepare(set.roughnessMap, rx, ry),
      aoMap: prepare(set.aoMap, rx, ry),
    });
    if (material.normalMap) material.normalScale.set(0.6, 0.6);
    return material;
  }, [record, set, widthM, heightM]);
}

/* ── Parametric furniture finishes ─────────────────────────────────────── */

/**
 * Fabric: a plain physical material with sheen. Fabric photos tile too
 * coarsely on furniture-sized UVs and read as a print; smooth colour with
 * sheen reads as upholstery.
 */
export function useFabricMaterial(color: string): THREE.MeshPhysicalMaterial {
  return useMemo(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: new THREE.Color(color),
        roughness: 0.95,
        sheen: 0.6,
        sheenRoughness: 0.8,
        sheenColor: new THREE.Color("#fff3df"),
      }),
    [color],
  );
}

/** Furniture wood: the walnut veneer material, tinted. */
export function useWoodMaterial(color = "#8a6a4b"): THREE.MeshStandardMaterial {
  const record = useMaterialRecord("veneer_walnut");
  const set = useTextureSet(record);
  return useMemo(() => {
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(color),
      roughness: set.roughnessMap ? 1 : 0.55,
      metalness: 0,
      map: prepare(set.map, 1.2, 1.2),
      normalMap: prepare(set.normalMap, 1.2, 1.2),
      roughnessMap: prepare(set.roughnessMap, 1.2, 1.2),
    });
    return material;
  }, [color, set]);
}
