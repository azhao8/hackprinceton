// Miguel's "Mochi" face, drawn on a canvas: cream face, two big dark eyes with sparkles, rosy blush, a tiny mouth.
// Cute and cartoony on purpose: no pupils, no whites, no realistic features (those look uncanny on a robot).
//
// Pure core (no DOM, testable in Node): Face.initialState(), Face.step(state, dt, inputs, rng), Face.draw(ctx, W, H, state).
// Browser wrapper: Face.create(canvas) -> { setMood, lookAt, setMouth, pulseMouth, start, stop, snapshot }.
//
// Layout is in units of u = min(width, 0.62 * height), so a portrait phone gets the designed proportions
// (u = width) and a wide desktop window gets the same face centered instead of stretched.
var Face = (function () {
  var MOODS = ['idle', 'happy', 'surprised', 'worried', 'sleepy', 'listening', 'alarm'];
  var OVAL_MOODS = ['idle', 'surprised', 'worried', 'listening'];   // moods drawn with open oval eyes

  var C = {
    bg: '#FAEEDA', bgAlarm: '#FCEBEB', eye: '#2C2C2A', eyeAlarm: '#A32D2D',
    blush: '#F4C0D1', mouth: '#993C1D', sparkle: '#FFFFFF'
  };

  // ---- timing ----
  var MOOD_TAU = 0.05;                       // mood blend time constant: ~95% in 150 ms, snaps to done at ~230 ms
  var GAZE_OMEGA = 16;                       // critically damped spring, rad/s: settles in ~0.35 s, no overshoot
  var BLINK_MIN = 2, BLINK_MAX = 6, BLINK_CLOSE = 0.045, BLINK_LEN = 0.12;
  var MOUTH_TAU_OPEN = 0.018, MOUTH_TAU_CLOSE = 0.04;   // ~90% in 40 ms opening, ~90% in 90 ms closing
  var PULSE_HOLD = 0.05, PULSE_TAU = 0.06;
  var SAC_TAU = 0.02;                        // micro-saccades are quick
  var GLANCE_X = 0.06, GLANCE_Y = 0.04;      // max eye shift, in u (fraction of width on a phone)

  // ---- shapes (all in u) ----
  var EYE_DX = 0.20, EYE_RX = 0.11, EYE_RY = 0.13, MOUTH_DY = 0.26;
  // per-mood oval eye scale [x, y]
  var EYE_SCALE = { idle: [1, 1], surprised: [1.2, 1.12], worried: [1, 0.96], listening: [1.06, 1.06] };
  // per-mood mouth: [half width, top height, bottom height, top added when open, bottom added when open].
  // Heights are measured from the corners' line: top > 0 bulges up, bottom > 0 bulges down.
  var MOUTH = {
    idle:      [0.030, 0.008, 0.011, 0.016, 0.036],
    happy:     [0.040, -0.004, 0.028, 0.008, 0.030],
    surprised: [0.022, 0.022, 0.026, 0.008, 0.012],
    worried:   [0.028, 0.019, -0.006, 0.006, 0.028],
    sleepy:    [0.017, 0.005, 0.007, 0.008, 0.018],
    listening: [0.026, 0.008, 0.010, 0.016, 0.034],
    alarm:     [0.034, 0.005, 0.004, 0.010, 0.026]
  };

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function num(v, d) { return typeof v === 'number' && isFinite(v) ? v : d; }
  function normMood(m) { return MOODS.indexOf(m) >= 0 ? m : 'idle'; }
  function normLook(l) {
    if (!l || !isFinite(l.x) || !isFinite(l.y)) return null;
    return { x: clamp(+l.x, -1, 1), y: clamp(+l.y, -1, 1) };
  }
  function ease(cur, target, dt, tau) { return target + (cur - target) * Math.exp(-dt / tau); }
  function smooth(x) { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); }

  function initialState() {
    var w = {};
    MOODS.forEach(function (m) { w[m] = m === 'idle' ? 1 : 0; });
    return {
      t: 0,
      mood: 'idle',
      w: w,                                           // blend weight of each mood, sums to 1
      look: null,                                     // target from lookAt, or null = wander
      gaze: { x: 0, y: 0, vx: 0, vy: 0 },             // spring-driven eye direction, -1..1
      wander: { x: 0, y: 0, next: 1.5 },
      sac: { x: 0, y: 0, tx: 0, ty: 0, next: 1.0 },   // micro-saccade offset (idle only)
      blink: { next: 3, t: -1, amt: 0 },              // amt: 0 open .. 1 closed
      level: 0,                                       // mouth openness asked for (setMouth)
      pulse: { amp: 0, age: 0 },                      // a word pulse in progress
      mouth: 0                                        // eased mouth openness that gets drawn
    };
  }

  function clone(s) {
    var w = {};
    for (var k in s.w) w[k] = s.w[k];
    return {
      t: s.t, mood: s.mood, w: w,
      look: s.look ? { x: s.look.x, y: s.look.y } : null,
      gaze: { x: s.gaze.x, y: s.gaze.y, vx: s.gaze.vx, vy: s.gaze.vy },
      wander: { x: s.wander.x, y: s.wander.y, next: s.wander.next },
      sac: { x: s.sac.x, y: s.sac.y, tx: s.sac.tx, ty: s.sac.ty, next: s.sac.next },
      blink: { next: s.blink.next, t: s.blink.t, amt: s.blink.amt },
      level: s.level, pulse: { amp: s.pulse.amp, age: s.pulse.age }, mouth: s.mouth
    };
  }

  // inputs (all optional): { mood, look: {x, y} | null (undefined = keep), mouth: 0..1, pulse: 0..1 (one-shot) }
  function applyInputs(s, inputs) {
    if (!inputs) return s;
    if (inputs.mood !== undefined) s.mood = normMood(inputs.mood);
    if (inputs.look !== undefined) s.look = normLook(inputs.look);
    if (inputs.mouth !== undefined) s.level = clamp(num(inputs.mouth, 0), 0, 1);
    var p = clamp(num(inputs.pulse, 0), 0, 1);
    if (p > 0) { s.pulse.amp = Math.max(p, s.pulse.amp * pulseEnv(s.pulse.age)); s.pulse.age = 0; }
    return s;
  }

  function pulseEnv(age) { return age < PULSE_HOLD ? 1 : Math.exp(-(age - PULSE_HOLD) / PULSE_TAU); }

  // exact critically damped spring step (no numerical overshoot at any dt)
  function spring(x, v, target, dt) {
    var c1 = x - target, c2 = v + GAZE_OMEGA * c1, e = Math.exp(-GAZE_OMEGA * dt);
    return [target + (c1 + c2 * dt) * e, (c2 - GAZE_OMEGA * (c1 + c2 * dt)) * e];
  }

  function step(state, dt, inputs, rng) {
    rng = rng || Math.random;
    dt = clamp(num(dt, 0), 0, 0.25);
    var s = applyInputs(clone(state), inputs);
    s.t += dt;

    // mood blend: every weight eases toward 1 (current mood) or 0, so the sum stays 1
    var a = 1 - Math.exp(-dt / MOOD_TAU), far = 0;
    MOODS.forEach(function (m) {
      var target = m === s.mood ? 1 : 0;
      s.w[m] += (target - s.w[m]) * a;
      far = Math.max(far, Math.abs(target - s.w[m]));
    });
    if (far < 0.01) MOODS.forEach(function (m) { s.w[m] = m === s.mood ? 1 : 0; });

    // blinks: one every 2-6 s, ~120 ms long
    s.blink.next -= dt;
    if (s.blink.t >= 0) s.blink.t += dt;
    if (s.blink.next <= 0) { s.blink.t = 0; s.blink.next = BLINK_MIN + (BLINK_MAX - BLINK_MIN) * rng(); }
    if (s.blink.t > BLINK_LEN) s.blink.t = -1;
    var bt = s.blink.t;
    s.blink.amt = bt < 0 ? 0 : bt < BLINK_CLOSE ? smooth(bt / BLINK_CLOSE) : 1 - smooth((bt - BLINK_CLOSE) / (BLINK_LEN - BLINK_CLOSE));

    // where to look: the target, or a gentle wander with occasional small glances
    var tx, ty;
    if (s.look) { tx = s.look.x; ty = s.look.y; }
    else {
      s.wander.next -= dt;
      if (s.wander.next <= 0) {
        if (rng() < 0.35) { s.wander.x = 0; s.wander.y = 0; }
        else { s.wander.x = (rng() * 2 - 1) * 0.6; s.wander.y = (rng() * 2 - 1) * 0.35; }
        s.wander.next = 1.2 + 2.3 * rng();
      }
      tx = s.wander.x; ty = s.wander.y;
    }
    var gx = spring(s.gaze.x, s.gaze.vx, tx, dt), gy = spring(s.gaze.y, s.gaze.vy, ty, dt);
    s.gaze.x = gx[0]; s.gaze.vx = gx[1]; s.gaze.y = gy[0]; s.gaze.vy = gy[1];

    // tiny quick saccades while idle
    s.sac.next -= dt;
    if (s.sac.next <= 0) {
      if (s.w.idle > 0.5) { s.sac.tx = (rng() * 2 - 1) * 0.08; s.sac.ty = (rng() * 2 - 1) * 0.06; }
      else { s.sac.tx = 0; s.sac.ty = 0; }
      s.sac.next = 0.6 + 1.8 * rng();
    }
    if (s.w.idle <= 0.5) { s.sac.tx = 0; s.sac.ty = 0; }
    s.sac.x = ease(s.sac.x, s.sac.tx, dt, SAC_TAU);
    s.sac.y = ease(s.sac.y, s.sac.ty, dt, SAC_TAU);

    // mouth: max of the audio level and any word pulse; opens fast, closes slower
    s.pulse.age += dt;
    var p = s.pulse.amp * pulseEnv(s.pulse.age);
    if (p < 1e-3) { s.pulse.amp = 0; p = 0; }
    var want = Math.max(s.level, p);
    s.mouth = ease(s.mouth, want, dt, want > s.mouth ? MOUTH_TAU_OPEN : MOUTH_TAU_CLOSE);
    if (Math.abs(s.mouth - want) < 1e-4) s.mouth = want;
    return s;
  }

  // ---------------- drawing ----------------
  function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
  function mix(c1, c2, k) {
    var a = hex(c1), b = hex(c2);
    return 'rgb(' + [0, 1, 2].map(function (i) { return Math.round(a[i] + (b[i] - a[i]) * k); }).join(',') + ')';
  }

  function draw(ctx, W, H, s) {
    var w = s.w, u = Math.min(W, 0.62 * H), t = s.t;
    var wOval = 0; OVAL_MOODS.forEach(function (m) { wOval += w[m]; });

    ctx.save();
    ctx.globalAlpha = 1;
    ctx.fillStyle = mix(C.bg, C.bgAlarm, w.alarm);
    ctx.fillRect(0, 0, W, H);

    var bob = Math.sin(t * 2 * Math.PI / 4) * 0.004 * u;            // slow "breathing"
    var gx = clamp(s.gaze.x + s.sac.x, -1.1, 1.1), gy = clamp(s.gaze.y + s.sac.y, -1.1, 1.1);
    var ox = gx * GLANCE_X * u, oy = gy * GLANCE_Y * u;             // eye shift toward the target
    var cx = W / 2, cy = H / 2 + bob;
    var eyes = [{ x: cx - EYE_DX * u + ox, y: cy + oy, side: -1 }, { x: cx + EYE_DX * u + ox, y: cy + oy, side: 1 }];

    // blush (behind the eyes), follows the gaze a little
    var blushA = 0.9 * (1 - 0.7 * w.alarm), blushK = 1 + 0.15 * w.happy;
    ctx.fillStyle = C.blush;
    ctx.globalAlpha = blushA;
    eyes.forEach(function (e) {
      ctx.beginPath();
      ctx.ellipse(cx + e.side * (EYE_DX + 0.08) * u + 0.3 * ox, cy + 0.16 * u + 0.3 * oy,
                  0.075 * u * blushK, 0.042 * u * blushK, 0, 0, 2 * Math.PI);
      ctx.fill();
    });
    ctx.globalAlpha = 1;

    // oval eyes (idle / surprised / worried / listening), squashed by blinks and by moving to an arc mood
    var sx = 0, sy = 0;
    OVAL_MOODS.forEach(function (m) { sx += w[m] * EYE_SCALE[m][0]; sy += w[m] * EYE_SCALE[m][1]; });
    if (wOval > 1e-3) { sx /= wOval; sy /= wOval; } else { sx = sy = 1; }
    var open = wOval * (1 - s.blink.amt);
    if (open > 0.01) {
      var rx = EYE_RX * u * sx, ryFull = EYE_RY * u * sy, ry = Math.max(ryFull * open, 0.012 * u);
      eyes.forEach(function (e) {
        ctx.fillStyle = C.eye;
        ctx.beginPath(); ctx.ellipse(e.x, e.y, rx, ry, 0, 0, 2 * Math.PI); ctx.fill();
        var k = clamp((open - 0.3) / 0.4, 0, 1);                    // sparkles fade out as the eye closes
        if (k > 0) {
          ctx.fillStyle = C.sparkle;
          ctx.globalAlpha = k;
          ctx.beginPath(); ctx.arc(e.x + 0.36 * rx, e.y - 0.42 * ry, 0.30 * rx, 0, 2 * Math.PI); ctx.fill();
          ctx.beginPath(); ctx.arc(e.x - 0.40 * rx, e.y + 0.44 * ry, 0.13 * rx, 0, 2 * Math.PI); ctx.fill();
          ctx.globalAlpha = 1;
        }
      });
    } else if (wOval > 0.01) {
      // fully blinked: a soft closed line
      ctx.strokeStyle = C.eye; ctx.lineWidth = 0.035 * u; ctx.lineCap = 'round';
      eyes.forEach(function (e) {
        ctx.beginPath(); ctx.moveTo(e.x - 0.8 * EYE_RX * u, e.y); ctx.lineTo(e.x + 0.8 * EYE_RX * u, e.y); ctx.stroke();
      });
    }

    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    // happy: upward arcs ^ ^
    if (w.happy > 0.01) {
      ctx.strokeStyle = C.eye; ctx.lineWidth = 0.05 * u; ctx.globalAlpha = Math.min(1, w.happy * 1.5);
      eyes.forEach(function (e) {
        var r = EYE_RX * u * 0.9, h = EYE_RY * u * 0.95 * w.happy;
        ctx.beginPath(); ctx.moveTo(e.x - r, e.y + 0.25 * h); ctx.quadraticCurveTo(e.x, e.y - 1.3 * h, e.x + r, e.y + 0.25 * h); ctx.stroke();
      });
    }
    // sleepy: closed downward arcs
    if (w.sleepy > 0.01) {
      ctx.strokeStyle = C.eye; ctx.lineWidth = 0.042 * u; ctx.globalAlpha = Math.min(1, w.sleepy * 1.5);
      eyes.forEach(function (e) {
        var r = EYE_RX * u * 0.85, h = EYE_RY * u * 0.55 * w.sleepy, y = e.y + 0.15 * EYE_RY * u;
        ctx.beginPath(); ctx.moveTo(e.x - r, y); ctx.quadraticCurveTo(e.x, y + 1.2 * h, e.x + r, y); ctx.stroke();
      });
    }
    // alarm: > < chevrons
    if (w.alarm > 0.01) {
      ctx.strokeStyle = C.eyeAlarm; ctx.lineWidth = 0.055 * u; ctx.globalAlpha = Math.min(1, w.alarm * 1.5);
      eyes.forEach(function (e) {
        var r = EYE_RX * u * 0.65, h = EYE_RY * u * 0.6 * w.alarm, tip = -e.side;   // left eye ">" points right
        ctx.beginPath(); ctx.moveTo(e.x - tip * r, e.y - h); ctx.lineTo(e.x + tip * r, e.y); ctx.lineTo(e.x - tip * r, e.y + h); ctx.stroke();
      });
    }
    // worried: small tilted brows, inner ends higher
    if (w.worried > 0.01) {
      ctx.strokeStyle = C.eye; ctx.lineWidth = 0.028 * u; ctx.globalAlpha = w.worried;
      eyes.forEach(function (e) {
        var top = e.y - EYE_RY * u * sy - 0.06 * u, inner = -e.side;          // inner = toward the face's center
        ctx.beginPath();
        ctx.moveTo(e.x - inner * 0.55 * EYE_RX * u, top);
        ctx.lineTo(e.x + inner * 0.55 * EYE_RX * u, top - 0.045 * u);
        ctx.stroke();
      });
    }
    ctx.globalAlpha = 1;

    // mouth: blend of the moods' shapes, opened by s.mouth
    var mp = [0, 0, 0, 0, 0];
    MOODS.forEach(function (m) { for (var i = 0; i < 5; i++) mp[i] += w[m] * MOUTH[m][i]; });
    var op = clamp(s.mouth, 0, 1);
    var mw = mp[0] * (1 - 0.15 * op) * u, top = (mp[1] + op * mp[3]) * u, bot = (mp[2] + op * mp[4]) * u;
    var mx = cx + 0.3 * ox, my = cy + MOUTH_DY * u + 0.3 * oy, K = 4 / 3;
    ctx.fillStyle = C.mouth; ctx.strokeStyle = C.mouth; ctx.lineWidth = 0.008 * u;
    ctx.beginPath();
    ctx.moveTo(mx - mw, my);
    ctx.bezierCurveTo(mx - mw, my - K * top, mx + mw, my - K * top, mx + mw, my);
    ctx.bezierCurveTo(mx + mw, my + K * bot, mx - mw, my + K * bot, mx - mw, my);
    ctx.closePath();
    ctx.fill(); ctx.stroke();

    // sleepy: little z's floating up
    if (w.sleepy > 0.01) {
      ctx.strokeStyle = C.eye; ctx.lineWidth = 0.01 * u;
      for (var i = 0; i < 3; i++) {
        var ph = (t / 2.4 + i / 3) % 1, size = 0.028 * u * (0.6 + 0.8 * ph);
        var zx = cx + (EYE_DX + 0.12) * u + ph * 0.08 * u, zy = cy - 0.2 * u - ph * 0.28 * u;
        ctx.globalAlpha = 0.65 * Math.sin(Math.PI * ph) * w.sleepy;
        ctx.beginPath();
        ctx.moveTo(zx - size / 2, zy - size / 2); ctx.lineTo(zx + size / 2, zy - size / 2);
        ctx.lineTo(zx - size / 2, zy + size / 2); ctx.lineTo(zx + size / 2, zy + size / 2);
        ctx.stroke();
      }
    }
    // listening: sound-wave arcs beside the right eye
    if (w.listening > 0.01) {
      ctx.strokeStyle = C.eye; ctx.lineWidth = 0.012 * u;
      var wx = eyes[1].x + EYE_RX * u * sx + 0.02 * u, wy = eyes[1].y;
      for (var j = 0; j < 3; j++) {
        var pulse = 0.5 + 0.5 * Math.sin(t * 6 - j * 1.1);
        ctx.globalAlpha = (0.2 + 0.4 * pulse) * w.listening;
        ctx.beginPath(); ctx.arc(wx, wy, (0.035 + 0.03 * j) * u, -0.55, 0.55); ctx.stroke();
      }
    }
    ctx.restore();
  }

  // ---------------- browser wrapper ----------------
  function create(canvas) {
    var ctx = canvas.getContext('2d'), state = initialState(), raf = 0, last = 0;

    function fit() {
      var dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
      var cw = Math.round((canvas.clientWidth || 0) * dpr), ch = Math.round((canvas.clientHeight || 0) * dpr);
      if (cw > 0 && ch > 0 && (canvas.width !== cw || canvas.height !== ch)) { canvas.width = cw; canvas.height = ch; }
      return canvas.width > 0 && canvas.height > 0;
    }
    function frame(now) {
      var dt = last ? (now - last) / 1000 : 0;
      last = now;
      state = step(state, Math.min(dt, 0.1), null, Math.random);
      if (fit()) draw(ctx, canvas.width, canvas.height, state);
      raf = requestAnimationFrame(frame);
    }
    return {
      setMood: function (m) { state.mood = normMood(m); },
      lookAt: function (x, y) { state.look = x === null || x === undefined ? null : normLook({ x: x, y: y }); },
      setMouth: function (open) { state.level = clamp(num(open, 0), 0, 1); },
      pulseMouth: function (strength) { state = applyInputs(state, { pulse: strength }); },
      start: function () { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } },
      stop: function () { if (raf) cancelAnimationFrame(raf); raf = 0; },
      snapshot: function () { return clone(state); }
    };
  }

  return { MOODS: MOODS.slice(), create: create, initialState: initialState, step: step, draw: draw };
})();
if (typeof module !== 'undefined') module.exports = Face;
