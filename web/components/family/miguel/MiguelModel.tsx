"use client";

// The in-app Miguel: the real robot (docs/reference/john-pack/cad, the GLB John exported),
// rebuilt as a character. Dimensions are the CAD's, in millimetres, softened and simplified;
// the phone head is scaled up a little, like the sticker.
//
// Three.js frame: y up, the face looks toward +z (the viewer). Scale 0.01, so he's ~5 units tall.

import { Outlines, RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type ReactNode, type RefObject } from "react";
import * as THREE from "three";
import type { Expression, MiguelMode } from "@/lib/family/types";
import { drawFace, type FaceParams } from "./face";
import { voiceLevel } from "./voice";

const INK = "#2a2630";

// Stylized proportions: a bigger phone head, chunkier wheels and a shorter mast than the CAD, like the sticker.
const HEAD_SCALE = 1.34;
const WHEEL_SCALE = 1.12;
const AXLE = 43 * WHEEL_SCALE;
const MAST_TOP = 288;

export interface MiguelPose {
  mode: MiguelMode;
  concerned: boolean;
  carrying: boolean;
}

export interface MiguelControls {
  /** Rotation from dragging, radians (written by the stage). */
  dragYaw: number;
  /** Set when the stage is being dragged. */
  dragging: boolean;
  /** performance.now() of the last tap, for the happy wiggle. */
  tapAt: number;
}

// ---------- materials ----------

function useMaterials() {
  return useMemo(() => {
    const m = (color: string, roughness = 0.6, metalness = 0, extra: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
      new THREE.MeshStandardMaterial({ color, roughness, metalness, ...extra });
    return {
      cream: m("#f3eee5", 0.58),
      creamShade: m("#e6dfd2", 0.62),
      blue: m("#a9c4ec", 0.5),
      blueDeep: m("#7fa3d8", 0.5),
      ink: m("#2b2a31", 0.55),
      tire: m("#26252c", 0.92),
      rim: m("#3d3c45", 0.45, 0.25),
      hub: m("#6d6c76", 0.4, 0.4),
      silver: m("#a7a9b1", 0.35, 0.6),
      gold: m("#d8b57a", 0.32, 0.75),
      goldBack: m("#ead6b2", 0.38, 0.35),
      lens: m("#121216", 0.15, 0.4),
      bezel: m("#141317", 0.3),
      pcb: m("#24262a", 0.6),
      green: m("#2f9a62", 0.55),
      red: m("#d7483b", 0.5),
      purple: m("#5b3f8c", 0.5),
      heatsink: m("#3f6fd6", 0.35, 0.5),
      orange: m("#f08a34", 0.5),
      yellow: m("#f2c230", 0.5),
      grey: m("#b9c0c7", 0.55),
      label: m("#3f8f3a", 0.55),
      led: new THREE.MeshStandardMaterial({ color: "#ff4b3e", emissive: "#ff2a1a", emissiveIntensity: 2.2 }),
      display: new THREE.MeshStandardMaterial({ color: "#1a0d0c", emissive: "#ff3b2f", emissiveIntensity: 0.9 }),
      glass: new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.05, transparent: true, opacity: 0.32 }),
      water: new THREE.MeshStandardMaterial({ color: "#8cc3f2", roughness: 0.1, transparent: true, opacity: 0.85 }),
      wire: {
        red: m("#d9483b", 0.45),
        blue: m("#3e6fd8", 0.45),
        orange: m("#f08a2e", 0.45),
        black: m("#26252b", 0.5),
        green: m("#3c9a5f", 0.45),
      },
    };
  }, []);
}

type Mats = ReturnType<typeof useMaterials>;

/** A rounded box with the sticker's ink outline. Position in mm. */
function Block({
  size,
  radius = 3,
  position,
  rotation,
  material,
  outline = true,
  children,
}: {
  size: [number, number, number];
  radius?: number;
  position?: [number, number, number];
  rotation?: [number, number, number];
  material: THREE.Material;
  outline?: boolean;
  children?: ReactNode;
}) {
  return (
    <RoundedBox args={size} radius={radius} smoothness={3} position={position} rotation={rotation} material={material}>
      {outline && <Outlines thickness={1.6} screenspace color={INK} />}
      {children}
    </RoundedBox>
  );
}

