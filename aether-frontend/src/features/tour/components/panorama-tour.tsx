"use client";

/**
 * 360° panorama tour: one equirectangular sphere per node, drag to look,
 * hotspots to linked nodes, autoplay along the route, floor-plan minimap.
 *
 * Coordinates are the scene's own frame (x right, y up, z toward viewer).
 * The panorama's image centre is the node's forward direction, so the sphere
 * is rotated by (yaw − π/2) about Y; hotspots are placed straight along the
 * scene-space direction to their target node, which makes them line up with
 * the rendered doorway without any per-render calibration.
 */

import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { fileUrl } from "../api/tour-api";
import type { TourNode, TourPackage } from "../types";
import { TourMinimap } from "./tour-minimap";

const RADIUS = 50;
const HOTSPOT_RADIUS = 30;

interface LookState {
  lon: number; // scene yaw (radians): 0 looks toward −Z, +π/2 toward −X
  lat: number;
  fov: number;
  dragging: boolean;
  lastX: number;
  lastY: number;
  idleSince: number;
}

function direction(lon: number, lat: number): THREE.Vector3 {
  const c = Math.cos(lat);
  return new THREE.Vector3(-Math.sin(lon) * c, Math.sin(lat), -Math.cos(lon) * c);
}

function PanoSphere({ url, yaw, onReady }: { url: string; yaw: number; onReady?: () => void }) {
  const texture = useLoader(THREE.TextureLoader, url);
  useEffect(() => {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.minFilter = THREE.LinearFilter;
    // seen from inside, an equirect must be mirrored horizontally
    texture.wrapS = THREE.RepeatWrapping;
    texture.repeat.x = -1;
    texture.needsUpdate = true;
    onReady?.();
  }, [texture, onReady]);
  // Back faces + mirrored texture: image centre lands on +X, image-right on +Z,
  // so rotating by (yaw + π/2) about Y puts the centre on the scene forward
  // direction and keeps left/right correct.
  return (
    <mesh rotation={[0, yaw + Math.PI / 2, 0]}>
      <sphereGeometry args={[RADIUS, 64, 32]} />
      <meshBasicMaterial map={texture} side={THREE.BackSide} toneMapped={false} />
    </mesh>
  );
}

/** Dev-only: expose the R3F state so the scene can be inspected from the console. */
function DebugState() {
  const state = useThree();
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      (window as unknown as { __tourState?: unknown }).__tourState = state;
    }
  }, [state]);
  return null;
}

function LookCamera({ look, autoRotate }: { look: React.MutableRefObject<LookState>; autoRotate: boolean }) {
  const { camera } = useThree();
  useFrame((_, delta) => {
    const s = look.current;
    if (autoRotate && !s.dragging && performance.now() - s.idleSince > 2500) {
      s.lon += delta * 0.08;
    }
    const target = direction(s.lon, s.lat);
    camera.lookAt(target);
    const cam = camera as THREE.PerspectiveCamera;
    if (Math.abs(cam.fov - s.fov) > 0.01) {
      cam.fov = s.fov;
      cam.updateProjectionMatrix();
    }
  });
  return null;
}

function Hotspot({ from, to, onSelect }: { from: TourNode; to: TourNode; onSelect: (id: string) => void }) {
  const position = useMemo(() => {
    const dx = to.position[0] - from.position[0];
    const dz = to.position[2] - from.position[2];
    const d = Math.hypot(dx, dz) || 1;
    // slightly below the horizon so the chip sits near the floor line
    return new THREE.Vector3((dx / d) * HOTSPOT_RADIUS, -HOTSPOT_RADIUS * 0.18, (dz / d) * HOTSPOT_RADIUS);
  }, [from, to]);
  return (
    <Html position={position} center zIndexRange={[10, 0]} style={{ pointerEvents: "auto" }}>
      <button
        type="button"
        onClick={() => onSelect(to.id)}
        className="group flex flex-col items-center gap-1 focus:outline-none"
        aria-label={`Go to ${to.label}`}
      >
        <span className="flex h-9 w-9 items-center justify-center rounded-full border-2 border-white/90 bg-white/25 shadow-lg backdrop-blur transition group-hover:scale-110 group-hover:bg-white/50 group-focus-visible:ring-2 group-focus-visible:ring-white">
          <span className="h-2.5 w-2.5 rounded-full bg-white" />
        </span>
        <span className="whitespace-nowrap rounded-full bg-black/55 px-2.5 py-0.5 text-xs font-medium text-white">
          {to.label}
        </span>
      </button>
    </Html>
  );
}

export interface PanoramaTourProps {
  pkg: TourPackage;
  initialNodeId?: string;
  autoplay?: boolean;
  onNodeChange?: (node: TourNode) => void;
  className?: string;
}

