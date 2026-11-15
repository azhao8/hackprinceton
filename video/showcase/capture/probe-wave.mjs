import { advance, launch, openPhone, startServer, locate } from "./browser.mjs";
const server = await startServer();
const browser = await launch();
const run = async (page, ms) => { for (let t = 0; t < ms; t += 1000 / 60) await advance(page, 1000 / 60); };
try {
  const p3 = await openPhone(browser, "/family/check-in");
  await run(p3, 800);
  const b = await locate(p3, "button", "Ask Mom"); await p3.mouse.click(b.x, b.y);
  await run(p3, 3200);
  for (const t of [300, 500, 400, 300, 300, 400, 1500]) { await run(p3, t); await p3.screenshot({ path: `out/probe/wave-${String(Math.round(await p3.evaluate(() => window.__vt.now()))).padStart(5, "0")}.png`, clip: { x: 20, y: 110, width: 353, height: 470 } }); }
} finally { await browser.close(); server.stop(); }
