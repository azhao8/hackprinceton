// Miguel's performance in 3D. Position and heading always agree: he drives along the direction he faces (or
// reverses), turns in place to change direction, and his two wheels turn at the speeds a differential-drive robot
// needs for that. On top: the balancing pitch (leads acceleration, overshoots, settles), cable sway, head acting,
// face acting, and the I's topple. Precomputed once, sampled per frame — deterministic.
import T from "../timeline.json";
import {
  bezier, clamp, easeInCubic, easeInOutCubic, easeInOutSine, easeOutCubic, easeOutQuint, fbm, Key, lerp, ramp, ring, track,
} from "../lib/anim";
import { FaceState, NEUTRAL_FACE } from "../miguel/face";
import { TRACK, WHEEL_R } from "../three/miguel3d";
import { CAP, MIGUEL_PX } from "./layout";

const SIM_HZ = 960;
const OUT_HZ = 240;
const D2R = Math.PI / 180;

export type Pose3D = {
  x: number; z: number; yaw: number; pitch: number; headTilt: number; headNod: number;
  wheelL: number; wheelR: number; face: FaceState; cable: { swayX: number; swayZ: number };
};
export type IState = { roll: number; pitch: number; back: number; drop: number; dx: number };
export type Choreo3D = {
  pose: (t: number) => Pose3D;
  letterI: (t: number) => IState;
  impactT: number;
  landT: number;
  /** Mean wheel speed (rad/s) and screen x, for the motor sounds. */
  motorAt: (t: number) => { w: number; x: number };
};

const heading = (dx: number, dz: number) => Math.atan2(dx, dz); // 0 = facing the camera (+z)
const facing = (yaw: number) => ({ fx: Math.sin(yaw), fz: Math.cos(yaw) });

const blinkAt = (t: number, times: number[]) => {
  let b = 0;
  for (const t0 of times) {
    const u = t - t0;
    if (u < 0 || u > 0.2) continue;
    b = Math.max(b, u < 0.07 ? u / 0.07 : u < 0.1 ? 1 : 1 - (u - 0.1) / 0.1);
  }
  return b;
};
const speechMouth = (t: number, start: number, dur: number, env?: number[], envHz = 60) => {
  const u = t - start;
  if (u < 0 || u > dur + 0.05) return 0;
  if (env && env.length) return clamp((env[Math.min(Math.floor(u * envHz), env.length - 1)] ?? 0) * 1.45);
  const syll = 0.5 + 0.5 * Math.sin(u * 2 * Math.PI * 4.3 - 1.2);
  return clamp(0.12 + 0.7 * syll * Math.sin(clamp(u / dur) * Math.PI) ** 0.4);
};

