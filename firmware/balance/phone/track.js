// Tracking and follow control for the phone page: ports of follow/follow.swift's yellow and person modes.
// Pure functions with no DOM, so they can be tested off the phone.
//
// All sizes and offsets are converted to what the REFERENCE camera would see: the iPhone 1x lens, landscape 16:9,
// i.e. the Continuity Camera view all the tuning was done with. So the defaults keep their physical meaning
// (how close it stops, how hard it turns) whichever lens and orientation the page uses.
var Track = (function () {
  // Half-angle tangents of 16:9 iPhone video: 1x lens 0.749 (long side) / 0.421 (short side);
  // 0.5x ultra-wide 1.376 / 0.778. kx, ky = how much bigger things look than in the reference, horizontally / vertically.
  function geom(label, W, H) {
    var uw = /ultra ?wide/i.test(label || '');
    var lng = uw ? 1.376 : 0.749, sht = uw ? 0.778 : 0.421;
    var tx = W >= H ? lng : sht, ty = W >= H ? sht : lng;
    return { kx: 0.749 / tx, ky: 0.421 / ty, uw: uw };
  }

  // ---------------- yellow ----------------
  var GATE = 0.22, LOCK_HOLD = 0.7, ACQ_MIN = 0.045, KEEP_MIN = 0.025, MIN_CELLS = 6;
  var DEAD_X = 0.06, KWY = 2.5, VGAIN = 0.35, DEAD_R = 0.08, VBACK_Y = -0.15, WMAX_Y = 1.2, LOST_AFTER = 0.5;

  // 1 = bright yellow: value >= 0.45, saturation >= 0.5, hue 45-70 deg (same test as follow.swift)
  function yellowMask(d, total, mask) {
    for (var k = 0, i = 0; k < total; k++, i += 4) {
      var r = d[i], g = d[i + 1], b = d[i + 2], yes = 0;
      if (b < r && b < g) {
        var mx = r > g ? r : g, dd = mx - b;
        if (mx >= 115 && dd >= 0.5 * mx) {
          var hue = mx === r ? 60 * ((g - b) / dd) : 60 * ((b - r) / dd + 2);
          if (hue < 0) hue += 360;
          yes = hue >= 45 && hue <= 70 ? 1 : 0;
        }
      }
      mask[k] = yes;
    }
  }

  // connected blobs; cells up to 2 apart join, so one object split by glare stays one blob
  function blobs(mask, gw, gh) {
    var out = [], stack = [];
    for (var i = 0; i < gw * gh; i++) {
      if (mask[i] !== 1) continue;
      var b = { n: 0, sx: 0, sy: 0, minX: gw, maxX: -1, minY: gh, maxY: -1 };
      mask[i] = 2; stack.push(i);
      while (stack.length) {
        var j = stack.pop(), x = j % gw, y = (j - x) / gw;
        b.n++; b.sx += x; b.sy += y;
        if (x < b.minX) b.minX = x; if (x > b.maxX) b.maxX = x;
        if (y < b.minY) b.minY = y; if (y > b.maxY) b.maxY = y;
        for (var dy = -2; dy <= 2; dy++) {
          var ny = y + dy; if (ny < 0 || ny >= gh) continue;
          for (var dx = -2; dx <= 2; dx++) {
            var nx = x + dx; if (nx < 0 || nx >= gw) continue;
            var k = ny * gw + nx;
            if (mask[k] === 1) { mask[k] = 2; stack.push(k); }
          }
        }
      }
      if (b.n >= MIN_CELLS) out.push(b);
    }
    return out;
  }

  // step(rgba, gw, gh, now, o): o = { kx, ky, targetY (patch size to hold, bigger = closer, 0.35), vmax }
  function makeTracker() {
    var mask = null, cx = 0.5, cy = 0.5, s = 0, last = -1e9, seen = -1e9, v = 0, w = 0;
    return {
      step: function (rgba, gw, gh, now, o) {
        var total = gw * gh, area = Math.sqrt(o.kx * o.ky);
        if (!mask || mask.length !== total) mask = new Uint8Array(total);
        yellowMask(rgba, total, mask);
        var all = blobs(mask, gw, gh).map(function (b) {
          return { cx: (b.sx / b.n + 0.5) / gw, cy: (b.sy / b.n + 0.5) / gh, n: b.n,
                   size: Math.sqrt(b.n / total) / area,
                   box: { x: b.minX / gw, y: b.minY / gh, w: (b.maxX - b.minX + 1) / gw, h: (b.maxY - b.minY + 1) / gh } };
        });
        var t = null, how = '';
        if (now - last < LOCK_HOLD && s > 0) {            // locked: only a blob near the last target, with a similar size
          var best = null, bestScore = 1e9;
          all.forEach(function (b) {
            var dist = Math.hypot(b.cx - cx, b.cy - cy), ratio = b.size / s;
            if (dist > GATE || ratio < 0.45 || ratio > 2.2 || b.size < KEEP_MIN) return;
            var score = dist + 0.25 * Math.abs(Math.log(ratio));
            if (score < bestScore) { bestScore = score; best = b; }
          });
          if (best) { t = best; how = all.length > 1 ? 'locked, ignoring ' + (all.length - 1) + ' other' : 'locked'; }
        } else if (all.length) {                            // (re)acquire the biggest blob, if it's big enough
          var big = all.reduce(function (a, b) { return b.n > a.n ? b : a; });
          if (big.size >= ACQ_MIN) { t = big; how = 'acquired'; }
        }
        if (t) {
          cx = t.cx; cy = t.cy; s = t.size; last = now; seen = now;
          var ex = (t.cx - 0.5) / o.kx;                      // offset as the reference camera would see it
          var wc = Math.abs(ex) < DEAD_X ? 0 : -KWY * ex;    // yellow on the right -> turn right
          var ratio = o.targetY / Math.max(t.size, 0.01) - 1; // patch size ~ 1/distance: how many times too far
          var vc = Math.abs(ratio) < DEAD_R ? 0 : VGAIN * ratio;
          vc = Math.max(VBACK_Y, Math.min(o.vmax, vc)); wc = Math.max(-WMAX_Y, Math.min(WMAX_Y, wc));
          v = 0.6 * v + 0.4 * vc; w = 0.6 * w + 0.4 * wc;
        } else if (now - seen > LOST_AFTER) { v = 0; w = 0; }   // lost: stop and hold
        return { target: t, all: all, how: how, v: v, w: w, tooClose: false, lostFor: now - seen };
      }
    };
  }

  // ---------------- person ----------------
  // step(boxes, now, o): boxes = [{x, y, w, h}] normalized (top-left origin) from the person detector;
  // o = { kx, targetW (upper-body width to hold, reference units; bigger = closer, 0.45), vmax }
  function makePersonTracker() {
    var P_GATE = 0.25, P_HOLD = 1.0, DEAD_W = 0.03, KW = 2.0, KV = 1.2, VBACK = -0.10, WMAX = 1.0;
    var SEARCH_FOR = 2.0, SEARCH_W = 0.5;
    var tr = null, last = -1e9, seen = -1e9, v = 0, w = 0, lastEx = 0;
    return {
      step: function (boxes, now, o) {
        var all = boxes.map(function (b) { return { cx: b.x + b.w / 2, cy: b.y + b.h / 2, size: b.w / o.kx, box: b }; });
        var t = null, how = '';
        if (now - last < P_HOLD && tr) {                    // locked: nearest to where they were, similar size
          var best = null, bs = 1e9;
          all.forEach(function (b) {
            var d = Math.hypot(b.cx - tr.cx, b.cy - tr.cy), r = b.size / tr.size;
            if (d > P_GATE || r < 0.6 || r > 1.6) return;
            var sc = d + 0.3 * Math.abs(Math.log(r));
            if (sc < bs) { bs = sc; best = b; }
          });
          if (best) { t = best; how = all.length > 1 ? 'locked, ignoring ' + (all.length - 1) + ' other' : 'locked'; }
        } else if (all.length) {                            // acquire the closest (widest) person
          t = all.reduce(function (a, b) { return b.size > a.size ? b : a; }); how = 'acquired';
        }
        var tooClose = false;
        if (t) {
          tr = t; last = now; seen = now;
          var ex = (t.cx - 0.5) / o.kx; lastEx = ex;
          var wc = Math.abs(ex) < DEAD_X ? 0 : -KW * ex;     // person on the right -> turn right
          var eh = o.targetW - t.size;
          var vc = Math.abs(eh) < DEAD_W ? 0 : KV * eh;      // narrow in the picture -> drive closer
          if (t.size > Math.max(0.55, o.targetW + 0.15)) { vc = VBACK; tooClose = true; }   // much too close: back off
          vc = Math.max(VBACK, Math.min(o.vmax, vc)); wc = Math.max(-WMAX, Math.min(WMAX, wc));
          v = 0.6 * v + 0.4 * vc; w = 0.6 * w + 0.4 * wc;
        } else {
          var lost = now - seen;
          v = 0.6 * v; if (lost > LOST_AFTER) v = 0;        // can't see them: no driving forward or back
          if (lost > SEARCH_FOR) w = 0;                     // gave up: hold still
          else if (Math.abs(lastEx) > 0.15) w = 0.6 * w + 0.4 * (lastEx > 0 ? -SEARCH_W : SEARCH_W);   // left at the edge: turn that way
          else if (lost > LOST_AFTER) w = 0;
        }
        return { target: t, all: all, how: how, v: v, w: w, tooClose: tooClose, lostFor: now - seen };
      }
    };
  }

  return { geom: geom, yellowMask: yellowMask, blobs: blobs, makeTracker: makeTracker, makePersonTracker: makePersonTracker };
})();