// ---------- wheels ----------

function Wheel({ side, mats, spin }: { side: 1 | -1; mats: Mats; spin: RefObject<THREE.Group | null> }) {
  const tireGeo = useMemo(() => {
    // Tire cross-section (radius, axial), rounded shoulders; lathe around the axle.
    const pts = [
      [29, -13.5],
      [37, -15],
      [41.6, -13.6],
      [43, -9],
      [43, 9],
      [41.6, 13.6],
      [37, 15],
      [29, 13.5],
    ].map(([r, y]) => new THREE.Vector2(r, y));
    const g = new THREE.LatheGeometry(pts, 56);
    g.rotateZ(Math.PI / 2); // axle along x
    return g;
  }, []);

  const treads = useMemo(() => {
    const n = 22;
    return Array.from({ length: n }, (_, i) => {
      const a = (i / n) * Math.PI * 2;
      const stagger = i % 2 === 0 ? 4 : -4;
      return { a, stagger };
    });
  }, []);

  return (
    <group position={[side * 79, AXLE, 0]} scale={WHEEL_SCALE}>
      <group ref={spin}>
        <mesh geometry={tireGeo} material={mats.tire}>
          <Outlines thickness={1.6} screenspace color={INK} />
        </mesh>
        {treads.map(({ a, stagger }, i) => (
          <mesh
            key={i}
            material={mats.tire}
            position={[stagger, Math.cos(a) * 43.2, Math.sin(a) * 43.2]}
            rotation={[-a, 0, 0]}
          >
            <boxGeometry args={[14, 3.2, 6]} />
          </mesh>
        ))}
        {/* Rim, hub and spokes on the outer face */}
        <mesh material={mats.rim} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[29.2, 29.2, 24, 40]} />
        </mesh>
        <mesh material={mats.hub} position={[side * 12.6, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[8, 8, 3, 24]} />
        </mesh>
        {[0, 1, 2, 3, 4].map((i) => {
          const a = (i / 5) * Math.PI * 2;
          return (
            <mesh
              key={i}
              material={mats.hub}
              position={[side * 12.4, Math.cos(a) * 17, Math.sin(a) * 17]}
              rotation={[-a, 0, 0]}
            >
              <boxGeometry args={[1.6, 19, 4.2]} />
            </mesh>
          );
        })}
      </group>
    </group>
  );
}

// ---------- wires ----------

function Wire({ points, material, radius = 1.7 }: { points: [number, number, number][]; material: THREE.Material; radius?: number }) {
  const geo = useMemo(() => {
    const curve = new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p)));
    return new THREE.TubeGeometry(curve, 96, radius, 8, false);
  }, [points, radius]);
  return <mesh geometry={geo} material={material} />;
}

function helix(phase: number, turns: number, y0: number, y1: number, rx: number, rz: number): [number, number, number][] {
  const pts: [number, number, number][] = [];
  const n = 40;
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const a = phase + t * turns * Math.PI * 2;
    pts.push([Math.cos(a) * rx, y0 + (y1 - y0) * t, Math.sin(a) * rz]);
  }
  return pts;
}

// ---------- face screen ----------

const SCREEN_W = 66;
const SCREEN_H = 146;

