import { advance, launch, openPhone, startServer, until, locate } from "./browser.mjs";
const server = await startServer();
const browser = await launch();
const shot = async (page, name) => page.screenshot({ path: `out/probe/${name}.png` });
const run = async (page, ms) => { for (let t = 0; t < ms; t += 1000 / 60) await advance(page, 1000 / 60); };
const tap = async (page, sel, text) => { const b = await locate(page, sel, text); await page.mouse.click(b.x, b.y); await run(page, 200); };
try {
  const page = await openPhone(browser, "/family");
  await run(page, 2500);
  await shot(page, "1-home");
  await page.evaluate(() => window.scrollTo(0, 9999)); await run(page, 100);
  await shot(page, "2-home-bottom");
  await tap(page, "a", "See all");
  await until(page, () => location.pathname === "/family/day");
  await run(page, 1200); await shot(page, "3-day");
  await tap(page, "a", "Miguel");
  await until(page, () => location.pathname === "/family/day/summary");
  await run(page, 1200); await shot(page, "4-summary");
  await page.evaluate(() => window.scrollTo(0, 560)); await run(page, 100); await shot(page, "5-summary-2");
  await page.evaluate(() => window.scrollTo(0, 1200)); await run(page, 100); await shot(page, "6-summary-3");
  const p2 = await openPhone(browser, "/family/send");
  await run(page, 600);
  await tap(p2, "button", "Water"); await run(p2, 600);
  await tap(p2, "button", "Love you"); await run(p2, 300);
  await p2.evaluate(() => window.scrollTo(0, 9999)); await run(p2, 100);
  await shot(p2, "7-send-form");
  await tap(p2, "button", "Send with Miguel");
  await run(p2, 1800); await shot(p2, "8-sent");
  await run(p2, 3500); await shot(p2, "9-delivered");
  const p3 = await openPhone(browser, "/family/check-in");
  await run(p3, 800);
  await tap(p3, "button", "Ask Mom"); await run(p3, 1500); await shot(p3, "10-asking");
  await run(p3, 3000); await shot(p3, "11-live");
} finally {
  await browser.close();
  server.stop();
}
