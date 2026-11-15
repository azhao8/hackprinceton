// Tests for the quick pills below the face (#101): when "I put items in his tray" and "Recalibrate tilt sensor" show.
// The rules live in index.html's "quick rules" block (no separate file, so the server serves nothing new); this reads
// that block and runs it. Run: node --test firmware/balance/phone/*.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const block = html.match(/\/\/ -+ quick rules \(#101\)[\s\S]*?\/\/ -+ end quick rules -+/);
assert.ok(block, 'index.html has the quick rules block');
const { stillStep, isStill, quickView, STILL_MS } =
  new Function(block[0] + '\nreturn { stillStep, isStill, quickView, STILL_MS };')();

// a robot on the main server, idle, lying still, nothing going on: only Recalibrate shows
const IDLE = { has: true, cal: false, tray: false, drift: false, calibrating: false, state: 'idle', waiting: false,
               still: true };
const view = (over) => quickView({ ...IDLE, ...over });

test('nothing shows on the bench server (no robot fields in /tel)', () => {
  assert.deepEqual(view({ has: false, tray: true, calibrating: true }), { tray: false, calNote: false, recal: false });
});

test('tray shows only while the bring skill waits for it', () => {
  assert.equal(view({ tray: true }).tray, true);
  assert.equal(view({ tray: false }).tray, false);
  assert.equal(view({ tray: true, state: 'balance', still: false }).tray, true);   // balancing at the station: still shows
  assert.equal(view({ tray: true, state: 'drive' }).tray, true);
});

test('recalibrate shows when he is idle and lying still', () => {
  assert.deepEqual(view({}), { tray: false, calNote: false, recal: true });
});

test('recalibrate hides while balancing or driving (the server refuses it then)', () => {
  assert.equal(view({ state: 'balance' }).recal, false);
  assert.equal(view({ state: 'drive' }).recal, false);
  assert.equal(view({ state: '' }).recal, false);                                    // no telemetry: unknown
});

test('recalibrate hides while he moves, while Start waits, and while the drift banner shows its own', () => {
  assert.equal(view({ still: false }).recal, false);
  assert.equal(view({ waiting: true }).recal, false);
  assert.equal(view({ drift: true }).recal, false);
});

test('while calibrating, the note takes the button\'s place', () => {
  assert.deepEqual(view({ calibrating: true }), { tray: false, calNote: true, recal: false });
  assert.equal(view({ calibrating: true, state: 'balance' }).calNote, true);
});

test("nothing shows during the phone's own recalibrate countdown (its overlay covers the screen)", () => {
  assert.deepEqual(view({ cal: true, tray: true, calibrating: true }), { tray: false, calNote: false, recal: false });
});

test('lying still: idle with a small tilt rate and a steady tilt, for STILL_MS', () => {
  const tel = (pitch, rate, state = 'idle') => ({ state, pitch, rate });
  let s = stillStep(null, tel(80, 0.4), 0);
  assert.equal(isStill(s, 0), false);
  s = stillStep(s, tel(80.5, -0.3), 1000);
  assert.equal(isStill(s, 1000), false);
  s = stillStep(s, tel(79.8, 0.2), STILL_MS);
  assert.equal(isStill(s, STILL_MS), true);
});

test('moving, held, balancing or no telemetry starts the clock again', () => {
  const t0 = stillStep(null, { state: 'idle', pitch: 80, rate: 0 }, 0);
  assert.equal(stillStep(t0, { state: 'idle', pitch: 80, rate: 40 }, 500), null);         // swinging
  assert.equal(stillStep(t0, { state: 'balance', pitch: 2, rate: 0 }, 500), null);
  assert.equal(stillStep(t0, {}, 500), null);
  assert.equal(stillStep(t0, null, 500), null);
  const moved = stillStep(t0, { state: 'idle', pitch: 70, rate: 1 }, 1000);              // slid 10 deg slowly
  assert.equal(moved.since, 1000);
  assert.equal(isStill(moved, 1000 + STILL_MS - 1), false);
  assert.equal(isStill(null, 1e9), false);
});

test('the page has the elements the rules drive', () => {
  for (const id of ['actTray', 'actRecal', 'calNote']) assert.match(html, new RegExp(`id="${id}" class="q"`));
});
