// Miguel as a real 3D model, reconstructed from the sticker (assets/source/miguel-sticker.png).
// Units: the robot is 1.0 tall (floor to the top of the phone). +z is his front (the side with the face and the
// phone's camera), +x is to his left (screen-right when he faces the camera), y is up. The axle is at y = WHEEL_R.
//
// Rig (all independent): root (position, yaw) → wheels (each spins on its own) and body (pitches about the axle)
// → head (small extra tilt) → face texture (eyes, mouth). Cables are tubes rebuilt from springy control points.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { drawFaceFeatures, FaceState } from "./face";

export const WHEEL_R = 0.107;
export const TRACK = 0.505; // distance between the wheel centres
const TIRE_W = 0.09;
export const ROBOT_LAYER = 1;

export const COLORS = {
  white: "#F6ECE7",
  whiteWarm: "#F3E6DF",
  blue: "#B4C9EA",
  blueDeep: "#8FA8D2",
  ink: "#2A2526",
  black: "#2B2728",
  tire: "#36302F",
  tread: "#5B5352",
  hub: "#2C2829",
  spoke: "#7A7171",
  gold: "#E3B567",
  goldDeep: "#C9953F",
  glass: "#F2E3CF",
  lens: "#1E1B1C",
  pcb: "#2D2C33",
  green: "#4FA65A",
  red: "#E2483D",
  cableBlue: "#3C77C8",
  orange: "#F0A338",
  cableGreen: "#2F8E5A",
  led: "#FF4B3B",
  screen: "#141416",
};

// --- materials ---------------------------------------------------------------------------------
let gradient: THREE.DataTexture | null = null;
const toonGradient = () => {
  if (!gradient) {
    const data = new Uint8Array([178, 178, 178, 255, 222, 222, 222, 255, 255, 255, 255, 255]);
    gradient = new THREE.DataTexture(data, 3, 1, THREE.RGBAFormat);
    gradient.minFilter = THREE.NearestFilter;
    gradient.magFilter = THREE.NearestFilter;
    gradient.needsUpdate = true;
  }
  return gradient;
};
const matCache = new Map<string, THREE.Material>();
export const toon = (color: string, opts: { emissive?: string; emissiveIntensity?: number } = {}) => {
  const key = `${color}|${opts.emissive ?? ""}|${opts.emissiveIntensity ?? 0}`;
  let m = matCache.get(key);
  if (!m) {
    m = new THREE.MeshToonMaterial({
      color: new THREE.Color(color),
      gradientMap: toonGradient(),
      emissive: new THREE.Color(opts.emissive ?? "#000000"),
      emissiveIntensity: opts.emissiveIntensity ?? 0,
    });
    matCache.set(key, m);
  }
  return m;
};

// --- helpers -----------------------------------------------------------------------------------
const rbox = (w: number, h: number, d: number, r: number, color: string, seg = 3) => {
  const m = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, seg, Math.min(r, w / 2, h / 2, d / 2) * 0.999), toon(color));
  return m;
};
const at = <T extends THREE.Object3D>(o: T, x: number, y: number, z: number) => {
  o.position.set(x, y, z);
  return o;
};
const cyl = (r: number, h: number, color: string, seg = 32, axis: "x" | "y" | "z" = "y") => {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), toon(color));
  if (axis === "x") m.rotation.z = Math.PI / 2;
  if (axis === "z") m.rotation.x = Math.PI / 2;
  return m;
};
/** A flat rounded rectangle facing +z. */
const plate = (w: number, h: number, r: number, color: string | THREE.Material) => {
  const s = new THREE.Shape();
  const x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);
  s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);
  s.quadraticCurveTo(x, y, x + r, y);
  const g = new THREE.ShapeGeometry(s, 8);
  // planar UVs 0..1
  const pos = g.attributes.position;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    uv[i * 2] = (pos.getX(i) - x) / w;
    uv[i * 2 + 1] = (pos.getY(i) - y) / h;
  }
  g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  return new THREE.Mesh(g, typeof color === "string" ? toon(color) : color);
};
const tube = (pts: THREE.Vector3[], r: number, color: string) => {
  const curve = new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.5);
  return new THREE.Mesh(new THREE.TubeGeometry(curve, 48, r, 8, false), toon(color));
};

