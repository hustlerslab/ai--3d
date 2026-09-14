"use client";

/**
 * Parametric renderers for the canonical scene — visual-quality pass.
 *
 * Still a pure projection of scene data (system design §3.1): meshes are
 * keyed by scene ids and geometry derives from the same meters the backend
 * validates. Floors and furniture carry PBR maps built from the portal's own
 * material photography; furniture is modelled from primitives with enough
 * detail (cushions, frames, legs, trims) to read as real objects. When a
 * real GLB is registered in /models/manifest.json for an asset_id, it
 * replaces the parametric shape, normalized to catalog dimensions.
 */

import { RoundedBox, useGLTF } from "@react-three/drei";
import { Suspense, useEffect, useMemo, useState } from "react";
import * as THREE from "three";

import { resolveModelUrl, resolveOwnMaterials } from "../api/asset-resolver";
import type {
  AetherScene,
  Opening,
  Room,
  SceneObject,
  Wall,
} from "../types/scene";
import {
  useBoxMaterial,
  useFabricMaterial,
  useSurfaceMaterial,
  useWoodMaterial,
} from "../utils/materials";

const TRIM_COLOR = "#4a3b2c";

/* ── Floors & ceilings ─────────────────────────────────────────────────── */

function useRoomGeometry(boundary: Room["boundary"]) {
  return useMemo(() => {
    const shape = new THREE.Shape();
    boundary.forEach(([x, z], i) => {
      if (i === 0) shape.moveTo(x, z);
      else shape.lineTo(x, z);
    });
    shape.closePath();
    const geo = new THREE.ShapeGeometry(shape);
    geo.rotateX(Math.PI / 2); // (x, y, 0) → (x, 0, y)
    return geo;
  }, [boundary]);
}

function RoomFloor({ room }: { room: Room }) {
  const geometry = useRoomGeometry(room.boundary);
  // ShapeGeometry UVs are world meters, so the registry's tile size applies directly.
  const material = useSurfaceMaterial(room.floor_material);
  return (
    <mesh
      geometry={geometry}
      material={material}
      position={[0, room.floor_height + 0.001, 0]}
      receiveShadow
    />
  );
}

function RoomCeiling({ room }: { room: Room }) {
  const geometry = useRoomGeometry(room.boundary);
  return (
    <mesh geometry={geometry} position={[0, room.ceiling_height, 0]}>
      <meshStandardMaterial color="#f4efe6" roughness={1} side={THREE.DoubleSide} />
    </mesh>
  );
}

/* ── Walls, trims, openings ────────────────────────────────────────────── */

interface WallSegment {
  center: number;
  length: number;
  bottom: number;
  height: number;
}

function wallSegments(wall: Wall, openings: Opening[]): WallSegment[] {
  const length = Math.hypot(
    wall.end[0] - wall.start[0],
    wall.end[1] - wall.start[1],
  );
  const sorted = [...openings].sort((a, b) => a.position - b.position);
  const segments: WallSegment[] = [];
  let cursor = 0;

  for (const opening of sorted) {
    const left = Math.max(0, opening.position - opening.width / 2);
    const right = Math.min(length, opening.position + opening.width / 2);
    if (left > cursor + 1e-4) {
      segments.push({
        center: (cursor + left) / 2,
        length: left - cursor,
        bottom: 0,
        height: wall.height,
      });
    }
    const headTop = opening.sill_height + opening.height;
    if (headTop < wall.height - 1e-4) {
      segments.push({
        center: (left + right) / 2,
        length: right - left,
        bottom: headTop,
        height: wall.height - headTop,
      });
    }
    if (opening.sill_height > 1e-4) {
      segments.push({
        center: (left + right) / 2,
        length: right - left,
        bottom: 0,
        height: opening.sill_height,
      });
    }
    cursor = right;
  }
  if (cursor < length - 1e-4) {
    segments.push({
      center: (cursor + length) / 2,
      length: length - cursor,
      bottom: 0,
      height: wall.height,
    });
  }
  return segments;
}

