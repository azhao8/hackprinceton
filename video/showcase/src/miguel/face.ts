// Miguel's face, drawn into the 3D face panel's texture in the sticker's style (two small rounded eyes, a small smile).
// Copied from the intro (video/intro/src/miguel/face.ts); the showcase adds mouth shapes for speech (round, wide).

export type FaceState = {
  lookX: number; // -1 (his left on screen) .. 1
  lookY: number; // -1 up .. 1 down
  blink: number; // 0 open .. 1 closed
  eyeOpen: number; // 1 normal, >1 wide, <1 squint
  happy: number; // 0 .. 1 blend to ^ ^ eyes
  smile: number; // 0 flat .. 1 sticker smile .. 1.5 big
  mouthOpen: number; // 0 .. 1 (talking)
  oh: number; // 0 .. 1 small round "o" mouth
  /** While talking: 0 neutral .. 1 rounded lips (oo, oh, w). */
  round?: number;
  /** While talking: 0 neutral .. 1 spread lips (ee, ay). */
  wide?: number;
};

export const NEUTRAL_FACE: FaceState = { lookX: 0, lookY: 0, blink: 0, eyeOpen: 1, happy: 0, smile: 1, mouthOpen: 0, oh: 0 };

const INK = "#2b2526";

const roundRect = (ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) => {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
};

/** The eyes and mouth in panel-local units: the panel interior is about 94 × 44, centred on the origin. */
export const drawFaceFeatures = (ctx: CanvasRenderingContext2D, f: FaceState) => {
  ctx.save();
  const ex = f.lookX * 7, ey = f.lookY * 4.6;
  const eyeW = 12, baseH = 16.5;
  const h = Math.max(1.6, baseH * f.eyeOpen * (1 - f.blink));
  ctx.fillStyle = INK;
  ctx.strokeStyle = INK;
  for (const side of [-1, 1]) {
    const x = side * 23.5 + ex, y = -3.5 + ey;
    if (f.happy < 1) {
      ctx.globalAlpha = 1 - f.happy;
      const w = eyeW * (0.92 + 0.08 * f.eyeOpen);
      roundRect(ctx, x - w / 2, y - h / 2, w, h, 4);
      ctx.fill();
    }
    if (f.happy > 0) {
      ctx.globalAlpha = f.happy;
      ctx.lineWidth = 4.6;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x - 7, y + 3.2);
      ctx.quadraticCurveTo(x, y - 8, x + 7, y + 3.2);
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;

  // mouth
  const mx = ex * 0.4, my = 10.5 + ey * 0.35;
  const half = 14.5 + (f.smile - 1) * 3.5;
  const depth = 4 + 9.5 * f.smile;
  // the mouth is either a closed smile, an open talking mouth (sized by the voice), or a round "o"
  const talking = f.oh < 0.3 && f.mouthOpen > 0.07;
  if (f.oh >= 0.3) {
    const k = 0.55 + 0.45 * f.oh;
    ctx.beginPath();
    ctx.ellipse(mx, my + 1.5, 6.2 * k, 7.6 * k, 0, 0, Math.PI * 2);
    ctx.fill();
  } else if (talking) {
    // rounded lips pull the corners in and drop the jaw a little; spread lips widen and flatten
    const r = f.round ?? 0, w = f.wide ?? 0;
    const hw = (half - 1) * (1 - 0.42 * r + 0.14 * w);
    const open = (5 + 13 * Math.min(1, f.mouthOpen)) * (1 + 0.2 * r - 0.22 * w);
    const top = depth * 0.22 * (1 - 0.7 * r);
    const bottom = depth * 0.45 * (1 - 0.45 * r) + open * 1.5;
    ctx.beginPath();
    ctx.moveTo(mx - hw, my - 3);
    ctx.quadraticCurveTo(mx, my - 3 + top - r * open * 0.35, mx + hw, my - 3);
    ctx.quadraticCurveTo(mx, my - 3 + bottom, mx - hw, my - 3);
    ctx.closePath();
    ctx.fill();
    ctx.save();
    ctx.clip();
    ctx.fillStyle = "#c9706b";
    ctx.beginPath();
    ctx.ellipse(mx, my - 3 + bottom * 0.9, 7.5 * (1 - 0.3 * r), 3.5 + open * 0.35, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  } else {
    ctx.lineWidth = 5.2;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(mx - half, my - 2.5);
    ctx.quadraticCurveTo(mx, my - 2.5 + depth, mx + half, my - 2.5);
    ctx.stroke();
  }
  ctx.restore();
};
