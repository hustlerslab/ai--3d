"use client";

import { useMemo } from "react";

import type { TourPackage } from "../types";

/** Top-down floor plan (scene x → right, scene z → down) with clickable nodes. */
export function TourMinimap({
  pkg,
  currentId,
  onSelect,
  size = 150,
}: {
  pkg: TourPackage;
  currentId: string;
  onSelect: (id: string) => void;
  size?: number;
}) {
  const { view, rooms, nodes } = useMemo(() => {
    const pts = pkg.rooms.flatMap((r) => r.boundary);
    const xs = pts.map((p) => p[0]);
    const zs = pts.map((p) => p[1]);
    const minX = Math.min(...xs, 0);
    const maxX = Math.max(...xs, 1);
    const minZ = Math.min(...zs, 0);
    const maxZ = Math.max(...zs, 1);
    const pad = 0.4;
    const w = maxX - minX + pad * 2;
    const h = maxZ - minZ + pad * 2;
    const scale = size / Math.max(w, h);
    const sx = (x: number) => (x - minX + pad) * scale;
    const sz = (z: number) => (z - minZ + pad) * scale;
    return {
      view: { w: w * scale, h: h * scale },
      rooms: pkg.rooms.map((r) => ({
        id: r.room_id,
        points: r.boundary.map((p) => `${sx(p[0]).toFixed(1)},${sz(p[1]).toFixed(1)}`).join(" "),
      })),
      nodes: pkg.tour.nodes.map((n) => ({ id: n.id, label: n.label, x: sx(n.position[0]), y: sz(n.position[2]) })),
    };
  }, [pkg, size]);

  return (
    <svg
      width={view.w}
      height={view.h}
      viewBox={`0 0 ${view.w} ${view.h}`}
      className="rounded-md bg-black/45 backdrop-blur"
      role="img"
      aria-label="Floor plan with tour stops"
    >
      {rooms.map((r) => (
        <polygon key={r.id} points={r.points} fill="rgba(255,255,255,0.12)" stroke="rgba(255,255,255,0.7)" strokeWidth={1} />
      ))}
      {nodes.map((n) => {
        const active = n.id === currentId;
        return (
          <g key={n.id} onClick={() => onSelect(n.id)} className="cursor-pointer">
            <title>{n.label}</title>
            <circle cx={n.x} cy={n.y} r={active ? 6 : 4} fill={active ? "#f3c96b" : "rgba(255,255,255,0.85)"} stroke="#000" strokeWidth={0.8} />
          </g>
        );
      })}
    </svg>
  );
}
