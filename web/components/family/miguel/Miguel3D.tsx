"use client";

// The stage Miguel stands on: a WebGL canvas with soft studio light, drag to turn him,
// tap to say hi. Loaded with next/dynamic (no SSR) by MiguelStage.

import { Environment, Lightformer } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useRef, type PointerEvent } from "react";
import { MiguelModel, type MiguelControls, type MiguelPose } from "./MiguelModel";

export interface Miguel3DProps {
  pose: MiguelPose;
  /** "full" frames all of him; "head" frames the phone and tray. */
  framing?: "full" | "head";
  interactive?: boolean;
  onTap?: () => void;
}

// A slight three-quarter view: you see the gold edge of the phone, the wheel treads and depth.
const FRAMING = {
  full: { position: [3.1, 3.25, 12.2] as [number, number, number], target: [0, 2.66, 0] as [number, number, number], fov: 27 },
  head: { position: [1.6, 4.6, 6.6] as [number, number, number], target: [0, 4.2, 0] as [number, number, number], fov: 27 },
};

export default function Miguel3D({ pose, framing = "full", interactive = true, onTap }: Miguel3DProps) {
  const controls = useRef<MiguelControls>({ dragYaw: 0, dragging: false, tapAt: 0 });
  const drag = useRef<{ id: number; x: number; y: number; startYaw: number; moved: boolean } | null>(null);
  const release = useRef<ReturnType<typeof setTimeout> | null>(null);
  const f = FRAMING[framing];

  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!interactive) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, startYaw: controls.current.dragYaw, moved: false };
    if (release.current) clearTimeout(release.current);
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.abs(dx) > 6 && Math.abs(dx) > Math.abs(dy)) {
      d.moved = true;
      controls.current.dragging = true;
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    if (d.moved) controls.current.dragYaw = d.startYaw + dx * 0.012;
  };
  const onUp = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    drag.current = null;
    if (!d.moved) {
      controls.current.tapAt = performance.now();
      onTap?.();
      return;
    }
    controls.current.dragging = false;
    // Let him be admired for a moment, then turn back to face you.
    release.current = setTimeout(() => {
      const yaw = controls.current.dragYaw;
      controls.current.dragYaw = Math.round(yaw / (Math.PI * 2)) * Math.PI * 2;
    }, 2200);
  };

  return (
    <div
      className="h-full w-full"
      style={{ touchAction: "pan-y" }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
    >
      <Canvas
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={{ position: f.position, fov: f.fov, near: 0.1, far: 100 }}
        onCreated={({ camera }) => camera.lookAt(...f.target)}
      >
        <hemisphereLight args={["#fff4e2", "#d9ccb6", 0.8]} />
        <directionalLight position={[-5, 7, 7]} intensity={2.9} color="#fff1dc" />
        <directionalLight position={[6, 2.5, 3]} intensity={0.55} color="#dfe8ff" />
        <directionalLight position={[1, 6, -7]} intensity={1.6} color="#ffe9c9" />
        <Environment resolution={128}>
          <Lightformer form="rect" intensity={2.2} position={[0, 4, 6]} scale={[8, 3, 1]} color="#fff1dc" />
          <Lightformer form="rect" intensity={1.2} position={[-6, 2, 0]} rotation={[0, Math.PI / 2, 0]} scale={[6, 4, 1]} color="#ffffff" />
          <Lightformer form="rect" intensity={0.8} position={[6, 2, -2]} rotation={[0, -Math.PI / 2, 0]} scale={[6, 4, 1]} color="#cfdcf5" />
        </Environment>
        <MiguelModel pose={pose} controls={controls} />
      </Canvas>
    </div>
  );
}
