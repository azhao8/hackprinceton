// Miguel's face, drawn on a 2D canvas. The 3D model uses it as the phone screen's
// texture; small 2D badges (alert, check-in) draw it directly.
//
// Coordinates are in "face units": u = width / 100, so the face scales with the screen.

import type { Expression } from "@/lib/family/types";

export interface FaceParams {
  expression: Expression;
  /** 0 = eyes open, 1 = closed. */
  blink: number;
  /** Where the eyes look, -1..1 on each axis (+y = down). */
  lookX: number;
  lookY: number;
  /** 0..1 while speaking, from the voice envelope. */
  mouth: number;
  /** Seconds, for small idle animations (z's, sparkles). */
  time: number;
  /** Draw the phone's camera pill at the top. */
  island?: boolean;
}

const INK = "#2a2630";
const CHEEK = "rgba(240, 150, 140, 0.42)";

const BACKGROUNDS: Record<Expression, [string, string]> = {
  happy: ["#fffaf0", "#f6ead6"],
  excited: ["#fffaf0", "#f8e8cc"],
  focused: ["#fffaf0", "#f6ead6"],
  sleepy: ["#f3eee6", "#e6dccd"],
  listening: ["#fbfbf6", "#e9eef5"],
  concerned: ["#fbf7f1", "#efe6da"],
  night: ["#ffe2a6", "#f6a752"],
  offline: ["#3a3740", "#2a272f"],
};

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

