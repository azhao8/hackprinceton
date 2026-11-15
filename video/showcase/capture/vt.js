// Virtual time for frame-exact capture. Injected before any page script runs.
//
// The page's clocks (Date, performance.now), timers and requestAnimationFrame only move when the
// capture script calls __vt.advance(ms), and every CSS animation and transition is paused and
// seeked to the virtual clock. So a 60 fps capture is exact no matter how long each screenshot
// takes, and loading (fonts, routes, the 3D model) costs no screen time.
(() => {
  const RealDate = Date;
  const EPOCH = RealDate.now();
  let now = 0; // virtual ms since the page loaded

  function VDate(...args) {
    if (!(this instanceof VDate)) return new RealDate(EPOCH + now).toString();
    return args.length ? new RealDate(...args) : new RealDate(EPOCH + now);
  }
  VDate.prototype = RealDate.prototype;
  VDate.now = () => EPOCH + now;
  VDate.parse = RealDate.parse;
  VDate.UTC = RealDate.UTC;
  window.Date = VDate;
  Object.defineProperty(Performance.prototype, "now", { value: () => now, configurable: true });

  let seq = 1;
  const timers = new Map();
  let rafs = new Map();
  window.setTimeout = (fn, ms = 0, ...args) => {
    const id = seq++;
    timers.set(id, { at: now + Math.max(0, Number(ms) || 0), fn, args, every: 0 });
    return id;
  };
  window.setInterval = (fn, ms = 0, ...args) => {
    const id = seq++;
    const every = Math.max(1, Number(ms) || 0);
    timers.set(id, { at: now + every, fn, args, every });
    return id;
  };
  window.clearTimeout = window.clearInterval = (id) => void timers.delete(id);
  window.requestAnimationFrame = (cb) => {
    const id = seq++;
    rafs.set(id, cb);
    return id;
  };
  window.cancelAnimationFrame = (id) => void rafs.delete(id);

  const run = (fn, args) => {
    try {
      if (typeof fn === "function") fn(...args);
    } catch (e) {
      console.error(e);
    }
  };

  function runDue(limit) {
    for (let guard = 0; guard < 100000; guard++) {
      let nextId = 0;
      let next = null;
      for (const [id, t] of timers) {
        if (t.at <= limit && (!next || t.at < next.at || (t.at === next.at && id < nextId))) {
          next = t;
          nextId = id;
        }
      }
      if (!next) return;
      now = Math.max(now, next.at);
      if (next.every) next.at += next.every;
      else timers.delete(nextId);
      run(next.fn, next.args);
    }
  }

  function syncAnimations() {
    for (const a of document.getAnimations()) {
      if (a.__vt === undefined) a.__vt = now;
      if (a.playState !== "paused") a.pause();
      a.currentTime = now - a.__vt;
    }
  }

  window.__vt = {
    now: () => now,
    /** Move the clock forward: due timers fire in order, then one animation frame at the new time. */
    advance(ms) {
      const target = now + ms;
      runDue(target);
      now = target;
      const list = [...rafs.values()];
      rafs = new Map();
      for (const cb of list) run(cb, [now]);
      syncAnimations();
    },
    /** Run zero-delay timers and pin new animations, without moving the clock. */
    flush() {
      runDue(now);
      syncAnimations();
    },
  };
})();
