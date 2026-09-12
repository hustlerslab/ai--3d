"use client";

/**
 * Camera rigs: first-person walking and guided-tour playback.
 *
 * Camera state is frontend state (plan §36) — nothing here writes to the
 * canonical scene. First-person movement is collision-checked locally with
 * the same rules the backend enforces.
 */

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { SpawnPoint, TourPath } from "../types/scene";
import { EYE_HEIGHT, tryMove, type WalkWorld } from "../utils/collision";

const WALK_SPEED = 2.2; // m/s
const LOOK_SENSITIVITY = 0.0022; // radians per pixel of mouse movement
const PITCH_LIMIT = 1.45; // just short of straight up/down

/**
 * Browsers refuse to re-acquire pointer lock for a moment after Esc releases
 * it; asking again inside that window throws a SecurityError. Anything after
 * this cooldown is safe.
 */
const RELOCK_COOLDOWN_MS = 1600;

/**
 * First-person rig with its own look handling instead of drei's
 * PointerLockControls. Pointer lock is attempted politely — cooldown
 * respected, rejection swallowed — and when it is unavailable at all
 * (iframes, permission policies) dragging the scene looks around instead,
 * so walking never breaks.
 */
export function FirstPersonRig({
  world,
  spawn,
  onLockChange,
}: {
  world: WalkWorld;
  spawn: SpawnPoint;
  onLockChange?: (locked: boolean) => void;
}) {
  const { camera, gl } = useThree();
  const keys = useRef<Record<string, boolean>>({});
  const look = useRef({ yaw: 0, pitch: 0 });
  const locked = useRef(false);
  const dragging = useRef(false);
  const lastUnlockAt = useRef(0);

  useEffect(() => {
    camera.position.set(spawn.position[0], EYE_HEIGHT, spawn.position[2]);
    camera.lookAt(spawn.look_at[0], spawn.look_at[1], spawn.look_at[2]);
    const euler = new THREE.Euler().setFromQuaternion(camera.quaternion, "YXZ");
    look.current = { yaw: euler.y, pitch: euler.x };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spawn]);

  useEffect(() => {
    const dom = gl.domElement;

    const applyLook = (dx: number, dy: number) => {
      look.current.yaw -= dx * LOOK_SENSITIVITY;
      look.current.pitch = Math.max(
        -PITCH_LIMIT,
        Math.min(PITCH_LIMIT, look.current.pitch - dy * LOOK_SENSITIVITY),
      );
      camera.quaternion.setFromEuler(
        new THREE.Euler(look.current.pitch, look.current.yaw, 0, "YXZ"),
      );
    };

    const requestLock = () => {
      if (document.pointerLockElement === dom) return;
      if (performance.now() - lastUnlockAt.current < RELOCK_COOLDOWN_MS) return;
      try {
        // Newer browsers return a Promise that rejects instead of throwing.
        const result = dom.requestPointerLock?.() as unknown;
        if (result instanceof Promise) result.catch(() => {});
      } catch {
        /* pointer lock unavailable — drag-look still works */
      }
    };

    const handleLockChange = () => {
      const isLocked = document.pointerLockElement === dom;
      if (!isLocked && locked.current) lastUnlockAt.current = performance.now();
      locked.current = isLocked;
      onLockChange?.(isLocked);
    };
    const handleLockError = () => {
      lastUnlockAt.current = performance.now();
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      if (!locked.current) {
        dragging.current = true;
        requestLock();
      }
    };
    const handlePointerUp = () => {
      dragging.current = false;
    };
    const handlePointerMove = (event: PointerEvent) => {
      if (locked.current || dragging.current) {
        applyLook(event.movementX, event.movementY);
      }
    };

    dom.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerlockchange", handleLockChange);
    document.addEventListener("pointerlockerror", handleLockError);
    return () => {
      dom.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerlockchange", handleLockChange);
      document.removeEventListener("pointerlockerror", handleLockError);
      if (document.pointerLockElement === dom) document.exitPointerLock();
    };
  }, [gl, camera, onLockChange]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      keys.current[e.code] = true;
    };
    const up = (e: KeyboardEvent) => {
      keys.current[e.code] = false;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  useFrame((_, delta) => {
    const k = keys.current;
    let forward = 0;
    let strafe = 0;
    if (k.KeyW || k.ArrowUp) forward += 1;
    if (k.KeyS || k.ArrowDown) forward -= 1;
    if (k.KeyA || k.ArrowLeft) strafe -= 1;
    if (k.KeyD || k.ArrowRight) strafe += 1;
    if (!forward && !strafe) return;

    const direction = new THREE.Vector3();
    camera.getWorldDirection(direction);
    direction.y = 0;
    direction.normalize();
    const side = new THREE.Vector3()
      .crossVectors(direction, new THREE.Vector3(0, 1, 0))
      .normalize();

    const step = WALK_SPEED * Math.min(delta, 0.05);
    const dx = (direction.x * forward + side.x * strafe) * step;
    const dz = (direction.z * forward + side.z * strafe) * step;

    const next = tryMove(world, [camera.position.x, camera.position.z], dx, dz);
    camera.position.set(next[0], EYE_HEIGHT, next[1]);
  });

  return null;
}

/* ── Guided tour ───────────────────────────────────────────────────────── */

interface TourSegment {
  start: number;
  end: number;
  fromPos: THREE.Vector3;
  toPos: THREE.Vector3;
  fromLook: THREE.Vector3;
  toLook: THREE.Vector3;
  label: string;
}

function smoothstep(t: number): number {
  return t * t * (3 - 2 * t);
}

export function TourRig({
  tour,
  playing,
  onProgress,
  onEnd,
}: {
  tour: TourPath;
  playing: boolean;
  onProgress?: (elapsed: number, label: string) => void;
  onEnd?: () => void;
}) {
  const { camera } = useThree();
  const elapsed = useRef(0);
  const ended = useRef(false);

  const segments = useMemo<TourSegment[]>(() => {
    const result: TourSegment[] = [];
    let clock = 0;
    let prevPos: THREE.Vector3 | null = null;
    let prevLook: THREE.Vector3 | null = null;
    for (const kf of tour.keyframes) {
      const pos = new THREE.Vector3(...kf.position);
      const look = new THREE.Vector3(...kf.look_at);
      if (prevPos === null || prevLook === null) {
        prevPos = pos;
        prevLook = look;
        continue;
      }
      const duration = Math.max(kf.duration, 0.4);
      result.push({
        start: clock,
        end: clock + duration,
        fromPos: prevPos,
        toPos: pos,
        fromLook: prevLook,
        toLook: look,
        label: kf.label,
      });
      clock += duration;
      prevPos = pos;
      prevLook = look;
    }
    return result;
  }, [tour]);

  const totalDuration = segments.length
    ? segments[segments.length - 1].end
    : 0;

  useEffect(() => {
    elapsed.current = 0;
    ended.current = false;
    if (tour.keyframes.length > 0) {
      const first = tour.keyframes[0];
      camera.position.set(...first.position);
      camera.lookAt(...first.look_at);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tour]);

  useFrame((_, delta) => {
    if (!playing || ended.current || segments.length === 0) return;
    elapsed.current = Math.min(elapsed.current + delta, totalDuration);
    const t = elapsed.current;

    const segment =
      segments.find((s) => t >= s.start && t <= s.end) ??
      segments[segments.length - 1];
    const local = smoothstep(
      Math.min(1, Math.max(0, (t - segment.start) / (segment.end - segment.start))),
    );

    const pos = segment.fromPos.clone().lerp(segment.toPos, local);
    const look = segment.fromLook.clone().lerp(segment.toLook, local);
    camera.position.copy(pos);
    camera.lookAt(look);

    onProgress?.(t, segment.label);

    if (t >= totalDuration && !ended.current) {
      ended.current = true;
      onEnd?.();
    }
  });

  return null;
}
