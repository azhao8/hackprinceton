"use client";

// The check-in video call's pieces for the live screen (#118): the call itself (useVideoCall), a
// video element for a MediaStream, and your own camera as a round bubble in the corner, Loom-style
// (like Miguel's narrator bubble in the showcase video, PR #116), with an amber ring that glows while
// you talk.

import { useEffect, useRef, useState } from "react";
import { CallClient, browserCallDeps, type CallView } from "@/lib/family/call";
import { useFamilyActions } from "@/lib/family/store";

/** The live call for check-in `call` (null: none). Null until the call has something to show. */
export function useVideoCall(call: string | null): CallView | null {
  const source = useFamilyActions();
  const [shown, setShown] = useState<{ call: string; view: CallView } | null>(null);
  useEffect(() => {
    if (!call) return;
    const client = new CallClient({
      ...browserCallDeps(),
      send: (p) => source.sendRtc({ call, ...p }),
      onChange: (view) => setShown({ call, view }),
      log: (what, detail) => console.warn(`check-in call: ${what}`, detail),
    });
    const off = source.subscribeRtc((m) => {
      if (m.call === call) void client.handle(m);
    });
    return () => {
      off();
      client.close();
    };
  }, [call, source]);
  return shown && shown.call === call ? shown.view : null;
}

/** A MediaStream in a <video>. `muted` for your own camera (no echo); `onPlaying` when frames show. */
export function StreamVideo({
  stream,
  muted = false,
  mirror = false,
  className,
  label,
  onPlaying,
  onBlocked,
}: {
  stream: MediaStream | null;
  muted?: boolean;
  mirror?: boolean;
  className?: string;
  label: string;
  onPlaying?: () => void;
  /** The browser wouldn't start the sound without a tap. */
  onBlocked?: () => void;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const blocked = useRef(onBlocked);
  useEffect(() => {
    blocked.current = onBlocked;
  }, [onBlocked]);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (v.srcObject !== stream) v.srcObject = stream;
    if (stream) v.play().catch(() => blocked.current?.());
  }, [stream]);
  return (
    <video
      ref={ref}
      aria-label={label}
      autoPlay
      playsInline
      muted={muted}
      onPlaying={onPlaying}
      className={className}
      style={mirror ? { transform: "scaleX(-1)" } : undefined}
    />
  );
}

/** Your camera, round, in the corner; the ring follows your mic's loudness. */
export function SelfBubble({ stream, className = "" }: { stream: MediaStream; className?: string }) {
  const ring = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ring.current;
    if (!el || !stream.getAudioTracks().length) return;
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    let raf = 0;
    let level = 0;
    const ctx = new AC();
    const an = ctx.createAnalyser();
    an.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(an); // to the analyser only: you don't hear yourself
    ctx.resume().catch(() => {});
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let s = 0;
      for (const b of buf) s += ((b - 128) / 128) ** 2;
      level = Math.max(Math.min(1, Math.sqrt(s / buf.length) * 6), level * 0.85);
      el.style.borderColor = `rgba(240, 178, 90, ${(0.15 + 0.7 * level).toFixed(2)})`;
      el.style.boxShadow = `0 0 ${Math.round(10 + 20 * level)}px rgba(240, 178, 90, ${(0.3 * level).toFixed(2)})`;
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      ctx.close().catch(() => {});
    };
  }, [stream]);
  return (
    <div className={`relative h-[96px] w-[96px] ${className}`}>
      <div ref={ring} className="absolute -inset-[7px] rounded-full border-[3px] border-[rgba(240,178,90,0.15)]" />
      <div className="absolute inset-0 overflow-hidden rounded-full bg-[#f3e9d8] shadow-[0_0_0_4px_#f4ecdd,0_10px_26px_rgba(0,0,0,0.5)]">
        <StreamVideo stream={stream} muted mirror label="You" className="block h-full w-full object-cover" />
      </div>
    </div>
  );
}