/** Draw the whole face into a w×h area at the canvas origin. */
export function drawFace(ctx: CanvasRenderingContext2D, w: number, h: number, p: FaceParams) {
  const u = w / 100;
  const cx = w / 2;
  const [bgTop, bgBottom] = BACKGROUNDS[p.expression];

  // Screen
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, bgTop);
  g.addColorStop(1, bgBottom);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  if (p.expression === "night") {
    // The night-light: a soft bloom behind the face.
    const r = ctx.createRadialGradient(cx, h * 0.42, 4 * u, cx, h * 0.42, 70 * u);
    r.addColorStop(0, "rgba(255, 246, 214, 0.95)");
    r.addColorStop(1, "rgba(255, 246, 214, 0)");
    ctx.fillStyle = r;
    ctx.fillRect(0, 0, w, h);
  }

  if (p.island !== false) {
    ctx.fillStyle = "#111";
    roundRect(ctx, cx - 15 * u, 4.2 * u, 30 * u, 8 * u, 4 * u);
    ctx.fill();
  }

  const eyeY = h * 0.4 + p.lookY * 2.4 * u;
  const eyeDX = 17 * u;
  const lx = p.lookX * 3.2 * u;
  const mouthY = h * 0.4 + 23 * u;

  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  // Features are drawn a little larger than the grid, around the face's center.
  const k = 1.26;
  const fcy = h * 0.45;
  ctx.save();
  ctx.translate(cx, fcy);
  ctx.scale(k, k);
  ctx.translate(-cx, -fcy);

  // Cheeks
  if (p.expression === "happy" || p.expression === "excited" || p.expression === "focused") {
    ctx.fillStyle = CHEEK;
    for (const s of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(cx + s * 29 * u + lx * 0.5, mouthY - 4 * u, 7.5 * u, 4.6 * u, 0, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  drawEyes(ctx, p, cx + lx, eyeY, eyeDX, u);
  drawBrows(ctx, p, cx + lx, eyeY, eyeDX, u);
  drawMouth(ctx, p, cx + lx * 0.6, mouthY, u);
  ctx.restore();
  drawExtras(ctx, p, w, h, u);
}

function drawEyes(ctx: CanvasRenderingContext2D, p: FaceParams, cx: number, y: number, dx: number, u: number) {
  const ink = p.expression === "offline" ? "rgba(235,230,220,0.55)" : INK;
  ctx.fillStyle = ink;
  ctx.strokeStyle = ink;

  for (const s of [-1, 1]) {
    const x = cx + s * dx;

    if (p.expression === "sleepy") {
      // Closed, content arcs.
      ctx.lineWidth = 3.4 * u;
      ctx.beginPath();
      ctx.arc(x, y - 1.5 * u, 6.5 * u, Math.PI * 0.15, Math.PI * 0.85);
      ctx.stroke();
      continue;
    }
    if (p.expression === "offline") {
      ctx.lineWidth = 3 * u;
      ctx.beginPath();
      ctx.moveTo(x - 5 * u, y);
      ctx.lineTo(x + 5 * u, y);
      ctx.stroke();
      continue;
    }

    let ew = 11 * u;
    let eh = 17 * u;
    if (p.expression === "excited") {
      ew = 12.5 * u;
      eh = 19 * u;
    } else if (p.expression === "listening") {
      ew = 12 * u;
      eh = 18.5 * u;
    } else if (p.expression === "concerned") {
      ew = 10 * u;
      eh = 14.5 * u;
    } else if (p.expression === "night") {
      eh = 13 * u;
    }

    const open = 1 - p.blink;
    const h = Math.max(2.6 * u, eh * open);
    roundRect(ctx, x - ew / 2, y - h / 2, ew, h, ew / 2);
    ctx.fill();

    // Sleepy lids at night: a flat top over the eye.
    if (p.expression === "night" && open > 0.5) {
      ctx.save();
      ctx.fillStyle = "#fbd690";
      ctx.fillRect(x - ew, y - h / 2 - 1, ew * 2, h * 0.38);
      ctx.restore();
    }

    // Highlights
    if (open > 0.45) {
      ctx.save();
      ctx.fillStyle = "rgba(255,250,240,0.95)";
      ctx.beginPath();
      ctx.arc(x - ew * 0.16, y - h * 0.2, ew * 0.2, 0, Math.PI * 2);
      ctx.fill();
      if (p.expression === "excited") {
        ctx.beginPath();
        ctx.arc(x + ew * 0.18, y + h * 0.14, ew * 0.1, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
  }
}

function drawBrows(ctx: CanvasRenderingContext2D, p: FaceParams, cx: number, y: number, dx: number, u: number) {
  if (p.expression !== "concerned" && p.expression !== "listening" && p.expression !== "focused") return;
  ctx.strokeStyle = INK;
  ctx.lineWidth = 2.6 * u;
  for (const s of [-1, 1]) {
    const x = cx + s * dx;
    const by = y - 14.5 * u;
    ctx.beginPath();
    if (p.expression === "concerned") {
      // Inner ends raised: worried.
      ctx.moveTo(x - s * 6 * u, by - 2.6 * u);
      ctx.quadraticCurveTo(x, by - 1.2 * u, x + s * 6 * u, by + 1.6 * u);
    } else if (p.expression === "focused") {
      ctx.moveTo(x - s * 6 * u, by + 0.8 * u);
      ctx.lineTo(x + s * 5.5 * u, by - 0.6 * u);
    } else {
      // Listening: raised, curious.
      ctx.arc(x, by + 1 * u, 6 * u, Math.PI * 1.18, Math.PI * 1.82);
    }
    ctx.stroke();
  }
}

function drawMouth(ctx: CanvasRenderingContext2D, p: FaceParams, cx: number, y: number, u: number) {
  ctx.strokeStyle = p.expression === "offline" ? "rgba(235,230,220,0.55)" : INK;
  ctx.fillStyle = INK;
  ctx.lineWidth = 3.2 * u;

  if (p.mouth > 0.04) {
    // Talking: an open mouth whose height follows the voice.
    const open = Math.min(1, p.mouth);
    const mw = (10 + 4 * open) * u;
    const mh = (2.5 + 9.5 * open) * u;
    ctx.beginPath();
    ctx.moveTo(cx - mw, y - 1 * u);
    ctx.quadraticCurveTo(cx, y + 1.2 * u, cx + mw, y - 1 * u);
    ctx.quadraticCurveTo(cx + mw * 0.75, y + mh, cx, y + mh + 0.6 * u);
    ctx.quadraticCurveTo(cx - mw * 0.75, y + mh, cx - mw, y - 1 * u);
    ctx.closePath();
    ctx.fill();
    if (open > 0.35) {
      ctx.save();
      ctx.clip();
      ctx.fillStyle = "#e5847a";
      ctx.beginPath();
      ctx.ellipse(cx, y + mh + 1 * u, mw * 0.55, mh * 0.42, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
    return;
  }

  ctx.beginPath();
  switch (p.expression) {
    case "excited": {
      const mw = 11 * u;
      ctx.moveTo(cx - mw, y - 1.5 * u);
      ctx.quadraticCurveTo(cx, y - 0.5 * u, cx + mw, y - 1.5 * u);
      ctx.quadraticCurveTo(cx + mw * 0.7, y + 11 * u, cx, y + 11 * u);
      ctx.quadraticCurveTo(cx - mw * 0.7, y + 11 * u, cx - mw, y - 1.5 * u);
      ctx.closePath();
      ctx.fill();
      ctx.save();
      ctx.clip();
      ctx.fillStyle = "#e5847a";
      ctx.beginPath();
      ctx.ellipse(cx, y + 11 * u, mw * 0.55, 4.5 * u, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      return;
    }
    case "listening":
      ctx.ellipse(cx, y + 2 * u, 3.2 * u, 3.8 * u, 0, 0, Math.PI * 2);
      ctx.stroke();
      return;
    case "concerned":
      ctx.moveTo(cx - 7 * u, y + 4 * u);
      ctx.quadraticCurveTo(cx, y + 0.2 * u, cx + 7 * u, y + 4 * u);
      ctx.stroke();
      return;
    case "sleepy":
    case "night":
      ctx.moveTo(cx - 6 * u, y + 1 * u);
      ctx.quadraticCurveTo(cx, y + 5 * u, cx + 6 * u, y + 1 * u);
      ctx.stroke();
      return;
    case "offline":
      ctx.moveTo(cx - 5 * u, y + 2 * u);
      ctx.lineTo(cx + 5 * u, y + 2 * u);
      ctx.stroke();
      return;
    default: {
      // happy, focused: the sticker's small smile.
      const mw = p.expression === "focused" ? 8 * u : 9.5 * u;
      ctx.moveTo(cx - mw, y);
      ctx.quadraticCurveTo(cx, y + 9 * u, cx + mw, y);
      ctx.stroke();
    }
  }
}

function drawExtras(ctx: CanvasRenderingContext2D, p: FaceParams, w: number, h: number, u: number) {
  if (p.expression === "sleepy") {
    // Floating z's and a small charging glyph.
    ctx.fillStyle = "rgba(42,38,48,0.55)";
    ctx.font = `600 ${9 * u}px ui-rounded, system-ui, sans-serif`;
    for (let i = 0; i < 2; i++) {
      const phase = (p.time * 0.35 + i * 0.5) % 1;
      ctx.globalAlpha = Math.sin(phase * Math.PI);
      ctx.fillText("z", w * 0.68 + phase * 8 * u + i * 6 * u, h * 0.3 - phase * 14 * u - i * 4 * u);
    }
    ctx.globalAlpha = 1;
    const bx = w / 2 - 7 * u;
    const by = h * 0.78;
    ctx.strokeStyle = "rgba(42,38,48,0.5)";
    ctx.lineWidth = 1.6 * u;
    roundRect(ctx, bx, by, 14 * u, 7 * u, 1.8 * u);
    ctx.stroke();
    ctx.fillStyle = "#5fa36f";
    const level = 0.35 + 0.6 * ((Math.sin(p.time * 1.2) + 1) / 2);
    roundRect(ctx, bx + 1.6 * u, by + 1.6 * u, (14 - 3.2) * u * level, 3.8 * u, 1 * u);
    ctx.fill();
  }
  if (p.expression === "listening") {
    // Little sound arcs beside the face.
    ctx.strokeStyle = "rgba(94,134,194,0.75)";
    ctx.lineWidth = 2.2 * u;
    for (let i = 0; i < 3; i++) {
      const a = (Math.sin(p.time * 4 - i * 0.9) + 1) / 2;
      ctx.globalAlpha = 0.25 + 0.75 * a;
      ctx.beginPath();
      ctx.arc(w * 0.5, h * 0.46, (36 + i * 6) * u, -0.45, 0.45);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
}