export function PanoramaTour({ pkg, initialNodeId, autoplay = false, onNodeChange, className }: PanoramaTourProps) {
  const nodes = pkg.tour.nodes;
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const [currentId, setCurrentId] = useState(initialNodeId ?? pkg.tour.route[0] ?? nodes[0]?.id);
  const [previousId, setPreviousId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(autoplay);
  const current = byId.get(currentId) ?? nodes[0];
  const previous = previousId ? byId.get(previousId) : undefined;
  const [readyId, setReadyId] = useState<string | null>(null);
  const onCurrentReady = useCallback(() => setReadyId(currentId), [currentId]);
  const ready = readyId === currentId;

  // Once the first panorama is on screen, warm the cache for the others so hops are instant.
  useEffect(() => {
    if (readyId === null) return;
    const urls = nodes.filter((n) => n.id !== readyId).map((n) => fileUrl(n.pano_url));
    const timer = setTimeout(() => useLoader.preload(THREE.TextureLoader, urls), 200);
    return () => clearTimeout(timer);
    // only the first ready node should trigger the warm-up
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readyId === null, nodes]);
  const look = useRef<LookState>({
    lon: current?.yaw ?? 0,
    lat: 0,
    fov: 75,
    dragging: false,
    lastX: 0,
    lastY: 0,
    idleSince: performance.now(),
  });

  const goTo = useCallback(
    (id: string) => {
      const node = byId.get(id);
      if (!node || id === currentId) return;
      setPreviousId(currentId);
      setCurrentId(id);
      look.current.lon = node.yaw;
      look.current.lat = 0;
      look.current.idleSince = performance.now();
      onNodeChange?.(node);
    },
    [byId, currentId, onNodeChange],
  );

  // autoplay along the route: the dwell only starts once the panorama is on screen
  useEffect(() => {
    if (!playing || !ready) return;
    const seconds = pkg.tour.autoplay_seconds_per_node || 6;
    const timer = setTimeout(() => {
      const route = pkg.tour.route;
      const i = route.indexOf(currentId);
      goTo(route[(i + 1) % route.length]);
    }, seconds * 1000);
    return () => clearTimeout(timer);
  }, [playing, ready, currentId, pkg.tour, goTo]);

  const onPointerDown = (e: React.PointerEvent) => {
    look.current.dragging = true;
    look.current.lastX = e.clientX;
    look.current.lastY = e.clientY;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const s = look.current;
    if (!s.dragging) return;
    const dx = e.clientX - s.lastX;
    const dy = e.clientY - s.lastY;
    s.lastX = e.clientX;
    s.lastY = e.clientY;
    const speed = (s.fov / 75) * 0.0035;
    s.lon += dx * speed; // drag right → look left, like grabbing the picture
    s.lat = Math.max(-1.2, Math.min(1.2, s.lat + dy * speed));
    s.idleSince = performance.now();
  };
  const onPointerUp = () => {
    look.current.dragging = false;
    look.current.idleSince = performance.now();
  };
  const onWheel = (e: React.WheelEvent) => {
    const s = look.current;
    s.fov = Math.max(35, Math.min(95, s.fov + e.deltaY * 0.03));
  };

  if (!current) {
    return <div className={className}>No panoramas in this tour yet.</div>;
  }

  const links = current.links.map((id) => byId.get(id)).filter((n): n is TourNode => Boolean(n));

  return (
    <div className={`relative select-none overflow-hidden bg-black ${className ?? ""}`}>
      <div
        className="absolute inset-0 cursor-grab touch-none active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={onWheel}
      >
        <Canvas camera={{ position: [0, 0, 0], fov: 75, near: 0.1, far: 200 }} dpr={[1, 1.5]} gl={{ antialias: true }}>
          <DebugState />
          <LookCamera look={look} autoRotate={playing} />
          {/* While the next panorama decodes, keep showing the one we came from. */}
          <Suspense
            fallback={
              previous ? (
                <PanoSphere key={`prev-${previous.id}`} url={fileUrl(previous.pano_url)} yaw={previous.yaw} />
              ) : (
                <Html center>
                  <span className="whitespace-nowrap rounded-full bg-white/15 px-3 py-1 text-xs text-white/80">
                    Loading panorama…
                  </span>
                </Html>
              )
            }
          >
            <PanoSphere key={current.id} url={fileUrl(current.pano_url)} yaw={current.yaw} onReady={onCurrentReady} />
          </Suspense>
          {links.map((to) => (
            <Hotspot key={to.id} from={current} to={to} onSelect={goTo} />
          ))}
        </Canvas>
      </div>

      {/* top-left: where we are */}
      <div className="pointer-events-none absolute left-4 top-4 flex flex-col gap-1">
        <span className="rounded-full bg-black/55 px-3 py-1 text-sm font-medium text-white backdrop-blur">
          {current.label}
        </span>
        <span className="rounded-full bg-black/35 px-3 py-0.5 text-[11px] uppercase tracking-wider text-white/80">
          {pkg.quality === "final" ? "final render" : "preview render"} · drag to look · scroll to zoom
          {!ready ? " · loading…" : ""}
        </span>
      </div>

      {/* bottom: route chips + autoplay */}
      <div className="absolute inset-x-0 bottom-0 flex flex-wrap items-end justify-between gap-3 bg-gradient-to-t from-black/70 to-transparent p-4">
        <div className="flex flex-wrap gap-2">
          {pkg.tour.route.map((id) => {
            const n = byId.get(id);
            if (!n) return null;
            const active = id === currentId;
            return (
              <button
                key={id}
                type="button"
                onClick={() => goTo(id)}
                className={`rounded-full px-3 py-1 text-xs font-medium backdrop-blur transition ${
                  active ? "bg-white text-black" : "bg-white/20 text-white hover:bg-white/35"
                }`}
              >
                {n.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            className="rounded-full bg-white/20 px-3 py-1 text-xs font-medium text-white backdrop-blur hover:bg-white/35"
            aria-pressed={playing}
          >
            {playing ? "Pause tour" : "Play tour"}
          </button>
          <TourMinimap pkg={pkg} currentId={currentId} onSelect={goTo} />
        </div>
      </div>
    </div>
  );
}
