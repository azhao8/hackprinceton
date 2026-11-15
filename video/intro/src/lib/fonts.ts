import opentype from "opentype.js";
import { useEffect, useState } from "react";
import { cancelRender, continueRender, delayRender, staticFile } from "remotion";

export type OtFont = opentype.Font;

const cache = new Map<string, Promise<OtFont>>();
export const loadOtFont = (file: string): Promise<OtFont> => {
  let p = cache.get(file);
  if (!p) {
    p = fetch(staticFile(`fonts/${file}`))
      .then((r) => r.arrayBuffer())
      .then((b) => opentype.parse(b) as OtFont);
    cache.set(file, p);
  }
  return p;
};

export const FONTS = {
  word: "outfit-latin-800-normal.woff",
  hero: "outfit-latin-600-normal.woff",
  heroLight: "outfit-latin-300-normal.woff",
  body: "inter-tight-latin-500-normal.woff",
  small: "inter-tight-latin-400-normal.woff",
} as const;
export type FontKey = keyof typeof FONTS;
export type FontSet = Record<FontKey, OtFont>;

/** Loads every font the film uses once; holds the render until they are parsed. */
export const useFontSet = (): FontSet | null => {
  const [fonts, setFonts] = useState<FontSet | null>(null);
  const [handle] = useState(() => delayRender("Loading fonts"));
  useEffect(() => {
    const keys = Object.keys(FONTS) as FontKey[];
    Promise.all(keys.map((k) => loadOtFont(FONTS[k])))
      .then((loaded) => {
        setFonts(Object.fromEntries(keys.map((k, i) => [k, loaded[i]])) as FontSet);
        continueRender(handle);
      })
      .catch((e) => cancelRender(e));
  }, [handle]);
  return fonts;
};

export type GlyphRun = {
  glyphs: { ch: string; x: number; width: number; d: string; bbox: { x1: number; y1: number; x2: number; y2: number } }[];
  width: number;
};

/** Lays out a string as positioned glyph paths (baseline at y = 0), with kerning and tracking (px). */
export const layout = (font: OtFont, text: string, size: number, tracking = 0): GlyphRun => {
  const scale = size / font.unitsPerEm;
  // map characters directly (opentype.js's GSUB shaping chokes on some of these fonts' contextual lookups)
  const glyphs = Array.from(text).map((ch) => font.charToGlyph(ch));
  let x = 0;
  const out: GlyphRun["glyphs"] = [];
  glyphs.forEach((g, i) => {
    const path = g.getPath(x, 0, size);
    const bb = path.getBoundingBox();
    out.push({ ch: text[i], x, width: g.advanceWidth! * scale, d: path.toPathData(3), bbox: bb });
    x += g.advanceWidth! * scale + tracking;
    if (i < glyphs.length - 1) x += font.getKerningValue(g, glyphs[i + 1]) * scale;
  });
  return { glyphs: out, width: x - tracking };
};
