import { describe, expect, it, vi } from "vitest";
import { CallClient, type CallDeps, type CallView, type PeerLike } from "./call";
import type { RtcPayload } from "./wire";

// A stand-in for RTCPeerConnection: records what the call does with it.
class FakePeer implements PeerLike {
  signalingState = "stable";
  connectionState = "new";
  remoteDescription: unknown = null;
  onicecandidate: PeerLike["onicecandidate"] = null;
  ontrack: PeerLike["ontrack"] = null;
  onconnectionstatechange: PeerLike["onconnectionstatechange"] = null;
  added: string[] = [];
  candidates: Record<string, unknown>[] = [];
  closed = false;
  addTrack(track: MediaStreamTrack) {
    this.added.push(track.kind);
  }
  async setRemoteDescription(d: { type: "offer" | "answer"; sdp: string }) {
    this.remoteDescription = d;
    this.signalingState = "have-remote-offer";
  }
  async createAnswer() {
    return { type: "answer", sdp: "v=0 answer" };
  }
  async setLocalDescription() {
    this.signalingState = "stable";
  }
  async addIceCandidate(c: Record<string, unknown>) {
    this.candidates.push(c);
  }
  close() {
    this.closed = true;
  }
}

function track(kind: string) {
  return { kind, stop: vi.fn() } as unknown as MediaStreamTrack;
}

function media() {
  const tracks = [track("video"), track("audio")];
  return { getTracks: () => tracks } as unknown as MediaStream;
}

function setup(over: Partial<CallDeps> = {}) {
  const sent: RtcPayload[] = [];
  const views: CallView[] = [];
  const peers: FakePeer[] = [];
  const client = new CallClient({
    secure: true,
    getMedia: async () => media(),
    createPeer: () => {
      const p = new FakePeer();
      peers.push(p);
      return p;
    },
    send: (p) => sent.push(p),
    onChange: (v) => views.push(v),
    ...over,
  });
  return { client, sent, views, peers };
}

const OFFER: RtcPayload = { sdp: { type: "offer", sdp: "v=0 offer" } };
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("CallClient (the family side of the check-in call, #118)", () => {
  it("answers the phone's offer with your camera and mic, then trades candidates", async () => {
    const { client, sent, peers, views } = setup();
    const answered = client.handle(OFFER);
    await client.handle({ candidate: { candidate: "early" } }); // while it answers: kept until the answer is set
    await answered;
    const pc = peers[0];
    expect(pc.added).toEqual(["video", "audio"]);
    expect(sent[0]).toEqual({ sdp: { type: "answer", sdp: "v=0 answer" } });
    expect(pc.candidates).toEqual([{ candidate: "early" }]);
    await client.handle({ candidate: { candidate: "late" } });
    expect(pc.candidates.at(-1)).toEqual({ candidate: "late" });
    pc.onicecandidate?.({ candidate: { toJSON: () => ({ candidate: "mine" }) } });
    expect(sent.at(-1)).toEqual({ candidate: { candidate: "mine" } });
    expect(views.at(-1)?.media).toBe("on");
  });

  it("a newer offer (the phone page reloaded) replaces the connection", async () => {
    const { client, sent, peers } = setup();
    await client.handle(OFFER);
    await client.handle(OFFER);
    expect(peers).toHaveLength(2);
    expect(peers[0].closed).toBe(true);
    expect(sent.filter((m) => "sdp" in m)).toHaveLength(2);
  });

  it("without a camera (refused, or a page that isn't https) it still answers, receive only", async () => {
    const denied = setup({ getMedia: () => Promise.reject(new Error("NotAllowedError")) });
    await denied.client.handle(OFFER);
    expect(denied.peers[0].added).toEqual([]);
    expect(denied.sent[0]).toEqual({ sdp: { type: "answer", sdp: "v=0 answer" } });
    expect(denied.client.view().media).toBe("denied");

    const getMedia = vi.fn();
    const insecure = setup({ secure: false, getMedia });
    await insecure.client.handle(OFFER);
    expect(getMedia).not.toHaveBeenCalled();
    expect(insecure.sent).toHaveLength(1);
    expect(insecure.client.view().media).toBe("insecure");
  });

  it("ending it stops your camera and mic and closes the connection", async () => {
    const m = media();
    const { client, peers, sent } = setup({ getMedia: async () => m });
    await client.handle(OFFER);
    client.close();
    expect(peers[0].closed).toBe(true);
    m.getTracks().forEach((t) => expect(t.stop).toHaveBeenCalled());
    await client.handle(OFFER); // anything after: ignored
    expect(peers).toHaveLength(1);
    expect(sent).toHaveLength(1);
  });

  it("a camera that arrives after the call ended is turned off at once", async () => {
    let give: (s: MediaStream) => void = () => {};
    const m = media();
    const { client } = setup({ getMedia: () => new Promise<MediaStream>((r) => (give = r)) });
    client.close();
    give(m);
    await flush();
    m.getTracks().forEach((t) => expect(t.stop).toHaveBeenCalled());
  });
});