// --- the wheel ---------------------------------------------------------------------------------
const buildWheel = (side: 1 | -1) => {
  // side = +1 for the wheel on his left (+x). The outer face points toward ±x.
  const g = new THREE.Group();
  const spin = new THREE.Group(); // rotates about x
  g.add(spin);
  const tire = cyl(WHEEL_R - 0.006, TIRE_W, COLORS.tire, 48, "x");
  spin.add(tire);
  // tread: two staggered rows of chunky blocks around the tire (the sticker's zigzag)
  const N = 22;
  const blockGeo = new RoundedBoxGeometry(TIRE_W * 0.44, 0.012, 0.024, 2, 0.003);
  for (let i = 0; i < N; i++) {
    for (const row of [0, 1]) {
      const a = ((i + row * 0.5) / N) * Math.PI * 2;
      const b = new THREE.Mesh(blockGeo, toon(COLORS.tread));
      const r = WHEEL_R - 0.004;
      b.position.set((row ? 1 : -1) * TIRE_W * 0.24, Math.cos(a) * r, Math.sin(a) * r);
      b.rotation.x = -a;
      spin.add(b);
    }
  }
  // outer side: sidewall, recessed hub disk, six spokes, cap
  const outX = side * (TIRE_W / 2 + 0.001);
  const wall = cyl(WHEEL_R * 0.9, 0.004, "#3E3837", 48, "x");
  wall.position.x = outX;
  spin.add(wall);
  const disk = cyl(WHEEL_R * 0.66, 0.006, COLORS.hub, 40, "x");
  disk.position.x = outX + side * 0.002;
  spin.add(disk);
  for (let j = 0; j < 6; j++) {
    const a = (j / 6) * Math.PI * 2;
    const sp = rbox(0.008, WHEEL_R * 0.5, 0.012, 0.003, COLORS.spoke, 2);
    sp.position.set(outX + side * 0.006, Math.cos(a) * WHEEL_R * 0.36, Math.sin(a) * WHEEL_R * 0.36);
    sp.rotation.x = -a;
    spin.add(sp);
  }
  const cap = cyl(WHEEL_R * 0.13, 0.012, "#5A5252", 24, "x");
  cap.position.x = outX + side * 0.008;
  spin.add(cap);
  // inner side
  const inner = cyl(WHEEL_R * 0.8, 0.004, COLORS.hub, 40, "x");
  inner.position.x = -side * (TIRE_W / 2 + 0.001);
  spin.add(inner);
  return { group: g, spin };
};

// --- face texture ------------------------------------------------------------------------------
const makeFaceCanvas = () => {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 272;
  return c;
};
const paintFace = (c: HTMLCanvasElement, f: FaceState) => {
  const ctx = c.getContext("2d")!;
  const W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  // the panel: dark frame, soft inner shadow, warm white screen
  const rr = (x: number, y: number, w: number, h: number, r: number) => {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  };
  rr(0, 0, W, H, 54);
  ctx.fillStyle = "#3A3334";
  ctx.fill();
  rr(14, 14, W - 28, H - 28, 44);
  const g = ctx.createLinearGradient(0, 14, 0, H - 14);
  g.addColorStop(0, "#CFC4C2");
  g.addColorStop(0.22, "#FBF3EF");
  g.addColorStop(1, "#F5ECE8");
  ctx.fillStyle = g;
  ctx.fill();
  ctx.save();
  ctx.translate(W / 2, H / 2 + 4);
  ctx.scale(W / 112, W / 112);
  drawFaceFeatures(ctx, f);
  ctx.restore();
};