function useScreen() {
  return useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 330;
    canvas.height = Math.round((330 * SCREEN_H) / SCREEN_W);
    const ctx = canvas.getContext("2d")!;
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;

    const r = 9;
    const shape = new THREE.Shape();
    const w = SCREEN_W / 2;
    const h = SCREEN_H / 2;
    shape.moveTo(-w + r, -h);
    shape.lineTo(w - r, -h);
    shape.quadraticCurveTo(w, -h, w, -h + r);
    shape.lineTo(w, h - r);
    shape.quadraticCurveTo(w, h, w - r, h);
    shape.lineTo(-w + r, h);
    shape.quadraticCurveTo(-w, h, -w, h - r);
    shape.lineTo(-w, -h + r);
    shape.quadraticCurveTo(-w, -h, -w + r, -h);
    const geo = new THREE.ShapeGeometry(shape, 12);
    const pos = geo.attributes.position;
    const uv = geo.attributes.uv;
    for (let i = 0; i < pos.count; i++) {
      uv.setXY(i, (pos.getX(i) + w) / SCREEN_W, (pos.getY(i) + h) / SCREEN_H);
    }
    const material = new THREE.MeshBasicMaterial({ map: texture, toneMapped: false });
    return { canvas, ctx, texture, geo, material };
  }, []);
}

type Screen = ReturnType<typeof useScreen>;

/** Draw the face and flag the texture for upload. Kept outside the component: it mutates three.js objects. */
function paintScreen(screen: Screen, p: FaceParams) {
  drawFace(screen.ctx, screen.canvas.width, screen.canvas.height, p);
  screen.texture.needsUpdate = true;
}

// ---------- the character ----------

interface Anim {
  lean: number;
  leanVel: number;
  wheel: number;
  yaw: number;
  kick: number;
  headTilt: number;
  headNod: number;
  headYaw: number;
  carry: number;
  blinkAt: number;
  blinkStart: number;
  lookX: number;
  lookY: number;
  lookTX: number;
  lookTY: number;
  lookAt: number;
  mouth: number;
  frame: number;
  lastTap: number;
}

function modeExpression(pose: MiguelPose, excited: boolean): Expression {
  if (pose.concerned) return "concerned";
  if (excited) return "excited";
  switch (pose.mode) {
    case "delivering":
      return "focused";
    case "charging":
      return "sleepy";
    case "listening":
      return "listening";
    case "nightLight":
      return "night";
    case "offline":
      return "offline";
    default:
      return "happy";
  }
}

