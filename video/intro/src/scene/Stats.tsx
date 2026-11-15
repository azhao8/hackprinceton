import { useMemo } from "react";
import T from "../timeline.json";
import { clamp, easeExit, easeInCubic, easeOutCubic, easeReveal, invLerp } from "../lib/anim";
import { FontKey, FontSet, layout } from "../lib/fonts";

export const AMBER = "#F3AE4B";
const INK = "#EEE8DF";
const MUTED = "#8E867C";

type Run = { text: string; font: FontKey; color: string };
type Stat = { hero: Run[]; sentence: string; source: string };

export const STATS: Stat[] = [
  {
    hero: [{ text: "1 in 4", font: "hero", color: AMBER }],
    sentence: "adults aged 65+ fall each year.",
    source: "U.S. adults 65+  ·  CDC, Older Adult Falls Data",
  },
  {
    hero: [{ text: "30%", font: "hero", color: AMBER }],
    sentence: "spent an hour or more on the floor after a fall.",
    source: "People over 90 who fell  ·  Fleming & Brayne, BMJ (2008)",
  },
  {
    hero: [
      { text: "Nearly ", font: "heroLight", color: INK },
      { text: "1 in 4", font: "hero", color: AMBER },
    ],
    sentence: "older adults are socially isolated.",
    source: "Community-dwelling U.S. adults 65+  ·  National Academies (2020)",
  },
];

const HERO = { size: 156, base: 505, travel: 176, clip: [330, 553] as const };
const SENT = { size: 46, base: 592, travel: 66, clip: [536, 610] as const };
const SRC = { size: 20, base: 664 };

type Glyph = { d: string; color: string; x: number };

const lineGlyphs = (fonts: FontSet, runs: Run[], size: number, tracking: number) => {
  const parts = runs.map((r) => ({ r, l: layout(fonts[r.font], r.text, size, tracking) }));
  const width = parts.reduce((a, p) => a + p.l.width, 0) + (parts.length - 1) * 0;
  let x = 960 - width / 2;
  const glyphs: Glyph[] = [];
  for (const p of parts) {
    for (const g of p.l.glyphs) if (g.d) glyphs.push({ d: g.d, color: p.r.color, x });
    x += p.l.width;
  }
  return glyphs;
};

/** Words, each as a group of glyph paths with its own stagger index. */
const sentenceWords = (fonts: FontSet, text: string, size: number) => {
  const l = layout(fonts.body, text, size, -0.2);
  const x0 = 960 - l.width / 2;
  const words: { d: string[]; x: number }[] = [];
  let cur: string[] = [];
  l.glyphs.forEach((g) => {
    if (g.ch === " ") {
      if (cur.length) words.push({ d: cur, x: x0 });
      cur = [];
    } else if (g.d) cur.push(g.d);
  });
  if (cur.length) words.push({ d: cur, x: x0 });
  return words;
};

const motion = (t: number, tin: number, tout: number, delay: number, outDelay: number, travel: number) => {
  const a = invLerp(tin + delay, tin + delay + 0.95, t);
  let y = (1 - easeReveal(a)) * travel;
  let o = clamp(a / 0.3);
  // the outgoing line lifts away and is nearly gone by the time the next one starts rising
  const b = invLerp(tout - 0.16 + outDelay, tout - 0.16 + outDelay + 0.34, t);
  y -= easeInCubic(b) * travel * 0.75;
  o *= 1 - easeOutCubic(clamp(b / 0.75));
  return { y, o };
};

/** Where the amber part of the hero line sits, for the soft light behind it. */
const amberSpan = (fonts: FontSet, runs: Run[]) => {
  const parts = runs.map((r) => ({ r, w: layout(fonts[r.font], r.text, HERO.size, -2).width }));
  const total = parts.reduce((a, p) => a + p.w, 0);
  let x = 960 - total / 2, amberX = 960, amberW = 0;
  for (const p of parts) {
    if (p.r.color === AMBER) { amberX = x + p.w / 2; amberW = p.w; }
    x += p.w;
  }
  return { amberX, amberW };
};
const heroLight = (t: number, tin: number, tout: number) =>
  clamp(invLerp(tin + 0.1, tin + 0.6, t)) * (1 - clamp(invLerp(tout - 0.2, tout + 0.08, t)));

export const Stats: React.FC<{ fonts: FontSet; t: number }> = ({ fonts, t }) => {
  const built = useMemo(
    () =>
      STATS.map((s) => ({
        hero: lineGlyphs(fonts, s.hero, HERO.size, -2),
        ...amberSpan(fonts, s.hero),
        words: sentenceWords(fonts, s.sentence, SENT.size),
        source: (() => {
          const l = layout(fonts.small, s.source, SRC.size, 0.5);
          return { d: l.glyphs.map((g) => g.d).join(" "), x: 960 - l.width / 2 };
        })(),
      })),
    [fonts],
  );
  if (t > T.darkStart + 0.2) return null;
  return (
    <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
      <defs>
        <clipPath id="heroClip">
          <rect x="0" y={HERO.clip[0]} width="1920" height={HERO.clip[1] - HERO.clip[0]} />
        </clipPath>
        <clipPath id="sentClip">
          <rect x="0" y={SENT.clip[0]} width="1920" height={SENT.clip[1] - SENT.clip[0]} />
        </clipPath>
        <radialGradient id="amberLight" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#F3AE4B" stopOpacity="0.16" />
          <stop offset="0.6" stopColor="#F3AE4B" stopOpacity="0.05" />
          <stop offset="1" stopColor="#F3AE4B" stopOpacity="0" />
        </radialGradient>
      </defs>
      {built.map((b, si) => {
        const { in: tin, out: tout } = T.stats[si];
        if (t < tin - 0.05 || t > tout + 0.9) return null;
        const srcIn = clamp(invLerp(tin + 0.45, tin + 0.95, t));
        const srcOut = clamp(invLerp(tout - 0.22, tout + 0.02, t));
        return (
          <g key={si}>
            <ellipse cx={b.amberX} cy={HERO.base - 52} rx={b.amberW * 0.62 + 60} ry={92} fill="url(#amberLight)" opacity={heroLight(t, tin, tout)} />
            <g>
            <g clipPath="url(#heroClip)">
              {b.hero.map((g, gi) => {
                const m = motion(t, tin, tout, gi * 0.03, gi * 0.012, HERO.travel);
                return (
                  <path key={gi} d={g.d} fill={g.color} opacity={m.o} transform={`translate(${g.x} ${HERO.base + m.y})`} />
                );
              })}
            </g>
            </g>
            <g clipPath="url(#sentClip)">
              {b.words.map((w, wi) => {
                const m = motion(t, tin, tout, 0.13 + wi * 0.04, 0.02 + wi * 0.01, SENT.travel);
                return (
                  <g key={wi} opacity={m.o} transform={`translate(${w.x} ${SENT.base + m.y})`}>
                    {w.d.map((d, k) => (
                      <path key={k} d={d} fill={INK} />
                    ))}
                  </g>
                );
              })}
            </g>
            <path
              d={b.source.d}
              fill={MUTED}
              opacity={srcIn * (1 - srcOut)}
              transform={`translate(${b.source.x} ${SRC.base + (1 - easeReveal(srcIn)) * 8 - easeExit(srcOut) * 6})`}
            />
          </g>
        );
      })}
    </svg>
  );
};