// --- window texture (the curved opening at the top of the holder, showing the phone's black mount) -------
const makeWindowTexture = () => {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 220;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#4A4344";
  ctx.fillRect(0, 0, 512, 220);
  ctx.fillStyle = "#2A2526";
  ctx.fillRect(18, 18, 476, 184);
  // the mount: a black disk whose lower half shows, ringed in cream
  ctx.save();
  ctx.beginPath();
  ctx.rect(18, 18, 476, 184);
  ctx.clip();
  ctx.fillStyle = "#EDE3D9";
  ctx.beginPath();
  ctx.arc(256, 40, 186, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#1F1B1C";
  ctx.beginPath();
  ctx.arc(256, 26, 166, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
};

export type CablePose = { swayX: number; swayZ: number };

export type Miguel3D = {
  root: THREE.Group;
  setPose: (p: {
    x: number; z: number; yaw: number; pitch: number; headTilt: number; headNod: number;
    wheelL: number; wheelR: number; face: FaceState; cable: CablePose;
  }) => void;
  /** World position of the top of his head, for placing his thoughts. */
  headTop: () => THREE.Vector3;
};

export const buildMiguel = (scale: number): Miguel3D => {
  const root = new THREE.Group();
  const model = new THREE.Group();
  model.scale.setScalar(scale);
  root.add(model);

  // wheels ---------------------------------------------------------------------------------------
  const wl = buildWheel(-1), wr = buildWheel(1);
  at(wl.group, -TRACK / 2, WHEEL_R, 0);
  at(wr.group, TRACK / 2, WHEEL_R, 0);
  model.add(wl.group, wr.group);

  // body: pitches about the axle --------------------------------------------------------------------
  const body = new THREE.Group();
  body.position.set(0, WHEEL_R, 0);
  model.add(body);
  const B = new THREE.Group(); // body content in robot coordinates (floor-based)
  B.position.set(0, -WHEEL_R, 0);
  body.add(B);

  // motors and axles
  for (const s of [-1, 1]) {
    B.add(at(rbox(0.078, 0.078, 0.078, 0.01, COLORS.black), s * 0.15, WHEEL_R, -0.005));
    B.add(at(cyl(0.009, 0.06, "#8A8484", 16, "x"), s * 0.215, WHEEL_R, 0));
  }
  // lower tray with the battery, and its side walls up to the deck
  B.add(at(rbox(0.32, 0.022, 0.22, 0.008, COLORS.white), 0, 0.062, 0.015));
  B.add(at(rbox(0.32, 0.03, 0.02, 0.006, COLORS.white), 0, 0.08, 0.12)); // front lip
  B.add(at(rbox(0.2, 0.05, 0.1, 0.008, COLORS.black), -0.02, 0.098, 0.05));
  B.add(at(rbox(0.2, 0.008, 0.004, 0.002, "#4B4545"), -0.02, 0.108, 0.101));
  for (const [x, z] of [[-0.145, 0.105], [0.145, 0.105], [-0.145, -0.075], [0.145, -0.075]] as const)
    B.add(at(cyl(0.008, 0.14, "#E9E2DC", 12), x, 0.135, z));
  // kickstand: a pale-blue T under the front
  B.add(at(rbox(0.03, 0.06, 0.022, 0.006, COLORS.blue), -0.03, 0.035, 0.09));
  B.add(at(rbox(0.075, 0.016, 0.03, 0.006, COLORS.blue), -0.03, 0.012, 0.09));

  // deck with pale-blue corner plates, screws and slots
  B.add(at(rbox(0.43, 0.03, 0.28, 0.01, COLORS.white), 0, 0.212, 0.0));
  for (const [x, z] of [[-0.135, 0.08], [0.135, 0.08], [-0.135, -0.08], [0.135, -0.08]] as const) {
    B.add(at(rbox(0.13, 0.007, 0.1, 0.008, COLORS.blue), x, 0.229, z));
    for (const [dx, dz] of [[-0.045, -0.032], [0.045, -0.032], [-0.045, 0.032], [0.045, 0.032]] as const) {
      B.add(at(cyl(0.007, 0.006, "#D9E3F3", 12), x + dx, 0.234, z + dz));
    }
  }
  for (let k = 0; k < 3; k++) B.add(at(rbox(0.055, 0.004, 0.009, 0.004, COLORS.ink), 0.135, 0.234, 0.06 + k * 0.018));
  B.add(at(rbox(0.07, 0.004, 0.008, 0.004, COLORS.ink), 0.0, 0.23, 0.12));
  B.add(at(cyl(0.006, 0.004, COLORS.ink, 12), 0.06, 0.23, 0.12));

  // electronics: an ESP32 board stack on his right (−x) and a driver board on his left (+x)
  const stack = new THREE.Group();
  at(stack, -0.135, 0.0, 0.065);
  B.add(stack);
  stack.add(at(rbox(0.17, 0.008, 0.1, 0.003, COLORS.pcb), 0, 0.245, 0));
  for (let i = 0; i < 6; i++) stack.add(at(rbox(0.024, 0.02, 0.022, 0.003, COLORS.green), -0.065 + i * 0.026, 0.259, 0.04));
  for (const [x, z] of [[-0.075, -0.04], [0.075, -0.04], [-0.075, 0.04], [0.075, 0.04]] as const)
    stack.add(at(cyl(0.004, 0.04, "#C9C2B8", 8), x, 0.27, z));
  stack.add(at(rbox(0.15, 0.008, 0.09, 0.003, COLORS.pcb), 0, 0.292, 0));
  for (let i = 0; i < 5; i++) stack.add(at(rbox(0.024, 0.018, 0.02, 0.003, COLORS.green), -0.055 + i * 0.026, 0.305, 0.034));
  stack.add(at(rbox(0.12, 0.01, 0.012, 0.002, "#1A1819"), 0, 0.3, -0.03));
  stack.add(at(rbox(0.04, 0.006, 0.03, 0.002, "#3B3A42"), 0.02, 0.3, 0.0));
  stack.add(at(new THREE.Mesh(new THREE.SphereGeometry(0.009, 12, 8), toon(COLORS.led, { emissive: COLORS.led, emissiveIntensity: 1.2 })), -0.03, 0.3, 0.012));
  stack.add(at(new THREE.Mesh(new THREE.SphereGeometry(0.006, 12, 8), toon("#FFB347", { emissive: "#FFB347", emissiveIntensity: 0.9 })), -0.012, 0.3, 0.02));
  stack.add(at(rbox(0.035, 0.024, 0.032, 0.004, "#EDE7DF"), -0.098, 0.27, 0.02)); // USB connector

  const drv = new THREE.Group();
  at(drv, 0.115, 0, 0.03);
  B.add(drv);
  drv.add(at(rbox(0.15, 0.008, 0.1, 0.003, COLORS.pcb), 0, 0.245, 0));
  for (let i = 0; i < 5; i++) drv.add(at(rbox(0.024, 0.018, 0.02, 0.003, COLORS.green), -0.05 + i * 0.026, 0.258, -0.035));
  drv.add(at(rbox(0.05, 0.01, 0.04, 0.003, "#3B3A42"), 0.02, 0.254, 0.015));
  drv.add(at(rbox(0.025, 0.025, 0.025, 0.004, "#EDE7DF"), 0.088, 0.26, 0.04)); // switch

  // the mast
  B.add(at(rbox(0.072, 0.29, 0.072, 0.012, COLORS.whiteWarm), 0, 0.37, 0));
  const house = new THREE.Shape();
  house.moveTo(-0.011, -0.012); house.lineTo(0.011, -0.012); house.lineTo(0.011, 0.004); house.lineTo(0, 0.014); house.lineTo(-0.011, 0.004); house.closePath();
  B.add(at(new THREE.Mesh(new THREE.ShapeGeometry(house), toon("#4A4060")), 0, 0.455, 0.0365));

  // neck: pale-blue plate with a hole, white clamp tabs, a black post
  B.add(at(rbox(0.18, 0.024, 0.13, 0.01, COLORS.blue), 0, 0.525, 0.005));
  B.add(at(rbox(0.07, 0.02, 0.07, 0.01, COLORS.blueDeep), 0, 0.508, 0.0));
  B.add(at(cyl(0.018, 0.026, "#3A3436", 20), 0, 0.527, 0.02));
  for (const s of [-1, 1]) B.add(at(rbox(0.04, 0.055, 0.06, 0.008, COLORS.white), s * 0.068, 0.56, 0.0));
  B.add(at(cyl(0.0085, 0.07, COLORS.black, 12), 0.028, 0.565, 0.045));

  // head: holder + phone, with the sticker's slight tilt ---------------------------------------------
  const neck = new THREE.Group(); // pivot for expressive head motion
  neck.position.set(0, 0.54, 0);
  B.add(neck);
  const head = new THREE.Group();
  head.position.set(0, -0.54, 0);
  head.rotation.z = (-4 * Math.PI) / 180;
  neck.add(head);

  const HOLD = { w: 0.3, h: 0.215, d: 0.135, y: 0.69 };
  head.add(at(rbox(HOLD.w, HOLD.h, HOLD.d, 0.03, COLORS.white, 4), 0, HOLD.y, 0));
  // rubber strap around it
  head.add(at(rbox(HOLD.w + 0.008, 0.02, HOLD.d + 0.008, 0.008, COLORS.ink), 0, 0.73, 0));
  // the curved opening at the top front, showing the phone's black mount
  const win = plate(0.15, 0.062, 0.012, new THREE.MeshBasicMaterial({ map: makeWindowTexture() }));
  at(win, 0, 0.765, HOLD.d / 2 + 0.0012);
  head.add(win);
  // face panel
  const faceCanvas = makeFaceCanvas();
  const faceTex = new THREE.CanvasTexture(faceCanvas);
  faceTex.colorSpace = THREE.SRGBColorSpace;
  faceTex.anisotropy = 4;
  const facePanel = plate(0.128, 0.068, 0.016, new THREE.MeshBasicMaterial({ map: faceTex, transparent: true }));
  at(facePanel, 0, 0.652, HOLD.d / 2 + 0.0012);
  head.add(facePanel);
  // bottom bracket tabs under the holder
  head.add(at(rbox(0.06, 0.03, 0.08, 0.008, COLORS.white), -0.09, 0.575, 0));
  head.add(at(rbox(0.06, 0.03, 0.08, 0.008, COLORS.white), 0.09, 0.575, 0));
  // back of the holder: a plain seam line (no screws — from behind they read as a second pair of eyes)
  head.add(at(rbox(HOLD.w - 0.05, 0.004, 0.003, 0.001, "#D8CCC7"), 0, 0.64, -HOLD.d / 2 - 0.0005));

  // the phone: back (cameras, mount) faces his front, the screen faces his back
  const phone = new THREE.Group();
  phone.position.set(0, 0.8, 0.026);
  head.add(phone);
  const PH = { w: 0.215, h: 0.4, d: 0.028 };
  phone.add(rbox(PH.w, PH.h, PH.d, 0.032, COLORS.gold, 4));
  const back = plate(PH.w - 0.014, PH.h - 0.014, 0.027, COLORS.glass);
  back.position.z = PH.d / 2 + 0.0008;
  phone.add(back);
  const screen = plate(PH.w - 0.014, PH.h - 0.014, 0.027, COLORS.screen);
  screen.position.z = -PH.d / 2 - 0.0008;
  screen.rotation.y = Math.PI;
  phone.add(screen);
  const island = plate(0.05, 0.014, 0.007, "#000000");
  island.position.set(0, PH.h / 2 - 0.03, -PH.d / 2 - 0.0016);
  island.rotation.y = Math.PI;
  phone.add(island);
  // camera bump (top-left when you look at the back) with two big lenses and a small flash
  const bump = new THREE.Group();
  bump.position.set(-0.048, 0.132, PH.d / 2 + 0.003);
  phone.add(bump);
  bump.add(rbox(0.1, 0.11, 0.008, 0.028, "#EBD3AE"));
  for (const ly of [0.025, -0.026]) {
    const ring = cyl(0.028, 0.009, COLORS.goldDeep, 32, "z");
    ring.position.set(-0.014, ly, 0.004);
    bump.add(ring);
    const lens = cyl(0.023, 0.011, COLORS.lens, 32, "z");
    lens.position.set(-0.014, ly, 0.006);
    bump.add(lens);
  }
  const flash = cyl(0.01, 0.007, "#FFF4DE", 16, "z");
  flash.position.set(0.03, 0, 0.004);
  bump.add(flash);
  // black magnetic mount on the back, ringed in cream (its top shows above the holder)
  const mount = cyl(0.074, 0.014, COLORS.lens, 40, "z");
  mount.position.set(0, -0.012, PH.d / 2 + 0.007);
  phone.add(mount);
  const mring = new THREE.Mesh(new THREE.TorusGeometry(0.08, 0.006, 8, 48), toon("#EFE5DA"));
  mring.position.set(0, -0.012, PH.d / 2 + 0.002);
  phone.add(mring);
  // side buttons on his left edge
  for (const [y, h] of [[0.09, 0.045], [0.03, 0.045], [0.15, 0.026]] as const) {
    phone.add(at(rbox(0.006, h, 0.01, 0.002, COLORS.goldDeep), PH.w / 2 + 0.002, y, 0));
  }

  // cables ---------------------------------------------------------------------------------------------
  const cableGroup = new THREE.Group();
  B.add(cableGroup);
  type CableDef = { pts: [number, number, number][]; r: number; color: string; sway: number[] };
  const V = (p: [number, number, number]) => new THREE.Vector3(...p);
  const helix = (color: string, phase: number, y0: number, y1: number, turns: number, extra: [number, number, number][]) => {
    const pts: [number, number, number][] = [];
    const n = 14;
    for (let i = 0; i <= n; i++) {
      const u = i / n;
      const a = phase + u * turns * Math.PI * 2;
      pts.push([Math.sin(a) * 0.058, y0 + (y1 - y0) * u, Math.cos(a) * 0.058]);
    }
    return { pts: [...pts, ...extra], r: 0.0068, color, sway: pts.map((_, i) => 0.15 * (i / n)).concat(extra.map(() => 0.6)) };
  };
  const cables: CableDef[] = [
    // black leads hanging from the neck down to the boards
    { pts: [[-0.05, 0.56, 0.05], [-0.062, 0.47, 0.062], [-0.07, 0.38, 0.066], [-0.075, 0.3, 0.07]], r: 0.0068, color: COLORS.black, sway: [0, 0.6, 1, 0.5] },
    { pts: [[-0.062, 0.555, 0.035], [-0.08, 0.46, 0.05], [-0.09, 0.37, 0.056], [-0.1, 0.3, 0.05]], r: 0.0068, color: COLORS.black, sway: [0, 0.7, 1, 0.5] },
    { pts: [[0.045, 0.56, 0.05], [0.06, 0.46, 0.064], [0.07, 0.37, 0.07], [0.08, 0.27, 0.066]], r: 0.0068, color: COLORS.black, sway: [0, 0.6, 1, 0.4] },
    { pts: [[0.058, 0.56, 0.04], [0.078, 0.46, 0.052], [0.09, 0.37, 0.056], [0.1, 0.27, 0.05]], r: 0.0068, color: COLORS.black, sway: [0, 0.7, 1, 0.4] },
    { pts: [[0.07, 0.555, 0.028], [0.095, 0.45, 0.036], [0.11, 0.36, 0.04], [0.12, 0.27, 0.03]], r: 0.0068, color: COLORS.black, sway: [0, 0.8, 1, 0.4] },
    { pts: [[-0.035, 0.55, 0.055], [-0.045, 0.4, 0.075], [-0.03, 0.26, 0.12], [0.0, 0.16, 0.13], [0.02, 0.11, 0.1]], r: 0.0068, color: COLORS.black, sway: [0, 0.6, 1, 0.8, 0.3] },
    // red and blue wrapped around the mast, then looping onto the driver board
    helix(COLORS.red, 0.4, 0.31, 0.43, 1.7, [[0.12, 0.36, 0.06], [0.19, 0.31, 0.07], [0.17, 0.27, 0.03]]),
    helix(COLORS.cableBlue, 2.0, 0.3, 0.42, 1.6, [[0.14, 0.34, 0.04], [0.2, 0.3, 0.04], [0.15, 0.26, 0.01]]),
    { pts: [[0.05, 0.27, 0.06], [0.13, 0.35, 0.09], [0.21, 0.3, 0.07], [0.17, 0.255, 0.05]], r: 0.0068, color: COLORS.orange, sway: [0, 0.8, 1, 0.4] },
    { pts: [[0.06, 0.27, 0.04], [0.15, 0.33, 0.1], [0.215, 0.285, 0.08], [0.16, 0.25, 0.06]], r: 0.0068, color: COLORS.cableBlue, sway: [0, 0.8, 1, 0.4] },
    { pts: [[-0.06, 0.25, 0.1], [-0.045, 0.3, 0.12], [-0.02, 0.27, 0.12], [-0.03, 0.24, 0.1]], r: 0.005, color: COLORS.cableGreen, sway: [0, 0.6, 0.6, 0] },
    // power: red pair from the battery round to the driver board, and a lead out to his left
    { pts: [[0.08, 0.1, 0.1], [0.14, 0.12, 0.12], [0.17, 0.17, 0.11], [0.15, 0.23, 0.08]], r: 0.006, color: COLORS.red, sway: [0, 0.3, 0.3, 0] },
    { pts: [[0.085, 0.09, 0.1], [0.15, 0.105, 0.115], [0.185, 0.16, 0.1], [0.165, 0.235, 0.07]], r: 0.006, color: COLORS.red, sway: [0, 0.3, 0.3, 0] },
    { pts: [[0.2, 0.235, -0.02], [0.25, 0.235, -0.06], [0.29, 0.215, -0.08]], r: 0.0055, color: COLORS.black, sway: [0, 0.5, 1] },
  ];
  const cableMeshes = cables.map((c) => {
    const m = tube(c.pts.map(V), c.r, c.color);
    cableGroup.add(m);
    return m;
  });
  const setCables = (cp: CablePose) => {
    cables.forEach((c, i) => {
      const pts = c.pts.map((p, k) => new THREE.Vector3(p[0] + cp.swayX * c.sway[k], p[1], p[2] + cp.swayZ * c.sway[k]));
      const old = cableMeshes[i].geometry;
      cableMeshes[i].geometry = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.5), 48, c.r, 8, false);
      old.dispose();
    });
  };

  // everything belongs to the robot layer (the outline pass draws ink lines only on him)
  root.traverse((o) => o.layers.set(ROBOT_LAYER));

  let lastCable = { swayX: 0, swayZ: 0 };
  return {
    root,
    setPose: (p) => {
      root.position.set(p.x, 0, p.z);
      root.rotation.y = p.yaw;
      wl.spin.rotation.x = p.wheelL;
      wr.spin.rotation.x = p.wheelR;
      body.rotation.x = p.pitch;
      neck.rotation.z = p.headTilt;
      neck.rotation.x = p.headNod;
      paintFace(faceCanvas, p.face);
      faceTex.needsUpdate = true;
      if (Math.abs(p.cable.swayX - lastCable.swayX) > 1e-4 || Math.abs(p.cable.swayZ - lastCable.swayZ) > 1e-4) {
        setCables(p.cable);
        lastCable = p.cable;
      }
    },
    headTop: () => {
      const v = new THREE.Vector3(0, 1.0, 0.02);
      phone.updateWorldMatrix(true, false);
      return phone.localToWorld(v.set(0, PH.h / 2, 0));
    },
  };
};
