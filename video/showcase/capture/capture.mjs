// Captures the showcase scenes from the real family app, frame by frame, for both phones.
//
//   node capture/capture.mjs [scene-id ...]     (all scenes when none are given)
//
// Needs the app built for filming first: tools/build-app.sh. Writes
//   public/capture/<scene>/<left|right>/000000.jpg …   (393 × 793 pt, below the status bar, at 2×)
//   public/capture/<scene>.json                         (timing, taps and swipes for the video)
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { FPS, FRAME_MS, VIEW, advance, launch, locate, openPhone, settle, stagesReady, startServer, until } from "./browser.mjs";
import { SCENES } from "./scenes.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "../public/capture");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** How long a finger stays down on a tap (s). */
const PRESS = 0.1;

// Demo clock: the page loads at 4:12 pm (seed AFTERNOON) and the clock is virtual.
const AFTERNOON = 16 * 60 + 12;
const clockAt = (vtMs) => {
  const m = AFTERNOON + Math.floor(vtMs / 60000);
  const h = Math.floor(m / 60) % 12 || 12;
  return `${h}:${String(m % 60).padStart(2, "0")}`;
};

/** A deceleration curve like a flicked list settling (fast start, long glide). */
const glide = (u) => {
  // cubic-bezier(0.25, 0.1, 0.2, 1), solved numerically
  const bx = (t) => 3 * (1 - t) ** 2 * t * 0.25 + 3 * (1 - t) * t ** 2 * 0.2 + t ** 3;
  const by = (t) => 3 * (1 - t) ** 2 * t * 0.1 + 3 * (1 - t) * t ** 2 * 1 + t ** 3;
  let lo = 0, hi = 1;
  for (let i = 0; i < 30; i++) {
    const mid = (lo + hi) / 2;
    if (bx(mid) < u) lo = mid;
    else hi = mid;
  }
  return by((lo + hi) / 2);
};

/** The off-camera helpers that preroll scripts use. */
function helpers(page) {
  const step = async (ms) => {
    // big jumps in a few steps so timers fire in order and React keeps up
    let left = ms;
    while (left > 0) {
      const d = Math.min(left, left > 2000 ? 1000 : FRAME_MS);
      await advance(page, d);
      left -= d;
    }
  };
  return {
    click: async ({ sel, text }) => {
      await page.evaluate(
        (s, t) => {
          const el = [...document.querySelectorAll(s)].find((e) => !t || e.textContent.includes(t));
          if (!el) throw new Error(`no ${s} ${t ?? ""}`);
          el.click();
        },
        sel,
        text ?? null,
      );
      await step(300);
    },
    wait: step,
    until: (fn) => until(page, fn),
    /** Run the clock until `seconds` after the page loaded (the page loads at 4:12 pm). */
    waitUntilClock: async (seconds) => {
      const now = await page.evaluate(() => window.__vt.now());
      if (seconds * 1000 > now) await step(seconds * 1000 - now);
    },
  };
}

async function scrollTargetY(page, target) {
  return page.evaluate((tg) => {
    const max = document.documentElement.scrollHeight - innerHeight;
    if (tg === "bottom") return max;
    if (typeof tg === "number") return Math.min(max, scrollY + tg);
    const el = [...document.querySelectorAll(tg.sel)].find((e) => !tg.text || e.textContent.includes(tg.text));
    if (!el) throw new Error(`no ${tg.sel}`);
    return Math.max(0, Math.min(max, scrollY + el.getBoundingClientRect().top - tg.top));
  }, target);
}

/**
 * One run of a scene. side "left": capture 0…duration, the handoff tap is pressed but blocked.
 * side "right": the handoff goes through; capture handoff…duration.
 */