function OpeningFrame({
  opening,
  yaw,
  origin,
  direction,
  thickness,
}: {
  opening: Opening;
  yaw: number;
  origin: [number, number];
  direction: [number, number];
  thickness: number;
}) {
  const cx = origin[0] + direction[0] * opening.position;
  const cz = origin[1] + direction[1] * opening.position;
  const frameT = 0.06;
  const depth = thickness + 0.04;
  const bottom = opening.sill_height;
  const top = opening.sill_height + opening.height;
  const isWindow = opening.type === "window";
  return (
    <group position={[cx, 0, cz]} rotation={[0, yaw, 0]}>
      {/* jambs */}
      <mesh position={[-opening.width / 2 + frameT / 2, (bottom + top) / 2, 0]} castShadow>
        <boxGeometry args={[frameT, opening.height, depth]} />
        <meshStandardMaterial color={TRIM_COLOR} roughness={0.6} />
      </mesh>
      <mesh position={[opening.width / 2 - frameT / 2, (bottom + top) / 2, 0]} castShadow>
        <boxGeometry args={[frameT, opening.height, depth]} />
        <meshStandardMaterial color={TRIM_COLOR} roughness={0.6} />
      </mesh>
      {/* head */}
      <mesh position={[0, top - frameT / 2, 0]} castShadow>
        <boxGeometry args={[opening.width, frameT, depth]} />
        <meshStandardMaterial color={TRIM_COLOR} roughness={0.6} />
      </mesh>
      {isWindow ? (
        <>
          {/* sill + center mullion + glass */}
          <mesh position={[0, bottom + frameT / 2, 0]} castShadow>
            <boxGeometry args={[opening.width + 0.08, frameT, depth + 0.06]} />
            <meshStandardMaterial color={TRIM_COLOR} roughness={0.6} />
          </mesh>
          <mesh position={[0, (bottom + top) / 2, 0]}>
            <boxGeometry args={[0.04, opening.height, 0.04]} />
            <meshStandardMaterial color={TRIM_COLOR} roughness={0.6} />
          </mesh>
          <mesh position={[0, (bottom + top) / 2, 0]}>
            <boxGeometry args={[opening.width, opening.height, 0.015]} />
            <meshPhysicalMaterial
              color="#dcebf2"
              transparent
              opacity={0.18}
              roughness={0.05}
              metalness={0}
              emissive="#fdf6e8"
              emissiveIntensity={0.55}
            />
          </mesh>
        </>
      ) : null}
    </group>
  );
}

function WallSegmentMesh({
  wall,
  segment,
  position,
  yaw,
  tint,
}: {
  wall: Wall;
  segment: WallSegment;
  position: [number, number, number];
  yaw: number;
  tint?: string | null;
}) {
  // Box UVs run 0–1 per face; tile by the segment's physical size.
  const base = useBoxMaterial(wall.material, segment.length, segment.height);
  // Moodboard wall colour: multiply the plaster by the palette's first tone.
  const material = useMemo(() => {
    if (!tint) return base;
    const m = base.clone();
    m.color.copy(base.color).lerp(new THREE.Color(tint), 0.7);
    return m;
  }, [base, tint]);
  return (
    <mesh position={position} rotation={[0, yaw, 0]} material={material} castShadow receiveShadow>
      <boxGeometry args={[segment.length, segment.height, wall.thickness]} />
    </mesh>
  );
}

