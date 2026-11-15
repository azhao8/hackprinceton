// The family side of the check-in video call (#118): two-way WebRTC with Miguel's phone.
//
// Miguel's phone offers (firmware/balance/phone/call.js) as soon as she says yes; the server relays
// the setup through the family socket (`rtc` messages, contract/web/family.md), and only to whoever
// asked, only while the check-in is live. This side answers: it asks for the camera and mic once,
// answers every offer (a newer offer means the phone page reloaded, so the old connection goes), and
// sends its ICE candidates back. Without a camera or mic (denied, or a page that isn't https) it still
// answers, receive only, so you see and hear her anyway.
//
// The browser parts are passed in, so the tests run it with a fake peer connection.

import type { RtcPayload } from "./wire";

/** What the screen shows. `media`: your own camera and mic: asking, on, or why not. */
export interface CallView {
  remote: MediaStream | null;
  local: MediaStream | null;
  media: "asking" | "on" | "denied" | "insecure";
  /** The peer connection's state ("new", "connecting", "connected", "disconnected", "failed", "closed"). */
  state: string;
}

/** The parts of RTCPeerConnection the call uses. */
export interface PeerLike {
  signalingState: string;
  connectionState: string;
  remoteDescription: unknown;
  onicecandidate: ((e: { candidate: { toJSON?: () => unknown } | null }) => void) | null;
  ontrack: ((e: { track: MediaStreamTrack; streams: readonly MediaStream[] }) => void) | null;
  onconnectionstatechange: (() => void) | null;
  addTrack(track: MediaStreamTrack, ...streams: MediaStream[]): unknown;
  setRemoteDescription(d: { type: "offer" | "answer"; sdp: string }): Promise<void>;
  createAnswer(): Promise<{ type: string; sdp?: string }>;
  setLocalDescription(d: { type: string; sdp?: string }): Promise<void>;
  addIceCandidate(c: Record<string, unknown>): Promise<void>;
  close(): void;
}

export interface CallDeps {
  send(payload: RtcPayload): void;
  createPeer(): PeerLike;
  /** Your camera and mic. Rejects (or resolves null) when there are none. */
  getMedia(): Promise<MediaStream | null>;
  /** True on https or localhost: browsers only give camera and mic there. */
  secure: boolean;
  onChange(view: CallView): void;
  log?(what: string, detail?: unknown): void;
}

export class CallClient {
  private pc: PeerLike | null = null;
  private remote: MediaStream | null = null;
  private local: MediaStream | null = null;
  private media: CallView["media"];
  private mediaReady: Promise<MediaStream | null>;
  private early: Record<string, unknown>[] = [];
  private gen = 0;
  private closed = false;

  constructor(private deps: CallDeps) {
    this.media = deps.secure ? "asking" : "insecure";
    this.mediaReady = deps.secure
      ? deps.getMedia().then(
          (s) => {
            if (this.closed) {
              s?.getTracks().forEach((t) => t.stop());
              return null;
            }
            this.local = s;
            this.media = s ? "on" : "denied";
            this.changed();
            return s;
          },
          (e) => {
            this.media = "denied";
            this.deps.log?.("camera or mic refused", e);
            this.changed();
            return null;
          },
        )
      : Promise.resolve(null);
  }

  view(): CallView {
    return { remote: this.remote, local: this.local, media: this.media, state: this.pc?.connectionState ?? "new" };
  }

  /** One `rtc` message from the server (the phone's offer or a candidate). */
  async handle(m: RtcPayload): Promise<void> {
    if (this.closed) return;
    if ("sdp" in m) {
      if (m.sdp.type === "offer") await this.answer({ type: "offer", sdp: m.sdp.sdp });
      return;
    }
    const pc = this.pc;
    if (pc && pc.remoteDescription) await pc.addIceCandidate(m.candidate).catch(() => {});
    else this.early.push(m.candidate);
  }

  /** Hang up here: stop the camera and mic and close the connection (the server's `end` tells the phone). */
  close() {
    this.closed = true;
    this.gen += 1;
    this.drop();
    this.local?.getTracks().forEach((t) => t.stop());
    this.local = null;
  }

  private async answer(offer: { type: "offer"; sdp: string }) {
    const gen = ++this.gen;
    this.drop();
    const pc = this.deps.createPeer();
    this.pc = pc;
    pc.onicecandidate = (e) => {
      if (this.pc !== pc || !e.candidate) return;
      const c = typeof e.candidate.toJSON === "function" ? e.candidate.toJSON() : e.candidate;
      this.deps.send({ candidate: c as Record<string, unknown> });
    };
    pc.ontrack = (e) => {
      if (this.pc !== pc) return;
      const stream = e.streams[0] ?? this.remote ?? new MediaStream();
      if (!stream.getTracks().includes(e.track)) stream.addTrack(e.track);
      this.remote = stream;
      this.changed();
    };
    pc.onconnectionstatechange = () => {
      if (this.pc === pc) this.changed();
    };
    try {
      await pc.setRemoteDescription(offer);
      const local = await this.mediaReady; // the first offer may beat your "Allow" tap
      if (gen !== this.gen) return;
      // Added after the offer, so they ride on the phone's transceivers (send and receive both ways).
      local?.getTracks().forEach((t) => pc.addTrack(t, local));
      const answer = await pc.createAnswer();
      if (gen !== this.gen) return;
      await pc.setLocalDescription(answer);
      if (gen !== this.gen) return;
      this.deps.send({ sdp: { type: "answer", sdp: answer.sdp ?? "" } });
      const queued = this.early;
      this.early = [];
      for (const c of queued) await pc.addIceCandidate(c).catch(() => {});
    } catch (e) {
      this.deps.log?.("answering the call failed", e);
    }
    this.changed();
  }

  private drop() {
    const pc = this.pc;
    if (pc) {
      pc.onicecandidate = pc.ontrack = pc.onconnectionstatechange = null;
      try {
        pc.close();
      } catch {
        // already closed
      }
    }
    this.pc = null;
    this.remote = null;
    this.early = [];
  }

  private changed() {
    if (!this.closed) this.deps.onChange(this.view());
  }
}

/** The browser's own parts: camera and mic, a real peer connection (no STUN/TURN: one Wi-Fi). */
export function browserCallDeps(): Pick<CallDeps, "createPeer" | "getMedia" | "secure"> {
  const secure = typeof window !== "undefined" && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;
  return {
    secure,
    createPeer: () => new RTCPeerConnection({ iceServers: [] }) as unknown as PeerLike,
    getMedia: () =>
      navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      }),
  };
}
