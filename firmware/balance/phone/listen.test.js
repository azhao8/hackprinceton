// Tests for the listening sounds (#111): when the "I'm listening" ping and the "done listening" chime play.
// The rules and Listen live in index.html (no separate file, so the server serves nothing new); this reads that code
// and runs it with a fake clock, fake timers and a fake Voice that counts the sounds. Not the audio itself.
// Run: node --test firmware/balance/phone/*.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const code = html.match(/\/\/ -+ listen sound rules \(#111\)[\s\S]*?\nconst Listen = \(\(\) => \{[\s\S]*?\n\}\)\(\);/);
assert.ok(code, 'index.html has the listen sound rules block followed by Listen');

// A page with the ring off, nothing playing. talk(true/false) makes Miguel (not) talking; wait(ms) runs the clock.
function page() {
  let now = 1000, talking = false, timers = [];
  const sounds = [];
  const Voice = { ping: () => sounds.push('ping'), chime: () => sounds.push('chime'), busy: () => talking };
  const performance = { now: () => now };
  const setTimeout = (fn, ms) => { timers.push({ at: now + ms, fn }); };
  const face = { setListening() {} };
  const { Listen, CHIME_WAIT_MS } = new Function('Voice', 'face', 'performance', 'setTimeout',
    code[0] + '\nreturn { Listen, CHIME_WAIT_MS };')(Voice, face, performance, setTimeout);
  function wait(ms) {
    const end = now + ms;
    for (;;) {
      timers.sort((a, b) => a.at - b.at);
      const t = timers[0];
      if (!t || t.at > end) break;
      timers.shift(); now = t.at; t.fn();
    }
    now = end;
  }
  return {
    Listen, sounds, wait, WAIT: CHIME_WAIT_MS,
    talk(on) { talking = on; },
    server(on, why) { Listen.set(on, why, true); },          // {type: 'listen', on, why} over the mic socket
  };
}

test('the chime is short, falling, and softer than the ping', () => {
  const sound = name => {                                     // const <name> = () => tones([[Hz, s, s], ...], peak);
    const m = html.match(new RegExp(`const ${name} = \\(\\) => tones\\((\\[\\[.*?\\]\\]), ([\\d.]+)\\)`));
    assert.ok(m, `${name} is a tones() call`);
    return { notes: JSON.parse(m[1]), peak: Number(m[2]) };
  };
  const ping = sound('ping'), chime = sound('chime');
  assert.ok(ping.notes[0][0] < ping.notes[1][0], 'the ping rises');
  assert.ok(chime.notes[0][0] > chime.notes[1][0], 'the chime falls');
  assert.ok(Math.max(...chime.notes.map(([, at, len]) => at + len)) < 0.3, 'the chime is under 0.3 s');
  assert.ok(chime.peak < ping.peak, 'the chime is quieter than the ping');
});

test('heard the request: ping when the ring turns on, one chime a moment after it goes off', () => {
  const p = page();
  p.server(true, 'wake');
  assert.deepEqual(p.sounds, ['ping']);
  p.server(false, null);
  assert.deepEqual(p.sounds, ['ping'], 'not at once');
  p.wait(p.WAIT);
  assert.deepEqual(p.sounds, ['ping', 'chime']);
  p.wait(5000);
  assert.deepEqual(p.sounds, ['ping', 'chime'], 'only once');
});

test('the answer window running out with nothing heard chimes once', () => {
  const p = page();
  p.server(true, 'question');
  p.wait(6000);
  p.server(false, null);
  p.wait(p.WAIT);
  assert.deepEqual(p.sounds, ['ping', 'chime']);
});

test('tapped off: chimes once, and the server confirming it adds nothing', () => {
  const p = page();
  p.Listen.set(true, 'tap');                                  // the tap turns it on at once
  p.server(true, 'tap');                                      // the server confirms
  p.wait(2000);
  p.Listen.set(false);                                        // tapped again: off at once
  p.wait(50);
  p.server(false, null);                                      // the server confirms
  p.Listen.set(false, null);                                  // and /tel says so too
  p.wait(p.WAIT);
  assert.deepEqual(p.sounds, ['ping', 'chime']);
});

test('"Miguel?" alone: the ring blinks off and back on, so no chime and no second ping', () => {
  const p = page();
  p.server(true, 'wake');                                     // heard the name while they talk
  p.server(false, null);                                      // the turn ends...
  p.wait(5);
  p.server(true, 'wake');                                     // ...and listening reopens for the request
  p.wait(p.WAIT * 3);
  assert.deepEqual(p.sounds, ['ping']);
  p.server(false, null);                                      // the request heard (or the window ran out)
  p.wait(p.WAIT);
  assert.deepEqual(p.sounds, ['ping', 'chime']);
});

test('flapping off and on settles to one chime, at the end', () => {
  const p = page();
  p.server(true, 'tap');
  for (let i = 0; i < 4; i++) { p.server(false, null); p.wait(p.WAIT / 3); p.server(true, 'tap'); p.wait(p.WAIT / 3); }
  p.server(false, null);
  p.wait(p.WAIT - 1);
  assert.deepEqual(p.sounds, ['ping']);
  p.wait(1);
  assert.deepEqual(p.sounds, ['ping', 'chime']);
});

test('no chime while Miguel talks: talking when the ring goes off', () => {
  const p = page();
  p.server(true, 'reply');
  p.talk(true);                                               // he starts a line: the server turns the ring off
  p.server(false, null);
  p.wait(p.WAIT);
  p.talk(false);
  p.wait(5000);
  assert.deepEqual(p.sounds, ['ping']);
});

test('no chime after a short line that turned the ring off ends within the wait', () => {
  const p = page();
  p.server(true, 'reply');
  p.talk(true);
  p.server(false, null);
  p.wait(100);
  p.talk(false);                                              // "OK." is over before the chime would be due
  p.wait(5000);
  assert.deepEqual(p.sounds, ['ping']);
});

test('no chime while Miguel talks: his line arrives just after the ring goes off', () => {
  const p = page();
  p.server(true, 'reply');
  p.server(false, null);                                      // the server turns the ring off just before the line
  p.wait(10);
  p.talk(true);                                               // the line is queued
  p.wait(p.WAIT);
  assert.deepEqual(p.sounds, ['ping']);
});

test('a new turn after the chime pings and chimes again', () => {
  const p = page();
  p.server(true, 'wake'); p.server(false, null); p.wait(p.WAIT);
  p.wait(2000);
  p.server(true, 'tap'); p.server(false, null); p.wait(p.WAIT);
  assert.deepEqual(p.sounds, ['ping', 'chime', 'ping', 'chime']);
});

test('an off with the ring already off, or a page that just opened, plays nothing', () => {
  const p = page();
  p.server(false, null);
  p.Listen.set(false, null);
  p.wait(5000);
  assert.deepEqual(p.sounds, []);
});
