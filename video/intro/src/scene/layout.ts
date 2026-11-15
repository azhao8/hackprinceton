// Wordmark geometry, centred on the frame. The second letter's slot is sized for Miguel (wheel to wheel, with
// breathing room) so he can take the I's place without crowding the M or the G, and no other letter ever moves.
import { CAM, CAP } from "../lib/camera";
import type { OtFont } from "../lib/fonts";
import { TRACK } from "../three/miguel3d";

export { CAP };
export const GAP = 70; // space between letters (ink to ink)
export const SLOT_PAD = 30; // space between Miguel's wheels and the neighbouring letters
export const DEPTH = 30; // letter thickness (world px)
/** Miguel's height in world px (on the letter plane he stands 1.32 × the cap height). */
export const MIGUEL_PX = Math.round(CAP * 1.32);
/** Wheel-to-wheel width when he faces the camera. */
export const MIGUEL_W = (TRACK + 0.09) * MIGUEL_PX;

export type PathCmd = { type: string; x?: number; y?: number; x1?: number; y1?: number; x2?: number; y2?: number };
export type Letter = { ch: string; path: PathCmd[]; x0: number; x1: number };
export type WordLayout = {
  fontSize: number;
  letters: Letter[]; // M, G, U, E, L
  I: Letter;
  slotX: number; // centre of the second letter's slot (world x)
  left: number;
  right: number;
};

export const computeWordLayout = (font: OtFont): WordLayout => {
  const fontSize = (CAP / font.tables.os2.sCapHeight) * font.unitsPerEm;
  const scale = fontSize / font.unitsPerEm;
  const ink = (ch: string) => {
    const g = font.charToGlyph(ch);
    const bb = g.getBoundingBox();
    return { g, x1: bb.x1 * scale, x2: bb.x2 * scale };
  };
  const chars = ["M", "G", "U", "E", "L"];
  const inks = chars.map(ink);
  const I = ink("I");
  const slotW = MIGUEL_W + 2 * SLOT_PAD;
  const widths = inks.map((k) => k.x2 - k.x1);
  const total = widths.reduce((a, b) => a + b, 0) + slotW + GAP * 3;
  const left = CAM.Xc - total / 2;
  let x = left;
  const letters: Letter[] = [];
  let slotX = 0;
  // glyph outlines in world units: x as laid out, y up from the baseline
  const outline = (g: typeof I.g, ox: number): PathCmd[] =>
    g.getPath(ox, 0, fontSize).commands.map((c) => {
      const o: PathCmd = { type: c.type };
      const cc = c as unknown as Record<string, number>;
      for (const k of ["x", "y", "x1", "y1", "x2", "y2"] as const) if (k in cc) o[k] = k.startsWith("y") ? -cc[k] : cc[k];
      return o;
    });
  chars.forEach((ch, i) => {
    const k = inks[i];
    const w = widths[i];
    letters.push({ ch, path: outline(k.g, x - k.x1), x0: x, x1: x + w });
    x += w;
    if (i === 0) {
      slotX = x + slotW / 2;
      x += slotW;
    } else if (i < chars.length - 1) x += GAP;
  });
  const iw = I.x2 - I.x1;
  const ix0 = slotX - iw / 2;
  return { fontSize, letters, I: { ch: "I", path: outline(I.g, ix0 - I.x1), x0: ix0, x1: ix0 + iw }, slotX, left, right: x };
};

/** Letter colours. */
export const LETTER = {
  faceTop: "#FBF7F0",
  faceBottom: "#E2D9CC",
  extrusion: "#6E665D",
  extrusionTop: "#9C9286",
  extrusionDark: "#3F3A35",
};
