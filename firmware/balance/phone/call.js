// Miguel's side of the family video call (#118): two-way WebRTC between this page and the family app.
//
// The server starts and ends the call over the mic socket (server/app/speech/mic.py, app/family.py):
//   {type: 'call', call, on: true, by}   she said yes: show the caller, send our camera and mic
//   {type: 'call', call, on: false}      it ended (the app's End, or the caller left)
//   {type: 'rtc', call, sdp | candidate} the app's answer and ICE candidates
// and this page sends back, over the same socket:
//   {type: 'rtc', call, sdp | candidate} our offer and candidates (this page offers: after a reload it
//                                        just offers again, and the app answers the newest offer)
//   {type: 'hangup', call}               her End button: ends it for both
//
// The call uses the tracks the page already has (iOS Safari keeps one capture going): the camera
// stream that also feeds vision, and the mic stream that also feeds hearing (mic.js sends zeros while
// the call is on, so nothing said on the call reaches Miguel). A camera switch swaps the track in
// place (setVideoTrack). No STUN or TURN: on one Wi-Fi the phones reach each other directly.
//
// view(s) is the layout (pure; call.test.js): during a call the caller's video takes the face's place
// in the top half, her own camera is a round bubble in its corner (Loom-style, like the showcase
// video's narrator, PR #116), and a big End button sits in the bottom half. makeCall(deps) is the
// signaling, with the browser parts passed in, so the Node test runs it with a fake peer connection.
(function (root) {
  'use strict';

  // ---------- the layout (pure) ----------
  // s: { call: {call, by} | null, remote: the caller's video is playing, video: the caller sends video,
  //      self: her camera is there, state: the peer connection's state }
  // Connected without the caller's video (their page had no camera: opened over http, or the camera was
  // refused) is a working call, audio or not: it says so and shows the caller's initial, not "Connecting" forever.
  function view(s) {
    const c = s && s.call;
    if (!c) return { face: true, remote: false, self: false, end: false, initial: '', label: '' };
    const who = c.by || 'your family';
    const lost = s.state === 'failed' || s.state === 'disconnected';
    const noCamera = !lost && s.state === 'connected' && !s.video && !s.remote;
    return {
      face: false,                                           // the caller replaces the face
      remote: true,                                          // the box shows even while connecting
      self: !!s.self,                                        // her own bubble, only with a camera
      end: true,
      initial: noCamera ? who.trim().charAt(0).toUpperCase() : '',   // a big letter in place of their video
      label: lost ? 'Reconnecting to ' + who + '…' : s.remote ? who
        : noCamera ? who + ' · camera off' : 'Connecting to ' + who + '…',
    };
  }

  // ---------- the signaling ----------
  // deps: {
  //   createPeer(): an RTCPeerConnection (or a fake),
  //   send(msg): sends over the mic socket, false if it's down,
  //   tracks(): { video: MediaStreamTrack | null, audio: MediaStreamTrack | null, stream: MediaStream | null },
  //   onChange(state): { call, remote: MediaStream | null, video: it has a video track, playing, state } after every change,
  //   log(obj): optional }
  function makeCall(deps) {
    let call = null, pc = null, remote = null, playing = false, state = 'new', early = [], videoSender = null;
    const log = deps.log || (() => {});

    function changed() {
      const video = !!(remote && remote.getVideoTracks && remote.getVideoTracks().length);
      try { deps.onChange({ call, remote, video, playing, state }); } catch (e) {}
    }

    function close() {
      if (pc) {
        pc.onicecandidate = pc.ontrack = pc.onconnectionstatechange = null;
        try { pc.close(); } catch (e) {}
      }
      pc = null; remote = null; playing = false; state = 'new'; early = []; videoSender = null;
    }

    async function offer() {                                 // a fresh connection and offer for `call`
      close();
      const id = call.call, p = deps.createPeer();
      pc = p;
      const t = deps.tracks() || {};
      const stream = t.stream || null;
      // Our camera and mic if we have them; otherwise receive only, so she still sees and hears them.
      if (t.video) videoSender = p.addTrack(t.video, ...(stream ? [stream] : []));
      else p.addTransceiver('video', { direction: 'recvonly' });
      if (t.audio) p.addTrack(t.audio, ...(stream ? [stream] : []));
      else p.addTransceiver('audio', { direction: 'recvonly' });
      p.onicecandidate = e => {
        if (pc !== p || !e.candidate) return;
        const c = typeof e.candidate.toJSON === 'function' ? e.candidate.toJSON() : e.candidate;
        deps.send({ type: 'rtc', call: id, candidate: c });
      };
      p.ontrack = e => {
        if (pc !== p) return;
        remote = (e.streams && e.streams[0]) || remote || null;
        if (!remote && typeof MediaStream !== 'undefined') remote = new MediaStream();
        if (remote && e.track && remote.getTracks && !remote.getTracks().includes(e.track)) remote.addTrack(e.track);
        changed();
      };
      p.onconnectionstatechange = () => {
        if (pc !== p) return;
        state = p.connectionState;
        log({ event: 'call connection', call: id, state });
        changed();
      };
      try {
        const o = await p.createOffer();
        if (pc !== p) return;
        await p.setLocalDescription(o);
        if (pc !== p) return;
        deps.send({ type: 'rtc', call: id, sdp: { type: o.type, sdp: o.sdp } });
      } catch (e) { log({ event: 'call offer failed', error: String(e) }); }
      changed();
    }

    async function onAnswer(sdp) {
      const p = pc;
      if (!p || p.signalingState !== 'have-local-offer') return;   // a late or repeated answer
      try {
        await p.setRemoteDescription(sdp);
        const queued = early; early = [];
        for (const c of queued) await p.addIceCandidate(c).catch(() => {});
      } catch (e) { log({ event: 'call answer failed', error: String(e) }); }
    }

    function end(local) {
      if (!call) return;
      const id = call.call;
      if (local) deps.send({ type: 'hangup', call: id });
      close(); call = null;
      log({ event: 'call ended', call: id, by: local ? 'her End button' : 'the server' });
      changed();
    }

    return {
      // A message from the server (mic socket). Returns true if it was the call's.
      message(msg) {
        if (!msg || (msg.type !== 'call' && msg.type !== 'rtc')) return false;
        if (msg.type === 'call') {
          if (!msg.on) { if (call && msg.call === call.call) end(false); return true; }
          if (call && call.call === msg.call && pc && state !== 'failed' && state !== 'closed') return true;   // sent again after a reconnect
          if (call && call.call !== msg.call) close();
          call = { call: msg.call, by: msg.by || '' };
          log({ event: 'call started', call: msg.call });
          offer();
          return true;
        }
        if (!call || msg.call !== call.call) return true;   // setup for another call
        if (msg.sdp && msg.sdp.type === 'answer') onAnswer(msg.sdp);
        else if (msg.candidate && pc) {
          if (pc.remoteDescription) pc.addIceCandidate(msg.candidate).catch(() => {});
          else early.push(msg.candidate);
        }
        return true;
      },
      hangup() { end(true); },                               // her End button
      playing(on) { if (call && playing !== !!on) { playing = !!on; changed(); } },   // the caller's video started
      // The camera changed (front/back switch): send the new track without a new offer.
      setVideoTrack(track) {
        if (!videoSender || !track) return;
        try { const r = videoSender.replaceTrack(track); if (r && r.catch) r.catch(() => {}); } catch (e) {}
      },
      get active() { return !!call; },
      get call() { return call; },
    };
  }

  const api = { view, makeCall };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') root.CallKit = api;
})(typeof window !== 'undefined' ? window : globalThis);
