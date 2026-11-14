// Miguel's voice: plays pre-recorded lines and reports how open his mouth should be.
//
// Each clip ships with a loudness envelope (scripts/voice.mjs writes both), so the
// mouth follows the actual audio, frame by frame, without Web Audio analysis on the phone.

import envelopes from "./voice-envelopes.json";

export type LineId = keyof typeof envelopes;

interface Envelope {
  text: string;
  fps: number;
  levels: number[];
}

const clips = envelopes as Record<string, Envelope>;

let audio: HTMLAudioElement | null = null;
let current: Envelope | null = null;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((l) => l());
}

export function hasLine(id: string): id is LineId {
  return id in clips;
}

/** Start speaking a line. Must be called from a tap (iOS only plays audio after a user gesture). */
export function speak(id: LineId) {
  stopSpeaking();
  const clip = clips[id];
  if (!clip) return;
  const a = new Audio(`/family/voice/${id}.m4a`);
  a.preload = "auto";
  audio = a;
  current = clip;
  a.addEventListener("ended", () => {
    if (audio === a) {
      audio = null;
      current = null;
      notify();
    }
  });
  a.play().catch(() => {
    if (audio === a) {
      audio = null;
      current = null;
      notify();
    }
  });
  notify();
}

export function stopSpeaking() {
  if (audio) {
    audio.pause();
    audio = null;
    current = null;
    notify();
  }
}

/** How loud Miguel is right now, 0..1. Read every animation frame. */
export function voiceLevel(): number {
  if (!audio || !current || audio.paused) return 0;
  const i = Math.floor(audio.currentTime * current.fps);
  return current.levels[i] ?? 0;
}

export function isSpeaking(): boolean {
  return audio !== null && !audio.paused;
}

export function onVoiceChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
