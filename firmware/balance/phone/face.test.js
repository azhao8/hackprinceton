// Tests for face.js (pure parts + the wrapper with fakes). Run: node --test firmware/balance/phone/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Face = require('./face.js');

function seeded(seed) {                       // mulberry32
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// run for `secs` at 60 fps; onStep(state) after each step
function run(state, secs, inputs, rng, onStep) {
  const dt = 1 / 60, n = Math.round(secs / dt);
  for (let i = 0; i < n; i++) {
    state = Face.step(state, dt, i === 0 ? inputs : null, rng);
    if (onStep) onStep(state);
  }
  return state;
}

function fakeCtx() {
  const calls = [], props = {};
  const ctx = new Proxy({}, {
    get(_, k) { return k in props ? props[k] : (...args) => { calls.push([k, args]); }; },
    set(_, k, v) { props[k] = v; calls.push(['=' + String(k), [v]]); return true; }
  });
  return { ctx, calls };
}

test('blinks every 2-6 s, ~120 ms long, deterministic with a seeded rng', () => {
  function blinkStarts(seed) {
    const starts = [];
    let s = Face.initialState(), wasBlinking = false, longest = 0, closedFor = 0;
    run(s, 60, null, seeded(seed), (st) => {
      const blinking = st.blink.t >= 0;
      if (blinking && !wasBlinking) starts.push(st.t);
      if (blinking) closedFor += 1 / 60; else { longest = Math.max(longest, closedFor); closedFor = 0; }
      wasBlinking = blinking;
    });
    return { starts, longest };
  }
  const a = blinkStarts(42), b = blinkStarts(42), c = blinkStarts(7);
  assert.deepEqual(a.starts, b.starts);
  assert.notDeepEqual(a.starts, c.starts);
  assert.ok(a.starts.length >= 60 / 6 - 1 && a.starts.length <= 60 / 2 + 1, 'blink count ' + a.starts.length);
  for (let i = 1; i < a.starts.length; i++) {
    const gap = a.starts[i] - a.starts[i - 1];
    assert.ok(gap >= 2 - 0.02 && gap <= 6 + 0.02, 'gap ' + gap);
  }
  assert.ok(a.longest >= 0.1 && a.longest <= 0.15, 'blink length ' + a.longest);
});

test('blink closes the eye fully and reopens', () => {
  let s = Face.initialState(), maxAmt = 0;
  s = run(s, 3.5, null, seeded(1), (st) => { maxAmt = Math.max(maxAmt, st.blink.amt); });
  assert.ok(maxAmt > 0.9);
  s = Face.initialState();
  s.blink.next = 0.001;
  s = run(s, 0.3, null, seeded(1));
  assert.equal(s.blink.amt, 0);
});

test('gaze spring converges to the target and barely overshoots', () => {
  for (const [tx, ty] of [[1, 0], [-1, 1], [0.3, -0.7]]) {
    let s = Face.initialState(), maxOver = 0;
    s = run(s, 1.0, { mood: 'happy', look: { x: tx, y: ty } }, seeded(3), (st) => {
      maxOver = Math.max(maxOver, (st.gaze.x - tx) * Math.sign(tx || 1), (st.gaze.y - ty) * Math.sign(ty || 1));
    });
    assert.ok(Math.abs(s.gaze.x - tx) < 0.01 && Math.abs(s.gaze.y - ty) < 0.01, JSON.stringify(s.gaze));
    assert.ok(maxOver < 0.01, 'overshoot ' + maxOver);
  }
  // starting with velocity the wrong way still settles without much overshoot
  let s = Face.initialState();
  s.gaze.vx = -10;
  let maxX = -Infinity;
  s = run(s, 1.5, { mood: 'happy', look: { x: 0.5, y: 0 } }, seeded(3), (st) => { maxX = Math.max(maxX, st.gaze.x); });
  assert.ok(Math.abs(s.gaze.x - 0.5) < 0.01);
  assert.ok(maxX < 0.5 + 0.05, 'max ' + maxX);
  // big jumps in dt stay stable
  s = Face.step(Face.initialState(), 0.25, { look: { x: 1, y: 1 } }, seeded(1));
  assert.ok(s.gaze.x <= 1 && s.gaze.y <= 1);
});

test('lookAt clamps to -1..1; null or junk means wander', () => {
  let s = Face.step(Face.initialState(), 1 / 60, { look: { x: 5, y: -3 } }, seeded(1));
  assert.deepEqual(s.look, { x: 1, y: -1 });
  s = Face.step(s, 1 / 60, { look: { x: NaN, y: 0 } }, seeded(1));
  assert.equal(s.look, null);
  s = Face.step(s, 1 / 60, { look: { x: 0.2, y: 0.1 } }, seeded(1));
  s = Face.step(s, 1 / 60, {}, seeded(1));
  assert.deepEqual(s.look, { x: 0.2, y: 0.1 }, 'missing look keeps the target');
  s = Face.step(s, 1 / 60, { look: null }, seeded(1));
  assert.equal(s.look, null);
  // wandering stays gentle
  let maxAbs = 0;
  run(s, 30, null, seeded(9), (st) => { maxAbs = Math.max(maxAbs, Math.abs(st.gaze.x), Math.abs(st.gaze.y)); });
  assert.ok(maxAbs > 0.05 && maxAbs <= 0.61, 'wander range ' + maxAbs);
});

test('mood transitions blend, then settle exactly', () => {
  let s = Face.initialState();
  s = run(s, 0.05, { mood: 'happy' }, seeded(1));
  assert.ok(s.w.happy > 0.2 && s.w.happy < 0.9, 'mid blend ' + s.w.happy);
  assert.ok(s.w.idle > 0.1 && s.w.idle < 0.8);
  const sum = Face.MOODS.reduce((acc, m) => acc + s.w[m], 0);
  assert.ok(Math.abs(sum - 1) < 1e-9);
  s = run(s, 0.25, null, seeded(1));
  assert.equal(s.w.happy, 1);
  assert.equal(s.w.idle, 0);
  assert.equal(s.mood, 'happy');
});

test('unknown mood falls back to idle', () => {
  let s = Face.step(Face.initialState(), 1 / 60, { mood: 'happy' }, seeded(1));
  s = Face.step(s, 1 / 60, { mood: 'grumpy' }, seeded(1));
  assert.equal(s.mood, 'idle');
  s = run(s, 0.5, null, seeded(1));
  assert.equal(s.w.idle, 1);
});

test('mouth opens faster than it closes, and clamps', () => {
  let s = Face.initialState(), tOpen = null, tClose = null;
  run(s, 0.3, { mouth: 1 }, seeded(1), (st) => { if (tOpen === null && st.mouth >= 0.9) tOpen = st.t; s = st; });
  const t0 = s.t;
  run(s, 0.4, { mouth: 0 }, seeded(1), (st) => { if (tClose === null && st.mouth <= 0.1) tClose = st.t - t0; });
  assert.ok(tOpen !== null && tOpen <= 0.07, 'open ' + tOpen);
  assert.ok(tClose !== null && tClose > tOpen && tClose <= 0.15, 'close ' + tClose);
  s = Face.step(Face.initialState(), 1 / 60, { mouth: 7 }, seeded(1));
  assert.equal(s.level, 1);
  s = Face.step(s, 1 / 60, { mouth: -2 }, seeded(1));
  assert.equal(s.level, 0);
});

test('pulseMouth opens quickly then decays to closed', () => {
  let s = Face.initialState(), peak = 0, peakT = 0;
  s = run(s, 0.6, { pulse: 1 }, seeded(1), (st) => { if (st.mouth > peak) { peak = st.mouth; peakT = st.t; } });
  assert.ok(peak > 0.6, 'peak ' + peak);
  assert.ok(peakT < 0.15, 'peak at ' + peakT);
  assert.ok(s.mouth < 0.02, 'end ' + s.mouth);
  assert.equal(s.pulse.amp, 0);
  // a pulse on top of speech never closes the mouth below the speech level
  s = run(Face.initialState(), 0.6, { mouth: 0.4, pulse: 1 }, seeded(1));
  assert.ok(Math.abs(s.mouth - 0.4) < 1e-3);
});

test('step does not mutate its input state', () => {
  const s = Face.initialState(), before = JSON.stringify(s);
  Face.step(s, 0.1, { mood: 'alarm', look: { x: 1, y: 1 }, mouth: 1, pulse: 1 }, seeded(1));
  assert.equal(JSON.stringify(s), before);
});

test('draw runs for every mood, mid-transition, blinking and talking, with finite numbers only', () => {
  const states = [];
  for (const m of Face.MOODS) {
    let s = run(Face.initialState(), 0.5, { mood: m, look: { x: 0.7, y: -0.4 }, mouth: 0.6 }, seeded(2));
    states.push(s);
    states.push(run(s, 0.06, { mood: m === 'idle' ? 'happy' : 'idle' }, seeded(2)));   // mid-blend
    const b = JSON.parse(JSON.stringify(s)); b.blink.amt = 1; b.blink.t = 0.05; states.push(b);
  }
  for (const s of states) {
    for (const [W, H] of [[1170, 2532], [1440, 800], [1, 1]]) {
      const { ctx, calls } = fakeCtx();
      Face.draw(ctx, W, H, s);
      assert.ok(calls.some((c) => c[0] === 'fillRect'), 'background');
      assert.ok(calls.some((c) => c[0] === 'fill'), 'something filled');
      for (const [name, args] of calls) {
        for (const a of args) if (typeof a === 'number') assert.ok(Number.isFinite(a), name + ' got ' + a);
      }
      const saves = calls.filter((c) => c[0] === 'save').length, restores = calls.filter((c) => c[0] === 'restore').length;
      assert.equal(saves, restores);
    }
  }
});

test('alarm uses the alarm background and red chevrons', () => {
  const s = run(Face.initialState(), 0.5, { mood: 'alarm' }, seeded(1));
  const { ctx, calls } = fakeCtx();
  Face.draw(ctx, 390, 844, s);
  const sets = calls.filter((c) => c[0].startsWith('=')).map((c) => [c[0], c[1][0]]);
  assert.ok(sets.some(([k, v]) => k === '=fillStyle' && v === 'rgb(252,235,235)'));
  assert.ok(sets.some(([k, v]) => k === '=strokeStyle' && v === '#A32D2D'));
});

test('create(): setters clamp and normalize; start/stop drive requestAnimationFrame at device pixels', () => {
  const { ctx, calls } = fakeCtx();
  const canvas = { width: 0, height: 0, clientWidth: 390, clientHeight: 844, getContext: () => ctx };
  const queue = [];
  globalThis.requestAnimationFrame = (fn) => { queue.push(fn); return queue.length; };
  globalThis.cancelAnimationFrame = () => { queue.length = 0; };
  globalThis.window = { devicePixelRatio: 3 };
  try {
    const face = Face.create(canvas);
    face.setMood('nope');
    assert.equal(face.snapshot().mood, 'idle');
    face.setMood('sleepy');
    assert.equal(face.snapshot().mood, 'sleepy');
    face.lookAt(3, -0.5);
    assert.deepEqual(face.snapshot().look, { x: 1, y: -0.5 });
    face.lookAt(null);
    assert.equal(face.snapshot().look, null);
    face.setMouth(2); assert.equal(face.snapshot().level, 1);
    face.setMouth(-1); assert.equal(face.snapshot().level, 0);
    face.pulseMouth(0.8); assert.equal(face.snapshot().pulse.amp, 0.8);
    const snap = face.snapshot(); snap.mood = 'hacked';
    assert.equal(face.snapshot().mood, 'sleepy', 'snapshot is a copy');

    face.start();
    for (let i = 0; i < 5; i++) queue.shift()(1000 + i * 16);
    assert.equal(canvas.width, 1170);
    assert.equal(canvas.height, 2532);
    assert.ok(calls.filter((c) => c[0] === 'fillRect').length >= 5);
    assert.ok(face.snapshot().t > 0);
    face.stop();
    assert.equal(queue.length, 0);
  } finally {
    delete globalThis.requestAnimationFrame; delete globalThis.cancelAnimationFrame; delete globalThis.window;
  }
});
