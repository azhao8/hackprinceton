// Tests for the family video call on Miguel's phone (#118, call.js): the layout switch and the signaling,
// with a fake RTCPeerConnection. Not the real WebRTC or the iPhone's camera.
// Run: node --test firmware/balance/phone/*.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { view, makeCall } = require('./call.js');

class FakePeer {
  constructor() {
    this.added = []; this.transceivers = []; this.remote = []; this.candidates = []; this.closed = false;
    this.signalingState = 'stable'; this.remoteDescription = null; this.connectionState = 'new';
  }
  addTrack(track, ...streams) { const s = { track, streams, replaced: [] }; s.replaceTrack = t => { s.replaced.push(t); return Promise.resolve(); }; this.added.push(s); return s; }
  addTransceiver(kind, init) { this.transceivers.push({ kind, ...init }); }
  async createOffer() { return { type: 'offer', sdp: 'v=0 offer' }; }
  async setLocalDescription(d) { this.local = d; this.signalingState = 'have-local-offer'; }
  async setRemoteDescription(d) { this.remoteDescription = d; this.signalingState = 'stable'; }
  async addIceCandidate(c) { this.candidates.push(c); }
  close() { this.closed = true; }
}

function phone({ video = 'cam', audio = 'mic' } = {}) {
  const sent = [], states = [], peers = [];
  const call = makeCall({
    createPeer: () => { const p = new FakePeer(); peers.push(p); return p; },
    send: m => { sent.push(m); return true; },
    tracks: () => ({ video, audio, stream: 'callStream' }),
    onChange: s => states.push(s),
  });
  return { call, sent, states, peers, last: () => states[states.length - 1] };
}
const tick = () => new Promise(r => setImmediate(r));
const START = { type: 'call', call: 'c4', on: true, by: 'Sarah' };

test('the layout: the face until a call, then the caller on top, her bubble and a big End button', () => {
  assert.deepEqual(view({ call: null }), { face: true, remote: false, self: false, end: false, label: '' });
  const connecting = view({ call: { call: 'c4', by: 'Sarah' }, remote: false, self: true, state: 'connecting' });
  assert.equal(connecting.face, false);
  assert.equal(connecting.remote, true);
  assert.equal(connecting.end, true);
  assert.equal(connecting.self, true);
  assert.equal(connecting.label, 'Connecting to Sarah…');
  assert.equal(view({ call: { call: 'c4', by: 'Sarah' }, remote: true, self: true, state: 'connected' }).label, 'Sarah');
  assert.equal(view({ call: { call: 'c4', by: 'Sarah' }, remote: true, self: false, state: 'failed' }).label, 'Reconnecting to Sarah…');
  assert.equal(view({ call: { call: 'c4', by: 'Sarah' }, remote: true, self: false }).self, false);   // no camera: no bubble
});

test('a call offers with her camera and mic, and the answer and candidates complete it', async () => {
  const p = phone();
  assert.equal(p.call.message(START), true);
  await tick();
  const pc = p.peers[0];
  assert.deepEqual(pc.added.map(s => s.track), ['cam', 'mic']);
  assert.deepEqual(pc.added[0].streams, ['callStream']);
  assert.deepEqual(p.sent[0], { type: 'rtc', call: 'c4', sdp: { type: 'offer', sdp: 'v=0 offer' } });
  pc.onicecandidate({ candidate: { toJSON: () => ({ candidate: 'mine' }) } });
  assert.deepEqual(p.sent[1], { type: 'rtc', call: 'c4', candidate: { candidate: 'mine' } });
  p.call.message({ type: 'rtc', call: 'c4', candidate: { candidate: 'early' } });   // before the answer: queued
  assert.deepEqual(pc.candidates, []);
  p.call.message({ type: 'rtc', call: 'c4', sdp: { type: 'answer', sdp: 'v=0 answer' } });
  await tick(); await tick();
  assert.equal(pc.remoteDescription.sdp, 'v=0 answer');
  p.call.message({ type: 'rtc', call: 'c4', candidate: { candidate: 'late' } });
  await tick();
  assert.deepEqual(pc.candidates.map(c => c.candidate), ['early', 'late']);
  p.call.message({ type: 'rtc', call: 'other', candidate: { candidate: 'stale' } });   // another call: ignored
  assert.equal(pc.candidates.length, 2);
  assert.equal(p.last().call.by, 'Sarah');
  assert.equal(p.call.active, true);
});

test('without a camera or mic she still sees and hears them (receive only)', async () => {
  const p = phone({ video: null, audio: null });
  p.call.message(START);
  await tick();
  assert.deepEqual(p.peers[0].transceivers, [{ kind: 'video', direction: 'recvonly' }, { kind: 'audio', direction: 'recvonly' }]);
});

test('her End button ends it for both; the server ending it ends it here', async () => {
  const p = phone();
  p.call.message(START);
  await tick();
  p.call.hangup();
  assert.deepEqual(p.sent[p.sent.length - 1], { type: 'hangup', call: 'c4' });
  assert.equal(p.peers[0].closed, true);
  assert.equal(p.call.active, false);
  assert.equal(p.last().call, null);
  assert.equal(view({ call: p.last().call }).face, true);       // the face comes back
  p.call.message({ type: 'call', call: 'c4', on: false });       // the server confirms: nothing more to do
  assert.equal(p.sent.filter(m => m.type === 'hangup').length, 1);

  const q = phone();
  q.call.message(START);
  await tick();
  q.call.message({ type: 'call', call: 'old', on: false });      // an older call's end: ignored
  assert.equal(q.call.active, true);
  q.call.message({ type: 'call', call: 'c4', on: false });       // the app's End
  assert.equal(q.call.active, false);
  assert.equal(q.peers[0].closed, true);
  assert.equal(q.sent.some(m => m.type === 'hangup'), false);    // not sent back
});

test('the call message again after a reconnect keeps the connection; a failed one offers again', async () => {
  const p = phone();
  p.call.message(START);
  await tick();
  p.call.message(START);
  await tick();
  assert.equal(p.peers.length, 1);
  p.peers[0].connectionState = 'failed';
  p.peers[0].onconnectionstatechange();
  p.call.message(START);
  await tick();
  assert.equal(p.peers.length, 2);
  assert.equal(p.peers[0].closed, true);
  assert.equal(p.sent.filter(m => m.sdp).length, 2);
});

test('a camera switch swaps the track in place, without a new offer', async () => {
  const p = phone();
  p.call.message(START);
  await tick();
  p.call.setVideoTrack('front cam');
  assert.deepEqual(p.peers[0].added[0].replaced, ['front cam']);
  assert.equal(p.sent.filter(m => m.sdp).length, 1);
});

test('other messages are not the call\'s', () => {
  const p = phone();
  assert.equal(p.call.message({ type: 'listen', on: true }), false);
  assert.equal(p.call.message({ type: 'say', id: 1, text: 'hi' }), false);
});