function WallMesh({ wall, openings, tint }: { wall: Wall; openings: Opening[]; tint?: string | null }) {
  const { segments, yaw, length } = useMemo(() => {
    const dx = wall.end[0] - wall.start[0];
    const dz = wall.end[1] - wall.start[1];
    return {
      segments: wallSegments(wall, openings),
      yaw: -Math.atan2(dz, dx),
      length: Math.hypot(dx, dz),
    };
  }, [wall, openings]);

  if (length < 1e-6) return null;
  const dirX = (wall.end[0] - wall.start[0]) / length;
  const dirZ = (wall.end[1] - wall.start[1]) / length;

  return (
    <group>
      {segments.map((segment, i) => (
        <group key={`${wall.wall_id}_${i}`}>
          <WallSegmentMesh
            wall={wall}
            segment={segment}
            yaw={yaw}
            tint={tint}
            position={[
              wall.start[0] + dirX * segment.center,
              segment.bottom + segment.height / 2,
              wall.start[1] + dirZ * segment.center,
            ]}
          />
          {/* baseboard on floor-touching segments */}
          {segment.bottom === 0 ? (
            <mesh
              position={[
                wall.start[0] + dirX * segment.center,
                0.045,
                wall.start[1] + dirZ * segment.center,
              ]}
              rotation={[0, yaw, 0]}
            >
              <boxGeometry args={[segment.length, 0.09, wall.thickness + 0.025]} />
              <meshStandardMaterial color={TRIM_COLOR} roughness={0.5} />
            </mesh>
          ) : null}
        </group>
      ))}
      {openings.map((opening) => (
        <OpeningFrame
          key={opening.opening_id}
          opening={opening}
          yaw={yaw}
          origin={wall.start}
          direction={[dirX, dirZ]}
          thickness={wall.thickness}
        />
      ))}
    </group>
  );
}

/* ── Furniture shapes ──────────────────────────────────────────────────── */