async function runScene(browser, scene, side) {
  const page = await openPhone(browser, scene.start);
  const h = helpers(page);
  // let the first paint and the 3D model come in, without screen time
  await until(page, () => document.fonts.status === "loaded");
  if (scene.preroll) await scene.preroll(h);
  else await h.wait(40); // fresh page: its entrance plays on camera
  await stagesReady(page);
  await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : null));

  const handoff = scene.steps.find((s) => s.handoff);
  const H = handoff ? handoff.t + PRESS : 0;
  const t0vt = await page.evaluate(() => window.__vt.now());
  const dir = join(OUT, scene.id, side);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });

  const nFrames = Math.round(scene.duration * FPS);
  const touches = [];
  // The left phone stops at the handoff; what comes after it happens on the right phone.
  const pending = scene.steps.filter((s) => side === "right" || !handoff || s.t <= handoff.t).map((s) => ({ ...s, state: "todo" }));
  let shot = 0;

  for (let f = 0; f < nFrames; f++) {
    const t = f / FPS;
    for (const s of pending) {
      if (s.tap) {
        if (s.state === "todo" && t >= s.t) {
          const box = await locate(page, s.tap.sel, s.tap.text);
          s.box = box;
          if (side === "left" && s.handoff) {
            await page.evaluate(() =>
              window.addEventListener(
                "click",
                (e) => {
                  e.preventDefault();
                  e.stopImmediatePropagation();
                },
                { capture: true, once: true },
              ),
            );
          }
          await page.mouse.move(box.x, box.y);
          await page.mouse.down();
          s.state = "down";
          s.down = t;
        } else if (s.state === "down" && t >= s.t + PRESS) {
          await page.mouse.up();
          s.state = "done";
          touches.push({ kind: "tap", t0: s.down, t1: t, x: s.box.x, y: s.box.y });
          if (s.nav && !(side === "left" && s.handoff)) await until(page, (p) => location.pathname === p, s.nav);
          await settle(page);
          await stagesReady(page);
        }
      } else if (s.swipe !== undefined) {
        if (s.state === "todo" && t >= s.t) {
          s.y0 = await page.evaluate(() => scrollY);
          s.y1 = await scrollTargetY(page, s.swipe);
          s.state = "moving";
        }
        if (s.state === "moving") {
          const u = Math.min(1, (t - s.t) / s.dur);
          await page.evaluate((y) => window.scrollTo(0, y), s.y0 + (s.y1 - s.y0) * glide(u));
          if (u >= 1) {
            s.state = "done";
            touches.push({ kind: "swipe", t0: s.t, t1: s.t + s.dur, x: VIEW.width * 0.62, from: s.y0, to: s.y1 });
          }
        }
      }
    }
    // only the right phone's own part of the timeline is captured
    if (side === "left" || t >= H - 1e-6) {
      await page.screenshot({
        path: join(dir, `${String(shot).padStart(6, "0")}.jpg`),
        type: "jpeg",
        quality: 92,
        optimizeForSpeed: true,
      });
      shot += 1;
    }
    await advance(page, FRAME_MS);
  }
  const clock = clockAt(t0vt);
  await page.close();
  // each phone shows only its own touches
  const mine = touches.filter((x) => (side === "left" ? x.t0 <= H : x.t0 >= H - 0.01));
  return { frames: shot, start: side === "left" ? 0 : H, touches: mine, clock };
}

const only = process.argv.slice(2);
const server = await startServer();
const browser = await launch();
try {
  for (const scene of SCENES) {
    if (only.length && !only.includes(scene.id)) continue;
    const t = Date.now();
    const left = await runScene(browser, scene, "left");
    const right = await runScene(browser, scene, "right");
    const handoff = scene.steps.find((s) => s.handoff);
    const meta = {
      id: scene.id,
      eyebrow: scene.eyebrow,
      title: scene.title,
      labels: scene.labels,
      rightLabelAfter: scene.rightLabelAfter ?? null,
      duration: scene.duration,
      handoff: handoff ? handoff.t + PRESS : 0,
      phone: { width: 393, height: 852, statusBar: 59, safeBottom: 34 },
      view: VIEW,
      left,
      right,
    };
    writeFileSync(join(OUT, `${scene.id}.json`), JSON.stringify(meta, null, 2));
    console.log(`${scene.id}: left ${left.frames} frames, right ${right.frames} frames, ${((Date.now() - t) / 1000).toFixed(0)} s`);
    await sleep(50);
  }
} finally {
  await browser.close();
  server.stop();
}
