// Miguel's ears: streams the phone's microphone to the server's /mic WebSocket (open question T-13).
//
// Mic.start(after) runs inside the Start tap: it creates the AudioContext there (iOS only lets audio
// start from a tap), waits for `after` (the camera's promise, so the two permission prompts don't
// overlap), then asks for the microphone separately from the camera. Audio is captured with an
// AudioWorklet (inline, from a Blob URL; ScriptProcessor if that fails), downsampled to 16 kHz mono
// s16le and sent as 40 ms binary frames to /mic?rate=16000 (wss on HTTPS). The server relays it to
// Cartesia speech to text (server/app/speech/mic.py).
//
// Half-duplex: while Miguel is talking (Voice.busy(), or Safari's speechSynthesis.speaking) and for
// 300 ms after, the frames are zeros: Cartesia wants an unbroken stream, and Miguel must not hear
// himself. The page also tells the server {"type":"voice","busy":...} so it knows when he spoke.
//
// window.onMicLevel(level, state), if set, gets the input level (0..1, RMS) about 25 times a second,
// with state = { sending, muted, connected }: a hook for the face to show "listening".
(function (root) {
  'use strict';

  const OUT_RATE = 16000, FRAME_MS = 40, TAIL_MS = 300;
  const FRAME_SAMPLES = OUT_RATE * FRAME_MS / 1000;           // 640 samples = 1280 bytes
  const MAX_BUFFERED = 64 * 1024;                             // bytes queued in the socket before we drop frames

  // ---------- pure helpers (also used by the Node test) ----------

  // Stateful downsampler: averages the input samples that fall in each output sample's slot (a box
  // low-pass, enough for speech) and keeps the leftover between calls, so any input block size works.
  function makeDownsampler(inRate, outRate) {
    const ratio = inRate / outRate;
    if (!(ratio >= 1)) throw new Error('can only downsample: ' + inRate + ' -> ' + outRate);
    let acc = 0, n = 0, t = 0, k = 1;                         // t: input samples seen; slot k ends at k * ratio
    return function (input) {                                 // Float32Array (-1..1) in, Int16Array out
      const out = new Int16Array(Math.floor((t + input.length) / ratio) - (k - 1) + 1);
      let o = 0;
      for (let i = 0; i < input.length; i++) {
        acc += input[i]; n++; t++;
        if (t >= k * ratio) { out[o++] = floatTo16(acc / n); acc = 0; n = 0; k++; }
      }
      return out.subarray(0, o);
    };
  }

  function floatTo16(x) {
    const s = x > 1 ? 1 : x < -1 ? -1 : x;
    return s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
  }

  function rms(input) {
    let s = 0;
    for (let i = 0; i < input.length; i++) s += input[i] * input[i];
    return input.length ? Math.sqrt(s / input.length) : 0;
  }

  // ---------- the browser part ----------

  const WORKLET = `
class MicTap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(1024); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i];
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor('mic-tap', MicTap);`;

  function makeMic() {
    let ctx = null, stream = null, src = null, node = null, sink = null, ws = null;
    let running = false, down = null, frame = new Int16Array(FRAME_SAMPLES), fill = 0;
    let quietUntil = 0, lastBusy = false, retry = 0, retryTimer = null, level = 0, frameLevel = 0, frameN = 0;

    function voiceBusy() {
      try {
        // `Voice` is the page's own module (index.html); a top-level const, so not on window
        if (typeof Voice !== 'undefined' && Voice && typeof Voice.busy === 'function') return !!Voice.busy();
      } catch (e) {}
      return typeof speechSynthesis !== 'undefined' && !!speechSynthesis.speaking;
    }

    function muted() {                                        // Miguel is talking, or just stopped
      const now = Date.now(), busy = voiceBusy();
      if (busy) quietUntil = now + TAIL_MS;
      if (busy !== lastBusy) {
        lastBusy = busy;
        sendJSON({ type: 'voice', busy });
      }
      return busy || now < quietUntil;
    }

    function sendJSON(obj) {
      if (ws && ws.readyState === 1) { try { ws.send(JSON.stringify(obj)); } catch (e) {} }
    }

    function connect() {
      if (!running) return;
      const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/mic?rate=' + OUT_RATE;
      let sock;
      try { sock = new WebSocket(url); } catch (e) { return reconnect(); }
      sock.binaryType = 'arraybuffer';
      sock.onopen = () => { retry = 0; lastBusy = !voiceBusy(); muted(); };   // re-announce the voice state
      sock.onclose = () => { if (ws === sock) { ws = null; reconnect(); } };
      sock.onerror = () => {};                                // onclose follows
      ws = sock;
    }

    function reconnect() {
      if (!running || retryTimer) return;
      const delay = Math.min(8000, 500 * Math.pow(2, retry++));
      retryTimer = setTimeout(() => { retryTimer = null; connect(); }, delay);
    }

    function onAudio(input) {                                 // Float32Array at ctx.sampleRate
      if (!running) return;
      level = rms(input);
      const pcm = down(input);
      const quiet = muted();
      for (let i = 0; i < pcm.length; i++) {
        frame[fill++] = quiet ? 0 : pcm[i];
        if (fill === FRAME_SAMPLES) {
          if (ws && ws.readyState === 1 && ws.bufferedAmount < MAX_BUFFERED) ws.send(frame.buffer);
          frame = new Int16Array(FRAME_SAMPLES); fill = 0;
          if (typeof root.onMicLevel === 'function') {
            try { root.onMicLevel(Math.min(1, level * 4), { sending: !quiet, muted: quiet, connected: !!ws && ws.readyState === 1 }); } catch (e) {}
          }
        }
      }
    }

    async function startCapture() {
      // The page sets the iOS audio session to 'playback' for Miguel's voice; capture needs
      // 'play-and-record' (else: "AudioSession category is not compatible with audio capture").
      try { if (navigator.audioSession) navigator.audioSession.type = 'play-and-record'; } catch (e) {}
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      if (!running) { stream.getTracks().forEach(t => t.stop()); return; }
      if (ctx.state !== 'running') { try { await ctx.resume(); } catch (e) {} }
      down = makeDownsampler(ctx.sampleRate, OUT_RATE);
      src = ctx.createMediaStreamSource(stream);
      sink = ctx.createGain(); sink.gain.value = 0;            // keeps the graph pulling, plays nothing
      sink.connect(ctx.destination);
      let worklet = false;
      if (ctx.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
        const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
        try {
          await ctx.audioWorklet.addModule(url);
          node = new AudioWorkletNode(ctx, 'mic-tap', { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
          node.port.onmessage = e => onAudio(e.data);
          worklet = true;
        } catch (e) { node = null; }
        finally { URL.revokeObjectURL(url); }
      }
      if (!worklet) {
        node = ctx.createScriptProcessor(2048, 1, 1);
        node.onaudioprocess = e => onAudio(e.inputBuffer.getChannelData(0));
      }
      src.connect(node); node.connect(sink);
      connect();
      return { rate: ctx.sampleRate, worklet };
    }

    return {
      // Call inside the Start tap. `after`: optional promise to wait for (the camera) before asking for the mic.
      start(after) {
        if (running) return Promise.resolve();
        running = true;
        const AC = root.AudioContext || root.webkitAudioContext;
        if (!AC || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          running = false;
          return Promise.resolve({ error: 'no microphone API on this page (needs HTTPS)' });
        }
        ctx = new AC();                                       // created in the tap: iOS lets it run
        ctx.resume().catch(() => {});
        ctx.onstatechange = () => { if (running && ctx && ctx.state !== 'running' && ctx.state !== 'closed') ctx.resume().catch(() => {}); };
        return Promise.resolve(after).catch(() => {}).then(startCapture).then(info => {
          if (info && typeof log === 'function') log({ event: 'mic on', rate: info.rate, worklet: info.worklet });
          return info;
        }, e => {
          running = false;
          const error = (e && e.name ? e.name + ': ' : '') + (e && e.message || e);
          if (typeof log === 'function') log({ event: 'mic error', error });
          return { error };
        });
      },
      stop() {
        running = false;
        if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
        if (ws) { const s = ws; ws = null; try { s.close(); } catch (e) {} }
        if (stream) stream.getTracks().forEach(t => t.stop());
        try { if (src) src.disconnect(); if (node) node.disconnect(); if (sink) sink.disconnect(); } catch (e) {}
        if (ctx) ctx.close().catch(() => {});
        ctx = stream = src = node = sink = null; fill = 0;
      },
      get running() { return running; },
      get connected() { return !!ws && ws.readyState === 1; },
      get level() { return level; },
    };
  }

  const api = { makeDownsampler, floatTo16, rms, OUT_RATE, FRAME_SAMPLES };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') { root.Mic = Object.assign(makeMic(), { _test: api }); }
})(typeof window !== 'undefined' ? window : globalThis);