function SeatShape({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  const fabric = useFabricMaterial(obj.color);
  const cushionFabric = useFabricMaterial(obj.color);
  const armW = Math.min(0.16, w * 0.12);
  const innerW = w - armW * 2;
  const baseH = h * 0.42;
  const backT = d * 0.22;
  const cushions = obj.semantic_type === "sofa" ? 3 : obj.semantic_type === "loveseat" ? 2 : 1;
  const cushionW = (innerW - 0.02 * (cushions - 1)) / cushions;
  return (
    <group>
      {/* base */}
      <RoundedBox args={[w, baseH, d]} radius={0.04} position={[0, baseH / 2, 0]} castShadow material={fabric} />
      {/* arms */}
      <RoundedBox args={[armW, h * 0.75, d]} radius={0.04} position={[-w / 2 + armW / 2, (h * 0.75) / 2, 0]} castShadow material={fabric} />
      <RoundedBox args={[armW, h * 0.75, d]} radius={0.04} position={[w / 2 - armW / 2, (h * 0.75) / 2, 0]} castShadow material={fabric} />
      {/* backrest */}
      <RoundedBox args={[innerW, h - baseH * 0.4, backT]} radius={0.05} position={[0, (h + baseH * 0.6) / 2, d / 2 - backT / 2]} castShadow material={fabric} />
      {/* seat cushions */}
      {Array.from({ length: cushions }, (_, i) => (
        <RoundedBox
          key={i}
          args={[cushionW, h * 0.16, d - backT - 0.06]}
          radius={0.05}
          position={[
            -innerW / 2 + cushionW / 2 + i * (cushionW + 0.02),
            baseH + h * 0.08,
            -backT / 2 + 0.02,
          ]}
          castShadow
          material={cushionFabric}
        />
      ))}
    </group>
  );
}

function TableShape({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  const wood = useWoodMaterial("#a98a67");
  const topT = Math.min(0.05, h * 0.15);
  const inset = 0.07;
  const legPositions: Array<[number, number]> = [
    [w / 2 - inset, d / 2 - inset],
    [-(w / 2 - inset), d / 2 - inset],
    [w / 2 - inset, -(d / 2 - inset)],
    [-(w / 2 - inset), -(d / 2 - inset)],
  ];
  return (
    <group>
      <RoundedBox args={[w, topT, d]} radius={0.02} position={[0, h - topT / 2, 0]} castShadow material={wood} />
      {legPositions.map(([x, z], i) => (
        <mesh key={i} position={[x, (h - topT) / 2, z]} castShadow material={wood}>
          <cylinderGeometry args={[0.02, 0.032, h - topT, 10]} />
        </mesh>
      ))}
    </group>
  );
}

function BedShape({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  const wood = useWoodMaterial("#6b543c");
  const linenWhite = useFabricMaterial("#f0e9dc");
  const duvet = useFabricMaterial(obj.color);
  const frameH = h * 0.35;
  return (
    <group>
      {/* frame + headboard */}
      <RoundedBox args={[w + 0.06, frameH, d + 0.06]} radius={0.02} position={[0, frameH / 2, 0]} castShadow material={wood} />
      <RoundedBox args={[w + 0.06, h * 1.9, 0.09]} radius={0.03} position={[0, (h * 1.9) / 2, d / 2]} castShadow material={wood} />
      {/* mattress */}
      <RoundedBox args={[w, h * 0.4, d]} radius={0.05} position={[0, frameH + h * 0.2, 0]} castShadow material={linenWhite} />
      {/* duvet over the lower two-thirds */}
      <RoundedBox args={[w + 0.02, h * 0.18, d * 0.68]} radius={0.06} position={[0, frameH + h * 0.42, -d * 0.16]} castShadow material={duvet} />
      {/* pillows */}
      <RoundedBox args={[w * 0.4, 0.11, 0.4]} radius={0.05} position={[-w * 0.22, frameH + h * 0.48, d / 2 - 0.3]} rotation={[-0.28, 0, 0]} castShadow material={linenWhite} />
      <RoundedBox args={[w * 0.4, 0.11, 0.4]} radius={0.05} position={[w * 0.22, frameH + h * 0.48, d / 2 - 0.3]} rotation={[-0.28, 0, 0]} castShadow material={linenWhite} />
    </group>
  );
}

function WardrobeShape({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  const wood = useWoodMaterial(obj.color);
  return (
    <group>
      <RoundedBox args={[w, h, d]} radius={0.015} position={[0, h / 2, 0]} castShadow material={wood} />
      {/* door seam + handles on the front (-Z) */}
      <mesh position={[0, h / 2, -d / 2 - 0.002]}>
        <boxGeometry args={[0.012, h * 0.94, 0.004]} />
        <meshStandardMaterial color="#2e2318" roughness={0.6} />
      </mesh>
      {[-0.06, 0.06].map((x) => (
        <mesh key={x} position={[x, h * 0.52, -d / 2 - 0.015]} castShadow>
          <cylinderGeometry args={[0.008, 0.008, 0.14, 8]} />
          <meshStandardMaterial color="#c8a04e" roughness={0.35} metalness={0.7} />
        </mesh>
      ))}
    </group>
  );
}

const BOOK_COLORS = ["#8a5a3b", "#4e5d4a", "#7a6046", "#5a4a5e", "#3f4e5c", "#96684a"];

function BookshelfShape({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  const wood = useWoodMaterial(obj.color);
  const shelves = 4;
  const inner = h - 0.08;
  const shelfGap = inner / shelves;
  return (
    <group>
      {/* carcass: sides, top, bottom, back */}
      <mesh position={[-w / 2 + 0.02, h / 2, 0]} castShadow material={wood}><boxGeometry args={[0.04, h, d]} /></mesh>
      <mesh position={[w / 2 - 0.02, h / 2, 0]} castShadow material={wood}><boxGeometry args={[0.04, h, d]} /></mesh>
      <mesh position={[0, h - 0.02, 0]} castShadow material={wood}><boxGeometry args={[w, 0.04, d]} /></mesh>
      <mesh position={[0, 0.02, 0]} material={wood}><boxGeometry args={[w, 0.04, d]} /></mesh>
      <mesh position={[0, h / 2, d / 2 - 0.01]} material={wood}><boxGeometry args={[w, h, 0.02]} /></mesh>
      {Array.from({ length: shelves - 1 }, (_, i) => (
        <mesh key={i} position={[0, 0.04 + shelfGap * (i + 1), 0]} castShadow material={wood}>
          <boxGeometry args={[w - 0.08, 0.03, d - 0.02]} />
        </mesh>
      ))}
      {/* books: deterministic rows */}
      {Array.from({ length: shelves }, (_, row) =>
        Array.from({ length: 5 }, (_, i) => {
          const bw = 0.035 + ((row * 5 + i) % 3) * 0.012;
          const bh = shelfGap * (0.55 + ((row + i) % 3) * 0.12);
          return (
            <mesh
              key={`${row}_${i}`}
              position={[-w / 2 + 0.1 + i * (w - 0.2) * 0.2, 0.055 + shelfGap * row + bh / 2, -0.02]}
            >
              <boxGeometry args={[bw, bh, d * 0.6]} />
              <meshStandardMaterial color={BOOK_COLORS[(row * 5 + i) % BOOK_COLORS.length]} roughness={0.85} />
            </mesh>
          );
        }),
      )}
    </group>
  );
}

function TvUnitShape({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  const wood = useWoodMaterial(obj.color);
  return (
    <group>
      <RoundedBox args={[w, h, d]} radius={0.015} position={[0, h / 2, 0]} castShadow material={wood} />
      {/* drawer seams */}
      <mesh position={[0, h / 2, -d / 2 - 0.002]}>
        <boxGeometry args={[w * 0.96, 0.008, 0.004]} />
        <meshStandardMaterial color="#2e2318" />
      </mesh>
      {/* TV panel above the unit */}
      <mesh position={[0, h + 0.45, d * 0.25]} castShadow>
        <boxGeometry args={[w * 0.75, w * 0.42, 0.04]} />
        <meshStandardMaterial color="#101010" roughness={0.3} metalness={0.4} />
      </mesh>
      <mesh position={[0, h + 0.45, d * 0.25 - 0.021]}>
        <boxGeometry args={[w * 0.71, w * 0.38, 0.002]} />
        <meshStandardMaterial color="#1a2026" roughness={0.05} metalness={0.6} emissive="#232f3a" emissiveIntensity={0.35} />
      </mesh>
    </group>
  );
}

function PlantShape({ obj }: { obj: SceneObject }) {
  const [w, h] = obj.dimensions;
  const foliage = [
    { pos: [0, h * 0.62, 0], r: w * 0.5 },
    { pos: [w * 0.18, h * 0.76, w * 0.08], r: w * 0.34 },
    { pos: [-w * 0.16, h * 0.7, -w * 0.1], r: w * 0.3 },
    { pos: [0, h * 0.88, 0], r: w * 0.26 },
  ] as const;
  return (
    <group>
      <mesh position={[0, h * 0.14, 0]} castShadow>
        <cylinderGeometry args={[w * 0.34, w * 0.26, h * 0.28, 14]} />
        <meshStandardMaterial color="#9c4f2c" roughness={0.9} />
      </mesh>
      <mesh position={[0, h * 0.4, 0]}>
        <cylinderGeometry args={[0.014, 0.02, h * 0.4, 8]} />
        <meshStandardMaterial color="#5a4630" roughness={0.9} />
      </mesh>
      {foliage.map((f, i) => (
        <mesh key={i} position={f.pos as unknown as [number, number, number]} castShadow>
          <sphereGeometry args={[f.r, 14, 12]} />
          <meshStandardMaterial color={i % 2 ? "#4d6b3f" : obj.color} roughness={1} />
        </mesh>
      ))}
    </group>
  );
}

function LampShape({ obj }: { obj: SceneObject }) {
  const [w, h] = obj.dimensions;
  return (
    <group>
      <mesh position={[0, 0.015, 0]} castShadow>
        <cylinderGeometry args={[w * 0.32, w * 0.36, 0.03, 16]} />
        <meshStandardMaterial color="#3a2f22" roughness={0.4} metalness={0.5} />
      </mesh>
      <mesh position={[0, h * 0.45, 0]} castShadow>
        <cylinderGeometry args={[0.014, 0.014, h * 0.9, 8]} />
        <meshStandardMaterial color="#3a2f22" roughness={0.4} metalness={0.6} />
      </mesh>
      <mesh position={[0, h * 0.88, 0]}>
        <coneGeometry args={[w * 0.5, h * 0.22, 20, 1, true]} />
        <meshStandardMaterial
          color={obj.color}
          roughness={0.6}
          side={THREE.DoubleSide}
          emissive="#ffd9a0"
          emissiveIntensity={1.6}
        />
      </mesh>
      <pointLight position={[0, h * 0.8, 0]} intensity={1.1} distance={5} decay={1.8} color="#ffe2b3" castShadow />
    </group>
  );
}

function RugShape({ obj }: { obj: SceneObject }) {
  const [w, , d] = obj.dimensions;
  const fabric = useFabricMaterial(obj.color);
  const border = useFabricMaterial("#8f7357");
  return (
    <group>
      <RoundedBox args={[w, 0.018, d]} radius={0.008} position={[0, 0.01, 0]} receiveShadow material={border} />
      <RoundedBox args={[w - 0.24, 0.02, d - 0.24]} radius={0.008} position={[0, 0.012, 0]} receiveShadow material={fabric} />
    </group>
  );
}

function BoxShape({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  const wood = useWoodMaterial(obj.color);
  return (
    <RoundedBox args={[w, h, d]} radius={0.02} position={[0, h / 2, 0]} castShadow material={wood} />
  );
}

/* ── Real GLB assets ───────────────────────────────────────────────────── */

const FABRIC_TYPES = new Set(["sofa", "loveseat", "armchair", "ottoman", "chair", "bed", "bar_stool", "pillows", "rug", "curtains"]);

function GlbModel({ url, obj, ownMaterials }: { url: string; obj: SceneObject; ownMaterials: boolean }) {
  const gltf = useGLTF(url);
  const normalized = useMemo(() => {
    const clone = gltf.scene.clone(true);
    const box = new THREE.Box3().setFromObject(clone);
    const size = new THREE.Vector3();
    box.getSize(size);
    if (size.x < 1e-6 || size.y < 1e-6 || size.z < 1e-6) return clone;
    // Scale to catalog dimensions, ground at y=0, center the pivot.
    const scale = Math.min(
      obj.dimensions[0] / size.x,
      obj.dimensions[1] / size.y,
      obj.dimensions[2] / size.z,
    );
    clone.scale.setScalar(scale);
    const scaledBox = new THREE.Box3().setFromObject(clone);
    const center = new THREE.Vector3();
    scaledBox.getCenter(center);
    clone.position.set(-center.x, -scaledBox.min.y, -center.z);
    let largest: THREE.Mesh | null = null;
    let largestSize = 0;
    clone.traverse((node) => {
      if (node instanceof THREE.Mesh) {
        node.castShadow = true;
        node.receiveShadow = true;
        node.geometry.computeBoundingBox();
        const b = node.geometry.boundingBox;
        if (b) {
          const v = (b.max.x - b.min.x) * (b.max.y - b.min.y) * (b.max.z - b.min.z);
          if (v > largestSize) {
            largestSize = v;
            largest = node;
          }
        }
      }
    });
    // Moodboard fidelity: the upholstery of a fabric piece takes the planned
    // colour — but only for a generic catalog model. A piece generated from
    // this project's own approved render already wears the client's fabric,
    // and tinting it throws away the thing the generation was paid for. Same
    // rule the Blender importer follows.
    if (!ownMaterials && largest && FABRIC_TYPES.has(obj.semantic_type) && obj.material_overrides?.primary) {
      const mesh = largest as THREE.Mesh;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      mesh.material = mats.map((m) => {
        const c = (m as THREE.MeshStandardMaterial).clone();
        if ("color" in c) (c as THREE.MeshStandardMaterial).color.set(obj.color);
        return c;
      }) as THREE.Material[];
      if (!Array.isArray(mesh.material) || mesh.material.length === 1) mesh.material = (mesh.material as THREE.Material[])[0];
    }
    return clone;
  }, [gltf, obj.dimensions, obj.semantic_type, obj.material_overrides, obj.color, ownMaterials]);
  return <primitive object={normalized} />;
}

/** The engine's normalized GLB for this asset, or null → parametric fallback. */
function useModelUrl(assetId: string | null, projectId = ""): { url: string | null; ownMaterials: boolean } {
  const [url, setUrl] = useState<string | null>(null);
  const [ownMaterials, setOwn] = useState(false);
  useEffect(() => {
    let alive = true;
    setUrl(null);
    setOwn(false);
    if (!assetId) return;
    void resolveOwnMaterials(assetId, projectId).then((own) => {
      if (alive) setOwn(own);
    });
    void resolveModelUrl(assetId, projectId).then((resolved) => {
      if (alive) setUrl(resolved);
    });
    return () => {
      alive = false;
    };
  }, [assetId, projectId]);
  return { url, ownMaterials };
}

/** Ceiling-mounted objects hang from the ceiling; wall art sits at eye line. */
function mountOffsetY(obj: SceneObject, ceilingHeight: number): number {
  if (obj.mount === "surface") return 0; // the planner already put it on the host's top face
  const height = obj.dimensions[1] * obj.scale[1];
  if (obj.mount === "ceiling") return Math.max(0, ceilingHeight - height - 0.05) - obj.position[1];
  if (obj.mount === "wall" && obj.position[1] < 0.2) return 1.45 - height / 2;
  return 0;
}

/* ── Object dispatch ───────────────────────────────────────────────────── */

const SEAT_TYPES = new Set(["sofa", "loveseat", "armchair", "chair"]);
const TABLE_TYPES = new Set(["coffee_table", "dining_table", "bedside_table"]);

function ParametricShape({ obj }: { obj: SceneObject }) {
  if (SEAT_TYPES.has(obj.semantic_type)) return <SeatShape obj={obj} />;
  if (TABLE_TYPES.has(obj.semantic_type)) return <TableShape obj={obj} />;
  switch (obj.semantic_type) {
    case "bed":
      return <BedShape obj={obj} />;
    case "wardrobe":
      return <WardrobeShape obj={obj} />;
    case "bookshelf":
      return <BookshelfShape obj={obj} />;
    case "tv_unit":
      return <TvUnitShape obj={obj} />;
    case "plant":
      return <PlantShape obj={obj} />;
    case "floor_lamp":
      return <LampShape obj={obj} />;
    case "rug":
      return <RugShape obj={obj} />;
    default:
      return <BoxShape obj={obj} />;
  }
}

/**
 * What is shown while a real model is still loading, or after it failed.
 *
 * Deliberately unmistakable. Without it the Suspense fallback draws a
 * furniture-shaped primitive that reads as the real asset: a plan view full of
 * these was twice reported as "the generated meshes are rendering" when not
 * one of them had loaded. A screenshot has to be able to tell the two apart on
 * its own, with nobody there to explain it.
 *
 * A wireframe cage over a washed-out shape. The cage doubles as useful
 * information — it is the volume the piece has been allotted — but its real
 * job is to look like scaffolding rather than furniture.
 */
function PendingAsset({ obj }: { obj: SceneObject }) {
  const [w, h, d] = obj.dimensions;
  return (
    <group>
      <ParametricShape obj={obj} />
      <mesh position={[0, h / 2, 0]}>
        <boxGeometry args={[w + 0.03, h + 0.03, d + 0.03]} />
        <meshBasicMaterial color="#6E7B8F" wireframe transparent opacity={0.85} />
      </mesh>
      <mesh position={[0, h / 2, 0]}>
        <boxGeometry args={[w, h, d]} />
        <meshBasicMaterial color="#AEB8C6" transparent opacity={0.35} depthWrite={false} />
      </mesh>
    </group>
  );
}

export function FurnitureMesh({
  obj,
  projectId = "",
  selected,
  onSelect,
  ceilingHeight = 2.8,
}: {
  obj: SceneObject;
  /** Scopes the model lookup: pieces generated for this project are only in
   *  this project's catalog, and without it every one falls back to a box. */
  projectId?: string;
  selected: boolean;
  onSelect?: (id: string) => void;
  ceilingHeight?: number;
}) {
  const { url: modelUrl, ownMaterials } = useModelUrl(obj.asset_id, projectId);
  const [w, h, d] = obj.dimensions;
  const liftY = mountOffsetY(obj, ceilingHeight);

  return (
    <group
      position={[obj.position[0], obj.position[1] + liftY, obj.position[2]]}
      rotation={[0, obj.rotation_y, 0]}
      scale={obj.scale}
      onClick={(event) => {
        event.stopPropagation();
        onSelect?.(obj.object_id);
      }}
    >
      {modelUrl ? (
        <Suspense fallback={<PendingAsset obj={obj} />}>
          <GlbModel url={modelUrl} obj={obj} ownMaterials={ownMaterials} />
        </Suspense>
      ) : (
        <ParametricShape obj={obj} />
      )}
      {selected ? (
        <mesh position={[0, h / 2, 0]}>
          <boxGeometry args={[w + 0.06, h + 0.06, d + 0.06]} />
          <meshBasicMaterial color="#B88538" wireframe transparent opacity={0.9} />
        </mesh>
      ) : null}
    </group>
  );
}

/* ── Whole scene ───────────────────────────────────────────────────────── */

export function SceneMeshes({
  scene,
  showCeilings,
  selectedId,
  onSelect,
  ghostObjects,
}: {
  scene: AetherScene;
  showCeilings: boolean;
  selectedId: string | null;
  onSelect?: (id: string | null) => void;
  ghostObjects?: SceneObject[];
}) {
  return (
    <group>
      {/* Soft warm downlight per room — interiors get almost nothing from a
          sun outside the walls, so each room carries its own practical. */}
      {scene.rooms.map((room) => {
        const xs = room.boundary.map((p) => p[0]);
        const zs = room.boundary.map((p) => p[1]);
        const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
        const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
        return (
          <pointLight
            key={`light_${room.room_id}`}
            position={[cx, room.ceiling_height - 0.25, cz]}
            intensity={14}
            distance={9}
            decay={1.6}
            color="#ffe8c8"
          />
        );
      })}
      {scene.rooms.map((room) => (
        <RoomFloor key={room.room_id} room={room} />
      ))}
      {showCeilings
        ? scene.rooms.map((room) => <RoomCeiling key={room.room_id} room={room} />)
        : null}
      {scene.walls.map((wall) => (
        <WallMesh
          key={wall.wall_id}
          wall={wall}
          openings={scene.openings.filter((o) => o.wall_id === wall.wall_id)}
          tint={scene.style?.palette?.[0] ?? null}
        />
      ))}
      {scene.objects.map((obj) => (
        <FurnitureMesh
          key={obj.object_id}
          obj={obj}
          projectId={scene.project_id}
          selected={obj.object_id === selectedId}
          onSelect={(id) => onSelect?.(id)}
          ceilingHeight={
            scene.rooms.find((r) => r.room_id === obj.room_id)?.ceiling_height ?? 2.8
          }
        />
      ))}
      {(ghostObjects ?? []).map((obj) => (
        <group
          key={`ghost_${obj.object_id}`}
          position={obj.position}
          rotation={[0, obj.rotation_y, 0]}
        >
          <mesh position={[0, obj.dimensions[1] / 2, 0]}>
            <boxGeometry args={[obj.dimensions[0], obj.dimensions[1], obj.dimensions[2]]} />
            <meshStandardMaterial color="#B88538" transparent opacity={0.4} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
