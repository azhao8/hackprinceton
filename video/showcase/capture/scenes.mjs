// The four showcase scenes as scripts of real taps and swipes on the family app.
//
// Times are seconds from the start of the scene. Every scene is captured twice from the same
// script: the LEFT phone (the action) and the RIGHT phone (the outcome). The `handoff` tap is the
// action whose result the right phone shows; on the left phone that one tap is pressed but not let
// through, so the left phone stays on the screen where it happened.
//
// `preroll` runs before the scene, with the clock running but nothing captured, so later scenes
// carry the earlier ones' history: the water from scene 2 and the check-in from scene 3 are in
// Mom's day by scene 4, at the times they happened.

const at = (sel, text) => ({ sel, text });

/** Off camera: send water with the note, wait for it to arrive, go back Home. */
async function sendWater(p) {
  await p.click(at("a[href='/family/send']"));
  await p.until(() => location.pathname === "/family/send");
  await p.click(at("button", "Water"));
  await p.click(at("button", "Love you, Mom"));
  await p.click(at("button", "Send with Miguel"));
  await p.wait(6000);
  await p.click(at("a", "Back to Mom"));
  await p.until(() => location.pathname === "/family");
}

/** Off camera: ask Mom to check in, talk for six minutes, end it. */
async function checkInSixMinutes(p) {
  await p.click(at("a[href='/family/check-in']"));
  await p.until(() => location.pathname === "/family/check-in");
  await p.click(at("button", "Ask Mom"));
  await p.wait(4000);
  await p.wait(6 * 60000);
  await p.click(at("button", "End check-in"));
  await p.wait(500);
}

export const SCENES = [
  {
    id: "day",
    eyebrow: "Know how they’re doing",
    title: "Stay close, even from far away.",
    labels: { left: ["Home", "How she is, at a glance"], right: ["Mom’s day", "What Miguel noticed"] },
    start: "/family",
    duration: 10.0,
    steps: [
      { t: 1.6, swipe: "bottom", dur: 0.85 },
      { t: 3.0, tap: at("a", "See all"), nav: "/family/day", handoff: true },
      { t: 4.4, swipe: 430, dur: 0.9 },
      { t: 5.6, swipe: "bottom", dur: 0.85 },
    ],
  },
  {
    id: "send",
    eyebrow: "Send something through Miguel",
    title: "A little help, whenever it’s needed.",
    labels: { left: ["Request", "Water, with a note"], right: ["On its way", "Miguel brings it to her"] },
    rightLabelAfter: { t: 4.3, label: "Delivered" }, // seconds after the handoff
    start: "/family",
    duration: 12.0,
    steps: [
      { t: 1.0, tap: at("a[href='/family/send']"), nav: "/family/send" },
      { t: 2.1, tap: at("button", "Water") },
      { t: 2.7, swipe: { sel: "textarea", top: 238 }, dur: 0.7 },
      { t: 3.7, tap: at("button", "Love you, Mom") },
      { t: 4.5, tap: at("button", "Send with Miguel"), handoff: true },
    ],
  },
  {
    id: "checkin",
    eyebrow: "Check in through Miguel",
    title: "Be there, without being there.",
    labels: { left: ["Check in", "Miguel asks her first"], right: ["Asking Mom", "Face to face, through Miguel"] },
    rightLabelAfter: { t: 2.9, label: "Connected" },
    start: "/family",
    preroll: async (p) => {
      await sendWater(p);
      await p.waitUntilClock(8 * 60 + 25); // 4:20:25 pm (the app's clock ticks every 20 s)
    },
    duration: 11.2,
    steps: [
      { t: 0.9, tap: at("a[href='/family/check-in']"), nav: "/family/check-in" },
      { t: 3.1, tap: at("button", "Ask Mom"), handoff: true },
    ],
  },
  {
    id: "summary",
    eyebrow: "Understand the bigger picture",
    title: "The little things add up.",
    labels: { left: ["Mom’s day", "Today, so far"], right: ["Summary", "Miguel’s read, and the facts"] },
    start: "/family",
    preroll: async (p) => {
      await sendWater(p);
      await p.waitUntilClock(8 * 60 + 25); // 4:20:25 pm
      await checkInSixMinutes(p);
      await p.click(at("a[href='/family']"));
      await p.until(() => location.pathname === "/family");
      await p.click(at("a[href='/family/day']"));
      await p.until(() => location.pathname === "/family/day");
      await p.waitUntilClock(14 * 60 + 40); // 4:26 pm, and the page's entrance is long done
    },
    duration: 12.6,
    steps: [
      { t: 1.8, tap: at("a[href='/family/day/summary']"), nav: "/family/day/summary", handoff: true },
      { t: 4.9, swipe: { sel: "h2", text: "Movement", top: 92 }, dur: 0.9 },
      { t: 6.4, swipe: { sel: "h2", text: "From the family", top: 92 }, dur: 0.9 },
    ],
  },
];
