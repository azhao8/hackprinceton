"use client";

import { useEffect, useRef, useState } from "react";

/** Press and hold to talk through Miguel. In the demo, nothing is recorded; it shows the flow. */
export function HoldToTalk({ who, tone = "ink" }: { who: string; tone?: "ink" | "alarm" | "sky" }) {
  const [phase, setPhase] = useState<"idle" | "talking" | "sent">("idle");
  const [seconds, setSeconds] = useState(0);
  const startedAt = useRef(0);

  useEffect(() => {
    if (phase !== "talking") return;
    const id = setInterval(() => setSeconds(Math.floor((performance.now() - startedAt.current) / 1000)), 250);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    if (phase !== "sent") return;
    const id = setTimeout(() => setPhase("idle"), 2600);
    return () => clearTimeout(id);
  }, [phase]);

  const bg = { ink: "bg-ink text-paper", alarm: "bg-alarm text-[#fffaf4]", sky: "bg-[#b5cbea] text-ink border-[1.5px] border-ink" }[tone];

  return (
    <button
      type="button"
      className={`relative flex h-16 w-full select-none items-center justify-center gap-3 overflow-visible rounded-2xl text-[17px] font-semibold transition active:scale-[0.99] ${bg}`}
      style={{ touchAction: "none", WebkitUserSelect: "none" }}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        startedAt.current = performance.now();
        setSeconds(0);
        setPhase("talking");
      }}
      onPointerUp={() => setPhase((p) => (p === "talking" ? "sent" : p))}
      onPointerCancel={() => setPhase("idle")}
      onContextMenu={(e) => e.preventDefault()}
    >
      {phase === "talking" && <span className="fg-talk-ring absolute inset-0 rounded-2xl border-2 border-current" aria-hidden />}
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
      </svg>
      {phase === "idle" && <span>Hold to talk to {who}</span>}
      {phase === "talking" && <span>Talking… 0:{seconds.toString().padStart(2, "0")} · let go to send</span>}
      {phase === "sent" && <span>Sent. Miguel is playing it for her.</span>}
    </button>
  );
}