export const buildChoreo3D = (slotX: number, voiceEnv: Record<string, number[]> = {}): Choreo3D => {
  // --- the path -----------------------------------------------------------------------------------
  const P0 = { x: 2420, z: 360 }; // off screen right
  const P1 = { x: 1290, z: 540 }; // where he talks, in front of the word
  const yawIn = heading(P1.x - P0.x, P1.z - P0.z); // ≈ −81°: he drives in facing screen-left
  const toI = heading(slotX - P1.x, 0 - P1.z); // facing the I (≈ −128°, mostly showing his back)
  const f = facing(toI);
  const PW = { x: P1.x - f.fx * 36, z: P1.z - f.fz * 36 }; // wind-up: backs off a little
  const PC = { x: slotX + 20 - f.fx * 62, z: 0 - f.fz * 62 }; // contact: his front meets the I's front corner
  const PP = { x: PC.x + f.fx * 10, z: PC.z + f.fz * 10 }; // follow-through
  const PR = { x: PC.x - f.fx * 12, z: PC.z - f.fz * 12 }; // recoil
  const PS = { x: slotX, z: -2 }; // the slot
  const yawSlot = heading(PS.x - PR.x, PS.z - PR.z);
  const yawFinal = -11 * D2R;

  const xKeys: Key[] = [
    [0, P0.x], [T.enterStart, P0.x], [T.enterStop, P1.x, bezier(0.2, 0.55, 0.3, 1)],
    [T.windup, P1.x], [T.windup + 0.28, PW.x, easeInOutSine],
    [T.charge, PW.x], [T.impact, PC.x, bezier(0.5, 0, 0.85, 0.7)], [T.impact + 0.09, PP.x, easeOutCubic],
    [T.impact + 0.38, PR.x, easeInOutSine],
    [T.slotStart, PR.x], [T.slotStart + 0.42, PS.x, bezier(0.4, 0, 0.3, 1)],
  ];
  const zKeys: Key[] = [
    [0, P0.z], [T.enterStart, P0.z], [T.enterStop, P1.z, bezier(0.2, 0.55, 0.3, 1)],
    [T.windup, P1.z], [T.windup + 0.28, PW.z, easeInOutSine],
    [T.charge, PW.z], [T.impact, PC.z, bezier(0.5, 0, 0.85, 0.7)], [T.impact + 0.09, PP.z, easeOutCubic],
    [T.impact + 0.38, PR.z, easeInOutSine],
    [T.slotStart, PR.z], [T.slotStart + 0.42, PS.z, bezier(0.4, 0, 0.3, 1)],
  ];
  // heading when standing still (while driving, the heading is the direction of travel)
  const yawKeys: Key[] = [
    [0, yawIn], [T.enterStop - 0.1, yawIn],
    [T.enterStop + 0.42, -10 * D2R, bezier(0.35, 0, 0.25, 1)],
    [T.notice, -10 * D2R], [T.notice + 0.32, -46 * D2R, easeOutCubic],
    [T.glanceAudience, -46 * D2R], [T.glanceAudience + 0.16, -20 * D2R, easeOutCubic],
    [T.glanceBack, -20 * D2R], [T.glanceBack + 0.14, -50 * D2R, easeOutCubic],
    [T.line2 + 0.85, -50 * D2R], [T.line2 + 1.15, -16 * D2R, easeInOutCubic],
    [T.turnToI, -16 * D2R], [T.turnToI + 0.36, toI, bezier(0.45, 0, 0.2, 1)],
    [T.slotStart, toI], [T.slotStart + 0.2, yawSlot, easeInOutSine],
    [T.slotTurn, yawSlot], [T.slotTurn + 0.42, yawFinal + 6 * D2R, bezier(0.4, 0, 0.25, 1)], [T.slotTurn + 0.62, yawFinal, easeInOutSine],
  ];
  const reversing = (t: number) => (t > T.windup && t < T.windup + 0.3) || (t > T.impact + 0.1 && t < T.impact + 0.4);

  // acting on top of the physics
  const pitchActKeys: Key[] = [
    [0, 0], [T.realize, 0], [T.realize + 0.08, -4, easeOutQuint], [T.realize + 0.4, 0, easeInOutSine],
    [T.lookUp, 0], [T.lookUp + 0.3, -3.5, easeInOutCubic], [T.lookBack, -3.5], [T.lookBack + 0.3, 0, easeInOutCubic],
  ];
  const headTiltKeys: Key[] = [
    [0, 0], [T.line1, 0], [T.line1 + 0.15, 3, easeOutCubic], [T.line1 + 0.55, -1.5, easeInOutSine], [T.line1 + 0.9, 0.5, easeInOutSine],
    [T.notice, 0.5], [T.notice + 0.3, 4.5, easeOutCubic], [T.glanceAudience, 0.5, easeInOutCubic], [T.glanceBack + 0.1, 4, easeInOutCubic],
    [T.line2 + 0.75, -2, easeInOutCubic], [T.line2 + 1.3, 1.5, easeInOutCubic], [T.turnToI, 0, easeInOutCubic],
    [T.line3, 0], [T.line3 + 0.12, 3.5, easeOutCubic], [T.line3 + 0.6, 0.8, easeInOutSine],
    [T.lookUp, 0.8], [T.lookUp + 0.25, 3, easeInOutCubic], [T.grandma + 0.9, -3, easeInOutSine], [T.phone + 0.1, 3.2, easeInOutCubic],
    [T.lookBack, 3.2], [T.lookBack + 0.3, 0, easeInOutCubic], [T.blink + 0.4, 1.8, easeInOutSine],
    // the closing hold: a slow, contented sway so the last shot never freezes
    [T.fadeOut - 0.3, 0.6, easeInOutSine], [T.fadeOut + 0.3, 1.5, easeInOutSine],
  ];
  const headNodKeys: Key[] = [
    [0, 0], [T.line1 + 0.05, 0], [T.line1 + 0.2, 3, easeOutCubic], [T.line1 + 0.45, 0, easeInOutSine],
    [T.realize, 0], [T.realize + 0.08, -5, easeOutQuint], [T.realize + 0.45, 0, easeInOutSine],
    [T.lookUp, 0], [T.lookUp + 0.25, -7, easeInOutCubic], [T.lookBack, -7], [T.lookBack + 0.3, 0, easeInOutCubic],
  ];

  // --- simulate --------------------------------------------------------------------------------
  const end = T.duration + 0.5;
  const nOut = Math.ceil(end * OUT_HZ) + 2;
  const out = {
    x: new Float32Array(nOut), z: new Float32Array(nOut), yaw: new Float32Array(nOut), pitch: new Float32Array(nOut),
    wl: new Float32Array(nOut), wr: new Float32Array(nOut), sx: new Float32Array(nOut), sz: new Float32Array(nOut),
    ws: new Float32Array(nOut),
  };
  const R = WHEEL_R * MIGUEL_PX; // wheel radius in px
  const halfTrack = (TRACK / 2) * MIGUEL_PX;
  const dt = 1 / SIM_HZ;
  const pos = (t: number) => ({ x: track(t, xKeys), z: track(t, zKeys) });
  const wn = 2 * Math.PI * 2.0, zeta = 0.33; // balance: ~2 Hz, a little underdamped
  const accelLean = 0.0095; // degrees per px/s² of forward acceleration
  let pitch = 0, pv = 0, prevPv = 0;
  let sx = 0, svx = 0, sz = 0, svz = 0;
  let yaw = yawIn, prevYaw = yawIn, prevYawRate = 0;
  let wl = 0, wr = 0;
  let prev = pos(0);
  let prevVf = 0;
  const e = 1 / 120;
  for (let i = 0, k = 0; k < nOut; i++) {
    const t = i * dt;
    const p = pos(t);
    const vx = (p.x - prev.x) / dt, vz = (p.z - prev.z) / dt;
    const speed = Math.hypot(vx, vz);
    // heading: the direction of travel while moving, otherwise the commanded heading
    const cmd = track(t, yawKeys);
    let travel = cmd;
    if (speed > 1) {
      travel = heading(vx, vz) + (reversing(t) ? Math.PI : 0);
      // unwrap toward the commanded heading
      while (travel - cmd > Math.PI) travel -= 2 * Math.PI;
      while (travel - cmd < -Math.PI) travel += 2 * Math.PI;
    }
    const wTravel = clamp((speed - 20) / 80);
    yaw = lerp(cmd, travel, wTravel);
    const yawRate = (yaw - prevYaw) / dt;
    prevYaw = yaw;
    // forward speed along the heading and the wheel speeds of a differential drive
    const { fx, fz } = facing(yaw);
    const vf = vx * fx + vz * fz;
    const vL = vf - yawRate * halfTrack;
    const vR = vf + yawRate * halfTrack;
    wl += (vL / R) * dt;
    wr += (vR / R) * dt;
    // balancing pitch leads the forward acceleration a little, then a damped spring
    const ta = t + 0.05;
    const pa = pos(ta - e), pb = pos(ta), pc = pos(ta + e);
    const ax = (pc.x - 2 * pb.x + pa.x) / (e * e), az = (pc.z - 2 * pb.z + pa.z) / (e * e);
    const af = ax * fx + az * fz;
    let target = clamp(af * accelLean, -14, 14) + track(t, pitchActKeys) + 0.5 * fbm(t * 0.9, 11);
    const pAcc = -wn * wn * (pitch - target) - 2 * zeta * wn * pv;
    pv += pAcc * dt;
    pitch += pv * dt;
    const pitchAcc = (pv - prevPv) / dt;
    prevPv = pv;
    const yawAcc = (yawRate - prevYawRate) / dt;
    prevYawRate = yawRate;
    // cables: front/back sway from the pitch, sideways from turning (springs)
    const wc = 2 * Math.PI * 3.2, zc = 0.2;
    svz += (-wc * wc * sz - 2 * zc * wc * svz - 0.000035 * pitchAcc) * dt;
    sz += svz * dt;
    svx += (-wc * wc * sx - 2 * zc * wc * svx + 0.0006 * yawAcc) * dt;
    sx += svx * dt;
    prev = p;
    prevVf = vf;
    if (i % (SIM_HZ / OUT_HZ) === 0) {
      out.x[k] = p.x;
      out.z[k] = p.z;
      out.yaw[k] = yaw;
      out.pitch[k] = (pitch + ring(t, T.impact, -7, 2.4, 3.6)) * D2R; // the bump knocks him back
      out.wl[k] = wl;
      out.wr[k] = wr;
      out.sx[k] = clamp(sx + ring(t, T.impact, 0.012, 3.0, 3.4), -0.03, 0.03);
      out.sz[k] = clamp(sz + ring(t, T.impact, -0.018, 3.0, 3.4), -0.04, 0.04);
      out.ws[k] = (Math.abs(vL) + Math.abs(vR)) / 2 / R;
      k++;
    }
  }
  void prevVf;
  const sample = (arr: Float32Array, t: number) => {
    const u = clamp(t, 0, end) * OUT_HZ;
    const i = Math.floor(u), fr = u - i;
    return lerp(arr[i] ?? 0, arr[i + 1] ?? arr[i] ?? 0, fr);
  };

  // --- face -------------------------------------------------------------------------------------
  const face = (t: number): FaceState => {
    const lookX = track(t, [
      [0, -0.6], [T.enterStop + 0.1, -0.6], [T.enterStop + 0.3, 0, easeInOutCubic],
      [T.notice, 0], [T.notice + 0.14, -1, easeOutQuint], [T.glanceAudience, -1], [T.glanceAudience + 0.1, 0.2, easeOutQuint],
      [T.glanceBack, 0.2], [T.glanceBack + 0.1, -1, easeOutQuint], [T.line2 + 0.85, -1], [T.line2 + 1.0, 0.1, easeOutQuint],
      [T.turnToI, 0], [T.turnToI + 0.1, -0.7, easeOutQuint], [T.impact + 0.3, -0.7], [T.impact + 0.45, -0.2, easeInOutCubic],
      [T.slotTurn + 0.3, 0, easeInOutCubic],
      [T.lookUp, 0], [T.lookUp + 0.15, 0.65, easeOutQuint], [T.grandma + 0.15, 0.6], [T.grandma + 0.95, -0.75, easeInOutSine],
      [T.phone + 0.02, -0.4], [T.phone + 0.16, 0.85, easeOutQuint], [T.lookBack, 0.85], [T.lookBack + 0.14, 0, easeOutQuint],
    ]);
    const lookY = track(t, [
      [0, 0], [T.notice, 0], [T.notice + 0.14, 0.15, easeOutQuint], [T.line2 + 1.0, 0, easeOutQuint],
      [T.lookUp, 0], [T.lookUp + 0.15, -1, easeOutQuint], [T.lookBack, -1], [T.lookBack + 0.14, 0, easeOutQuint],
    ]);
    const blink = Math.max(
      blinkAt(t, [T.enterStop + 0.5, T.line1 + 1.15, T.glanceBack - 0.06, T.slotTurn + 0.7, T.line3 + 0.95, T.blink, T.idleBlink]),
      ramp(t, T.impact - 0.01, T.impact + 0.04) * (1 - ramp(t, T.impact + 0.16, T.impact + 0.28)),
    );
    const eyeOpen = track(t, [
      [0, 1], [T.notice, 1], [T.notice + 0.12, 1.14, easeOutCubic], [T.realize, 1.14], [T.realize + 0.08, 1.38, easeOutQuint],
      [T.line2 + 0.55, 1.08, easeInOutCubic], [T.turnToI, 1.05], [T.turnToI + 0.15, 0.68, easeOutCubic], [T.impact, 0.68],
      [T.impact + 0.3, 1, easeInOutCubic],
    ]);
    const happy = track(t, [[0, 0], [T.line3 - 0.02, 0], [T.line3 + 0.12, 1, easeOutCubic], [T.line3 + 0.7, 1], [T.line3 + 0.9, 0, easeInOutCubic]]);
    const smile = track(t, [
      [0, 1], [T.notice, 1], [T.notice + 0.2, 0.55, easeInOutCubic], [T.turnToI, 0.55], [T.turnToI + 0.15, 0.15, easeOutCubic],
      [T.impact + 0.3, 0.15], [T.slotTurn + 0.4, 0.9, easeInOutCubic], [T.line3, 1.1], [T.line3 + 0.15, 1.55, easeOutCubic],
      [T.line3 + 0.9, 1.2, easeInOutCubic], [T.lookUp + 0.3, 1.0, easeInOutCubic], [T.heart, 1.0], [T.heart + 0.3, 1.35, easeInOutCubic],
      [T.blink + 0.1, 1.35], [T.blink + 0.45, 1.5, easeInOutCubic],
    ]);
    const V = T.voice;
    const mouthOpen = Math.max(
      speechMouth(t, T.line1, V.line1.dur, voiceEnv.line1),
      speechMouth(t, T.line2, V.line2.dur, voiceEnv.line2),
      speechMouth(t, T.line3, V.line3.dur, voiceEnv.line3) * 0.85,
    );
    const oh = track(t, [[0, 0], [T.line2 - 0.02, 0], [T.line2 + 0.05, 1, easeOutCubic], [T.line2 + 0.3, 1], [T.line2 + 0.4, 0, easeInOutCubic]]);
    return { ...NEUTRAL_FACE, lookX, lookY, blink, eyeOpen, happy, smile, mouthOpen, oh };
  };

  const pose = (t: number): Pose3D => ({
    x: sample(out.x, t),
    z: sample(out.z, t),
    yaw: sample(out.yaw, t),
    pitch: sample(out.pitch, t),
    headTilt: (track(t, headTiltKeys) + 0.3 * fbm(t * 0.7, 5)) * D2R,
    headNod: track(t, headNodKeys) * D2R,
    wheelL: sample(out.wl, t),
    wheelR: sample(out.wr, t),
    face: face(t),
    cable: { swayX: sample(out.sx, t) + 0.002 * fbm(t * 1.7, 9), swayZ: sample(out.sz, t) + 0.002 * fbm(t * 1.3, 3) },
  });

  // --- the I: knocked left and back, it teeters on its bottom-left edge, rolls, and drops off the ledge ------
  const g = 9.8 * (CAP / 0.38);
  const hM = 0.38, wM = 0.38 * (57 / CAP);
  const inertia = (wM * wM + hM * hM) / 3;
  const iN = Math.ceil(1.6 * SIM_HZ);
  const iRoll = new Float32Array(iN), iBack = new Float32Array(iN), iDrop = new Float32Array(iN);
  {
    let rho = 0, w = 2.45, drop = 0, vy = 0;
    for (let i = 0; i < iN; i++) {
      const u = i / SIM_HZ;
      const back = 118 * easeInOutCubic(clamp((u - 0.04) / 0.55));
      iRoll[i] = rho;
      iBack[i] = back;
      iDrop[i] = drop;
      const off = (wM / 2) * Math.cos(rho) - (hM / 2) * Math.sin(rho);
      w += ((-9.8 * off) / inertia) * dt;
      rho = Math.min(rho + w * dt, 1.75);
      if (back > 34) {
        vy += g * dt;
        drop += vy * dt;
      }
    }
  }
  const letterI = (t: number): IState => {
    const u = t - T.impact;
    if (u <= 0) return { roll: 0, pitch: 0, back: 0, drop: 0, dx: 0 };
    const i = Math.min(iN - 1, Math.floor(u * SIM_HZ));
    return { roll: iRoll[i], pitch: 9 * D2R * easeOutCubic(clamp(u / 0.3)), back: iBack[i], drop: iDrop[i], dx: -16 * easeOutCubic(clamp(u / 0.4)) };
  };
  let landT = T.impact + 1;
  for (let i = 0; i < iN; i++) if (iDrop[i] > 210) { landT = T.impact + i / SIM_HZ; break; }

  return {
    pose,
    letterI,
    impactT: T.impact,
    landT,
    motorAt: (t) => ({ w: sample(out.ws, t), x: sample(out.x, t) }),
  };
};
