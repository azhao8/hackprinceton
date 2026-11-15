// Shared capture plumbing: the family app's production server, a phone-sized Chrome page with
// virtual time, and helpers to tap, scroll and wait the way a person would.
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const HERE = dirname(fileURLToPath(import.meta.url));
export const WEB_DIR = join(HERE, "../../../web");
export const CHROME = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export const PORT = Number(process.env.SHOWCASE_PORT ?? 3107);
export const ORIGIN = `http://localhost:${PORT}`;

// iPhone 15 Pro / 16: 393 × 852 points; status bar 59 pt, home indicator 34 pt.
// Added to the Home Screen, the app opens full screen with the default (opaque) status bar, so
// the page itself is the 793 pt below it; the video draws the status bar above the capture.
export const PHONE = { width: 393, height: 852, statusBar: 59, safeBottom: 34 };
export const VIEW = { width: PHONE.width, height: PHONE.height - PHONE.statusBar };
export const DPR = Number(process.env.SHOWCASE_DPR ?? 2);
export const FPS = 60;
export const FRAME_MS = 1000 / FPS;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** `next start` on the built app (run `npm run build` in web/ first). */
export async function startServer() {
  try {
    const r = await fetch(`${ORIGIN}/family`);
    if (r.ok) return { stop: () => {} };
  } catch {}
  const proc = spawn("npx", ["next", "start", "-p", String(PORT)], { cwd: WEB_DIR, stdio: ["ignore", "pipe", "pipe"] });
  proc.stderr.on("data", (d) => process.stderr.write(d));
  for (let i = 0; i < 100; i++) {
    await sleep(200);
    try {
      const r = await fetch(`${ORIGIN}/family`);
      if (r.ok) return { stop: () => proc.kill() };
    } catch {}
  }
  proc.kill();
  throw new Error("next start did not come up");
}

export async function launch() {
  return puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--hide-scrollbars", "--force-color-profile=srgb", "--font-render-hinting=none", "--use-angle=metal"],
  });
}

/** A phone-sized page with virtual time, the status bar's safe areas, and the demo source. */
export async function openPhone(browser, path = "/family") {
  const page = await browser.newPage();
  await page.setViewport({ width: VIEW.width, height: VIEW.height, deviceScaleFactor: DPR, isMobile: true, hasTouch: false });
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "no-preference" }, { name: "prefers-color-scheme", value: "light" }]);
  await page.evaluateOnNewDocument(readFileSync(join(HERE, "vt.js"), "utf8"));
  // The home indicator is drawn by the video over the bottom of the page; the app keeps clear of
  // it as on an iPhone (it reads env(safe-area-inset-bottom) through --safe-bottom).
  await page.evaluateOnNewDocument(`
    addEventListener("DOMContentLoaded", () => {
      const s = document.createElement("style");
      s.textContent = ".family-root{--safe-top:0px !important;--safe-bottom:${PHONE.safeBottom}px !important}" +
        "*{caret-color:transparent}";
      document.head.appendChild(s);
    });
  `);
  page.on("pageerror", (e) => console.error("[page error]", e.message));
  page.on("console", (m) => m.type() === "error" && console.error("[console]", m.text()));
  // The app is built with NEXT_PUBLIC_FAMILY_SOURCE=demo (tools/build-app.sh), so no ?demo (which opens the demo panel).
  await page.goto(`${ORIGIN}${path}`, { waitUntil: "networkidle0" });
  await page.evaluate(() => document.fonts.ready);
  return page;
}

/** Let React and the router finish what the last clock step started, without moving the clock. */
export async function settle(page, rounds = 3) {
  for (let i = 0; i < rounds; i++) {
    await page.evaluate(
      () =>
        new Promise((r) => {
          const ch = new MessageChannel();
          ch.port1.onmessage = () => r();
          ch.port2.postMessage(0);
        }),
    );
    await page.evaluate(() => window.__vt.flush());
  }
}

/** Wait (in real time, the clock stopped) until a condition holds in the page. */
export async function until(page, fn, arg, timeout = 10000) {
  const t0 = Date.now();
  for (;;) {
    await settle(page, 1);
    if (await page.evaluate(fn, arg)) return;
    if (Date.now() - t0 > timeout) throw new Error(`timed out waiting for ${fn}`);
    await sleep(25);
  }
}

export async function advance(page, ms) {
  await page.evaluate((m) => window.__vt.advance(m), ms);
  await settle(page);
}

/** Center of the first element matching `selector` whose text includes `text` (CSS px in the viewport). */
export async function locate(page, selector, text) {
  const box = await page.evaluate(
    (sel, txt) => {
      const els = [...document.querySelectorAll(sel)].filter((e) => !txt || e.textContent.includes(txt));
      const el = els.find((e) => e.getBoundingClientRect().height > 0);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height };
    },
    selector,
    text ?? null,
  );
  if (!box) throw new Error(`no element ${selector} ${text ?? ""}`);
  return box;
}

/**
 * Miguel's 3D stage mounts in real time; wait until every visible one has a sized canvas and has
 * drawn, so he's there from the page's first frame (as in an app that has loaded him before).
 */
export async function stagesReady(page) {
  await until(
    page,
    () =>
      [...document.querySelectorAll(".stage-floor")]
        .filter((f) => f.getBoundingClientRect().width > 0)
        .every((f) => {
          const c = f.parentElement.querySelector("canvas");
          return c && c.width > 0 && c.height > 0;
        }),
    null,
    15000,
  );
  for (let i = 0; i < 4; i++) {
    await page.evaluate(() => window.__vt.advance(0));
    await sleep(40);
  }
  await settle(page);
}