export function MiguelModel({ pose, controls }: { pose: MiguelPose; controls: RefObject<MiguelControls> }) {
  const mats = useMaterials();
  const screen = useScreen();

  const root = useRef<THREE.Group>(null);
  const body = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const kickstand = useRef<THREE.Group>(null);
  const wheelL = useRef<THREE.Group>(null);
  const wheelR = useRef<THREE.Group>(null);
  const wires = useRef<THREE.Group>(null);
  const glass = useRef<THREE.Group>(null);
  const shadow = useRef<THREE.Mesh>(null);
  const nightLight = useRef<THREE.PointLight>(null);
  const led = useRef<THREE.Mesh>(null);

  const anim = useRef<Anim>({
    lean: 0,
    leanVel: 0,
    wheel: 0,
    yaw: 0,
    kick: 0,
    headTilt: 0,
    headNod: 0,
    headYaw: 0,
    carry: 0,
    blinkAt: 1.8,
    blinkStart: -1,
    lookX: 0,
    lookY: 0,
    lookTX: 0,
    lookTY: 0,
    lookAt: 2,
    mouth: 0,
    frame: 0,
    lastTap: 0,
  });

  const shadowTex = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d")!;
    const grd = g.createRadialGradient(64, 64, 4, 64, 64, 64);
    grd.addColorStop(0, "rgba(42,38,48,0.55)");
    grd.addColorStop(0.55, "rgba(42,38,48,0.22)");
    grd.addColorStop(1, "rgba(42,38,48,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }, []);

  useEffect(() => {
    return () => {
      screen.texture.dispose();
      screen.geo.dispose();
      shadowTex.dispose();
    };
  }, [screen, shadowTex]);

  const helices = useMemo(
    () => ({
      red: helix(0.2, 1.5, 176, MAST_TOP + 2, 29, 21),
      blue: helix(2.3, 1.3, 172, MAST_TOP, 31, 23),
      orange: helix(4.2, 1.1, 180, MAST_TOP - 4, 30, 22),
      leftBlack: [
        [-30, MAST_TOP + 26, 12],
        [-40, MAST_TOP - 6, 19],
        [-46, 240, 22],
        [-52, 190, 20],
        [-56, 168, 14],
      ] as [number, number, number][],
      rightBlack: [
        [30, MAST_TOP + 26, 12],
        [38, MAST_TOP - 10, 19],
        [44, 236, 22],
        [50, 190, 18],
        [54, 168, 12],
      ] as [number, number, number][],
      greenLoop: [
        [-36, 166, 30],
        [-28, 158, 46],
        [-12, 156, 50],
        [-2, 168, 30],
      ] as [number, number, number][],
    }),
    [],
  );

  useFrame((state, dt) => {
    const a = anim.current;
    const c = controls.current;
    const t = state.clock.elapsedTime;
    const d = Math.min(dt, 1 / 20);
    a.frame += 1;

    // Tap: a happy wiggle and a moment of excitement.
    if (c.tapAt !== a.lastTap) {
      a.lastTap = c.tapAt;
      a.leanVel += 1.4;
    }
    const sinceTap = (performance.now() - a.lastTap) / 1000;
    const excited = a.lastTap > 0 && sinceTap < 1.8;

    // --- body: balancing lean, by mode ---
    const docked = pose.mode === "charging" || pose.mode === "offline";
    const deg = Math.PI / 180;
    let leanBase = 0;
    let sway = 1;
    if (pose.mode === "delivering") leanBase = 5 * deg;
    if (pose.mode === "listening") leanBase = 2.5 * deg;
    if (pose.concerned) leanBase = 1.5 * deg;
    if (docked) {
      leanBase = -9 * deg;
      sway = 0.12;
    }
    if (pose.mode === "nightLight") sway = 0.7;

    const wobble =
      sway * deg * (0.9 * Math.sin(t * 1.7) + 0.5 * Math.sin(t * 3.1 + 1.3) + (pose.concerned ? 0.35 * Math.sin(t * 13) : 0));
    // Spring toward the target lean, so taps and mode changes overshoot a little, like balancing.
    const target = leanBase + wobble;
    const k = docked ? 30 : 46;
    a.leanVel += (-(a.lean - target) * k - a.leanVel * 7.5) * d;
    a.lean += a.leanVel * d;

    // Wheels roll under the lean (that's how it balances); keep rolling while delivering.
    const rolling = pose.mode === "delivering" ? 4.2 : 0;
    a.wheel += rolling * d;
    const wheelAngle = a.wheel + (docked ? 0 : a.lean * 2.4);
    if (excited) {
      // a quick back-and-forth wheel wiggle
      const w = Math.sin(sinceTap * 22) * Math.exp(-sinceTap * 3.2) * 0.45;
      if (wheelL.current) wheelL.current.rotation.x = wheelAngle + w;
      if (wheelR.current) wheelR.current.rotation.x = wheelAngle - w;
    } else {
      if (wheelL.current) wheelL.current.rotation.x = wheelAngle;
      if (wheelR.current) wheelR.current.rotation.x = wheelAngle;
    }

    if (body.current) body.current.rotation.x = a.lean;
    if (root.current) {
      const bob = pose.mode === "delivering" ? Math.abs(Math.sin(t * 7)) * 1.2 : 0;
      root.current.position.z = (docked ? 0 : a.lean * 22) * 0.01;
      root.current.position.y = bob * 0.01;
      // Drag yaw (springs back when released; the stage writes dragYaw)
      a.yaw += (c.dragYaw - a.yaw) * Math.min(1, d * 10);
      root.current.rotation.y = a.yaw;
    }

    // Kickstand down when docked
    a.kick += ((docked ? 1 : 0) - a.kick) * Math.min(1, d * 5);
    if (kickstand.current) kickstand.current.rotation.x = -0.42 * (1 - a.kick) + 0.18 * a.kick;

    // --- head ---
    const level = voiceLevel();
    a.mouth += (level - a.mouth) * Math.min(1, d * (level > a.mouth ? 28 : 14));
    let tiltT = 0;
    let nodT = 0;
    if (pose.mode === "listening") tiltT = 8 * deg;
    if (pose.concerned) nodT = 7 * deg;
    if (pose.mode === "charging") nodT = 4 * deg;
    if (excited) tiltT = Math.sin(sinceTap * 9) * Math.exp(-sinceTap * 2.5) * 10 * deg;
    nodT += a.mouth * 2.2 * deg * Math.sin(t * 9);
    a.headTilt += (tiltT - a.headTilt) * Math.min(1, d * 6);
    a.headNod += (nodT - a.headNod) * Math.min(1, d * 6);
    // He turns his head toward you (the camera), as far as his neck allows.
    const camAngle = Math.atan2(state.camera.position.x, state.camera.position.z);
    const headYawT = c.dragging ? 0 : Math.max(-0.5, Math.min(0.5, camAngle - a.yaw)) * 0.75;
    a.headYaw += (headYawT - a.headYaw) * Math.min(1, d * 4);
    if (head.current) {
      head.current.rotation.y = a.headYaw;
      head.current.rotation.z = a.headTilt;
      head.current.rotation.x = a.headNod + Math.sin(t * 1.1) * 0.6 * deg * sway;
    }

    // Wires sway a little behind the body's motion.
    if (wires.current) {
      wires.current.rotation.x = -a.leanVel * 0.012;
      wires.current.rotation.z = Math.sin(t * 2.3) * 0.004;
    }

    // Tray glass when carrying
    a.carry += ((pose.carrying ? 1 : 0) - a.carry) * Math.min(1, d * 6);
    if (glass.current) {
      const s = a.carry < 0.01 ? 0.0001 : a.carry * 1.3;
      glass.current.scale.setScalar(s);
      glass.current.visible = a.carry > 0.01;
    }

    // Shadow follows the lean
    if (shadow.current) {
      shadow.current.scale.set(1 + Math.abs(a.lean) * 1.5, 1, 1);
      shadow.current.position.z = (docked ? -8 : a.lean * 40) * 0.01;
    }

    // Night-light glow
    if (nightLight.current) {
      const on = pose.mode === "nightLight" ? 1 : 0;
      nightLight.current.intensity += (on * (5.5 + Math.sin(t * 1.4) * 0.5) - nightLight.current.intensity) * Math.min(1, d * 3);
    }
    if (led.current) {
      (led.current.material as THREE.MeshStandardMaterial).emissiveIntensity = pose.mode === "offline" ? 0.2 : 1.6 + Math.sin(t * 5) * 0.8;
    }

    // --- face ---
    // Blink every few seconds (sometimes twice); never while sleepy/offline.
    if (t > a.blinkAt) {
      a.blinkStart = t;
      a.blinkAt = t + 2.2 + ((Math.sin(t * 12.9898) * 43758.5453) % 1 + 1) % 1 * 3.4;
    }
    const bt = t - a.blinkStart;
    let blink = bt >= 0 && bt < 0.17 ? Math.sin((bt / 0.17) * Math.PI) : 0;
    if (pose.mode === "nightLight") blink = Math.max(blink, 0.25);

    // Glance around now and then; look where the user drags.
    if (t > a.lookAt) {
      const r1 = ((Math.sin(t * 78.233) * 12345.6789) % 1 + 1) % 1;
      const r2 = ((Math.sin(t * 39.425) * 54321.123) % 1 + 1) % 1;
      const glance = r1 > 0.55;
      a.lookTX = glance ? (r2 - 0.5) * 1.4 : 0;
      a.lookTY = glance ? (r1 - 0.75) * 0.8 : 0;
      a.lookAt = t + (glance ? 0.9 : 2.8) + r2 * 2;
    }
    let tx = a.lookTX;
    let ty = a.lookTY;
    if (c.dragging) {
      tx = Math.max(-1, Math.min(1, -a.yaw * 1.6));
      ty = 0;
    }
    if (pose.concerned) {
      tx = -0.35;
      ty = 0.8;
    }
    a.lookX += (tx - a.lookX) * Math.min(1, d * 9);
    a.lookY += (ty - a.lookY) * Math.min(1, d * 9);

    // Redraw the screen at ~30 fps.
    if (a.frame % 2 === 0) {
      const p: FaceParams = {
        expression: modeExpression(pose, excited),
        blink,
        lookX: a.lookX,
        lookY: a.lookY,
        mouth: a.mouth,
        time: t,
      };
      paintScreen(screen, p);
    }
  });

  const deg = Math.PI / 180;

  return (
    <group ref={root}>
      <group scale={0.01}>
        {/* Contact shadow */}
        <mesh ref={shadow} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.3, 0]}>
          <planeGeometry args={[290, 150]} />
          <meshBasicMaterial map={shadowTex} transparent depthWrite={false} />
        </mesh>

        <Wheel side={-1} mats={mats} spin={wheelL} />
        <Wheel side={1} mats={mats} spin={wheelR} />

        {/* Everything above the axle leans around it */}
        <group position={[0, AXLE, 0]}>
          <group ref={body}>
            <group position={[0, -43, 0]}>
              {/* Motors and axle housings */}
              {[-1, 1].map((s) => (
                <group key={s}>
                  <Block size={[38, 42, 42]} radius={4} position={[s * 31, 43, 0]} material={mats.ink} outline={false} />
                  <Block size={[8, 42, 42]} radius={3} position={[s * 52, 43, 0]} material={mats.silver} outline={false} />
                  <Block size={[22, 54, 48]} radius={4} position={[s * 45, 46, 0]} material={mats.blue} />
                </group>
              ))}

              {/* Lower deck */}
              <Block size={[118, 9, 132]} radius={4} position={[0, 74, 0]} material={mats.cream} />
              {/* Battery (front), with its label and plug */}
              <Block size={[104, 25, 34]} radius={4} position={[0, 91, 38]} material={mats.ink} />
              <Block size={[24, 25.6, 34.6]} radius={2} position={[0, 91, 38]} material={mats.label} outline={false} />
              <Block size={[14, 8, 14]} radius={2} position={[50, 82, 14]} material={mats.yellow} />
              {/* Wago blocks with orange levers (right, back) */}
              {[0, 1].map((i) => (
                <group key={i} position={[31, 82, -24 - i * 21]}>
                  <Block size={[30, 9, 17]} radius={2} material={mats.grey} outline={false} />
                  <Block size={[28, 2.5, 6]} radius={1} position={[0, 5, 4]} material={mats.orange} outline={false} />
                </group>
              ))}
              {/* Buck converter: blue board, red display (left, back) */}
              <group position={[-21, 99, -44]}>
                <Block size={[66, 36, 3]} radius={1.5} material={mats.heatsink} />
                <Block size={[22, 13, 2]} radius={1} position={[0, -2, -2.4]} material={mats.display} outline={false} />
              </group>

              {/* Kickstand, hinged under the front of the deck */}
              <group position={[0, 70, 56]}>
                <group ref={kickstand}>
                  <Block size={[20, 58, 10]} radius={4} position={[0, -28, 2]} material={mats.blue} />
                  <Block size={[30, 6, 16]} radius={3} position={[0, -56, 4]} material={mats.blueDeep} />
                </group>
              </group>

              {/* Mast, with the CAD's diamond holes and the sticker's little house window */}
              <Block size={[46, MAST_TOP - 72, 32]} radius={6} position={[0, (MAST_TOP + 72) / 2, 0]} material={mats.cream} />
              {[0, 1, 2, 3, 4].map((i) => (
                <mesh key={i} position={[12, 178 + i * 16, 16.2]} rotation={[0, 0, Math.PI / 4]} material={mats.ink}>
                  <boxGeometry args={[4.4, 4.4, 0.8]} />
                </mesh>
              ))}
              <mesh position={[-8, MAST_TOP - 26, 16.2]} material={mats.ink}>
                <shapeGeometry
                  args={[
                    new THREE.Shape([
                      new THREE.Vector2(-5, -6),
                      new THREE.Vector2(5, -6),
                      new THREE.Vector2(5, 2),
                      new THREE.Vector2(0, 7),
                      new THREE.Vector2(-5, 2),
                    ]),
                  ]}
                />
              </mesh>

              {/* Electronics shelf */}
              <Block size={[178, 6, 124]} radius={4} position={[0, 149, 0]} material={mats.cream} />
              <Block size={[62, 7, 104]} radius={3} position={[-57, 155.5, 0]} material={mats.blue} />
              <Block size={[60, 7, 50]} radius={3} position={[57, 155.5, 30]} material={mats.blue} />
              <Block size={[60, 7, 50]} radius={3} position={[57, 155.5, -30]} material={mats.blue} />
              {/* ESP32 terminal board, with its glowing LED */}
              <Block size={[58, 2, 80]} radius={1} position={[-57, 160, 0]} material={mats.pcb} outline={false} />
              <Block size={[7, 8, 66]} radius={1.5} position={[-82, 165, 0]} material={mats.green} outline={false} />
              <Block size={[7, 8, 66]} radius={1.5} position={[-32, 165, 0]} material={mats.green} outline={false} />
              <Block size={[25, 2, 62]} radius={1} position={[-57, 167, 0]} material={mats.ink} outline={false} />
              <Block size={[16, 3, 18]} radius={1} position={[-57, 169.5, -14]} material={mats.silver} outline={false} />
              <mesh ref={led} position={[-50, 169.5, 16]} material={mats.led}>
                <sphereGeometry args={[2, 12, 12]} />
              </mesh>
              {/* Two driver boards: red sockets, purple chips, blue heatsinks */}
              {[30, -30].map((z) => (
                <group key={z} position={[57, 160, z]}>
                  <Block size={[43, 2, 46]} radius={1} material={mats.pcb} outline={false} />
                  <Block size={[15, 8, 20]} radius={1} position={[0, 5, 0]} material={mats.red} outline={false} />
                  <Block size={[15, 2, 20]} radius={0.5} position={[0, 10, 0]} material={mats.purple} outline={false} />
                  <Block size={[9, 9, 9]} radius={1} position={[0, 15.5, 0]} material={mats.heatsink} outline={false} />
                </group>
              ))}

              {/* The tray, on the front of the mast */}
              <group position={[0, 206, 0]}>
                <Block size={[24, 16, 30]} radius={3} position={[0, -6, 26]} material={mats.blue} />
                <mesh position={[0, 0, 48]} material={mats.cream}>
                  <cylinderGeometry args={[44, 41, 6, 56]} />
                  <Outlines thickness={1.6} screenspace color={INK} />
                </mesh>
                <mesh position={[0, 3.5, 48]} rotation={[Math.PI / 2, 0, 0]} material={mats.blue}>
                  <torusGeometry args={[42.5, 3, 12, 56]} />
                </mesh>
                <group ref={glass} position={[0, 3, 52]}>
                  <mesh position={[0, 12, 0]} material={mats.water}>
                    <cylinderGeometry args={[8.2, 7.4, 16, 24]} />
                  </mesh>
                  <mesh position={[0, 13, 0]} material={mats.glass}>
                    <cylinderGeometry args={[9.6, 8.6, 26, 24, 1, true]} />
                    <Outlines thickness={1.2} screenspace color={INK} />
                  </mesh>
                </group>
              </group>

              {/* Wires: wrapped round the mast, hanging from the head, a loop by the board */}
              <group ref={wires}>
                <Wire points={helices.red} material={mats.wire.red} />
                <Wire points={helices.blue} material={mats.wire.blue} />
                <Wire points={helices.orange} material={mats.wire.orange} />
                <Wire points={helices.leftBlack} material={mats.wire.black} radius={1.4} />
                <Wire points={helices.rightBlack} material={mats.wire.black} radius={1.4} />
                <Wire points={helices.greenLoop} material={mats.wire.green} radius={1.4} />
              </group>

              {/* Head: phone mount, cradle and phone. Pivots at the top of the mast. */}
              <group position={[0, MAST_TOP, 0]}>
                <group ref={head} scale={HEAD_SCALE}>
                  <group position={[0, -316, 0]}>
                    {/* Pale-blue mount with screws */}
                    <Block size={[58, 5, 46]} radius={2} position={[0, 316, -4]} material={mats.blue} />
                    <Block size={[48, 22, 38]} radius={4} position={[0, 329, -4]} material={mats.blue} />
                    {[-1, 1].map((sx) =>
                      [-1, 1].map((sz) => (
                        <mesh key={`${sx}${sz}`} position={[sx * 22, 319, -4 + sz * 17]} material={mats.silver}>
                          <cylinderGeometry args={[2.2, 2.2, 2, 12]} />
                        </mesh>
                      )),
                    )}

                    {/* Cream cradle: base, side arms, back plate, dark strap */}
                    <Block size={[94, 20, 26]} radius={6} position={[0, 344, 0]} material={mats.cream} />
                    {[-1, 1].map((s) => (
                      <Block key={s} size={[11, 50, 21]} radius={5.4} position={[s * 42.5, 366, 0]} material={mats.cream} />
                    ))}
                    <Block size={[90, 56, 6]} radius={5} position={[0, 368, -9]} material={mats.creamShade} />
                    <Block size={[97, 7, 29]} radius={2.5} position={[0, 362, -0.5]} material={mats.ink} outline={false} />
                    {/* The back plate's round opening onto the phone's MagSafe ring */}
                    <mesh position={[0, 374, -12.3]} rotation={[Math.PI / 2, 0, 0]} material={mats.ink}>
                      <cylinderGeometry args={[17, 17, 0.6, 40]} />
                    </mesh>
                    <mesh position={[0, 374, -12.6]} rotation={[Math.PI / 2, 0, 0]} material={mats.goldBack}>
                      <cylinderGeometry args={[14, 14, 0.6, 40]} />
                    </mesh>

                    {/* The phone: gold frame, champagne back with two lenses, the face on the screen */}
                    <group position={[0, 420, 0]} rotation={[-2 * deg, 0, 0]}>
                      <Block size={[74, 156, 9]} radius={4.4} material={mats.gold} />
                      <Block size={[70, 152, 1]} radius={0.5} position={[0, 0, -4.4]} material={mats.goldBack} outline={false} />
                      <group position={[17, 56, -5.2]}>
                        <Block size={[28, 30, 2.4]} radius={1.2} material={mats.goldBack} />
                        {[7, -7].map((y) => (
                          <group key={y} position={[3, y, -1.2]}>
                            <mesh rotation={[Math.PI / 2, 0, 0]} material={mats.gold}>
                              <cylinderGeometry args={[6.4, 6.4, 1.6, 28]} />
                            </mesh>
                            <mesh position={[0, 0, -0.6]} rotation={[Math.PI / 2, 0, 0]} material={mats.lens}>
                              <cylinderGeometry args={[5, 5, 1.2, 28]} />
                            </mesh>
                          </group>
                        ))}
                        <mesh position={[-8, 0, -1.3]} rotation={[Math.PI / 2, 0, 0]} material={mats.silver}>
                          <cylinderGeometry args={[2, 2, 0.8, 16]} />
                        </mesh>
                      </group>
                      {/* Screen: black glass with the live face */}
                      <Block size={[69, 150, 0.6]} radius={0.3} position={[0, 0, 4.4]} material={mats.bezel} outline={false} />
                      <mesh geometry={screen.geo} material={screen.material} position={[0, 0, 4.8]} />
                    </group>
                  </group>
                </group>
              </group>
            </group>
          </group>
        </group>

        {/* Night-light: the screen lights the floor in front of him */}
        <pointLight ref={nightLight} position={[0, 380, 120]} color="#ffbf66" intensity={0} distance={900} decay={0} />
      </group>
    </group>
  );
}
