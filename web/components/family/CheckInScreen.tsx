"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useDemoControls, useFamily, useFamilyActions, useLiveFrame } from "@/lib/family/store";
import type { RequestStatus } from "@/lib/family/types";
import { HoldToTalk } from "./HoldToTalk";
import { Margaret } from "./Margaret";
import { FaceBadge } from "./miguel/FaceBadge";
import { MiguelStage } from "./miguel/MiguelStage";
import { hasLine, speak } from "./miguel/voice";
import { PageTitle, PlainButton, QuietLink, StickerButton, TopBar } from "./ui";

function useElapsed(since: number | null) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (since === null) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [since]);
  if (since === null || now === 0) return "0:00";
  const s = Math.max(0, Math.floor((now - since) / 1000));
  return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;
}

export function CheckInScreen() {
  const s = useFamily();
  const actions = useFamilyActions();
  const mom = s.resident.short;
  const name = s.resident.name;
  const c = s.checkIn;
  const elapsed = useElapsed(c.phase === "live" ? c.startedAt : null);
  // Miguel's camera, as JPEG frames from the server (the no-WebRTC fallback). Null in the demo.
  const frame = useLiveFrame();
  // The real server relays her camera one way (no WebRTC, no voice clips yet): say so, and never show
  // the illustrated Margaret as if she were live. The demo keeps the full two-way story.
  const demo = useDemoControls() !== null;
  // The check-in request before you tapped "Ask" (undefined: none yet), so only this visit's error shows.
  const [askedFrom, setAskedFrom] = useState<RequestStatus | undefined | null>(null);
  const askRequest = s.requests.checkIn;
  const askError = askedFrom !== null && askRequest !== askedFrom && askRequest?.status === "error" ? askRequest.message : null;
  const [momTalking, setMomTalking] = useState(false);
  const router = useRouter();

  // She chats a little when you first connect.
  useEffect(() => {
    if (c.phase !== "live") return;
    const a = setTimeout(() => setMomTalking(true), 900);
    const b = setTimeout(() => setMomTalking(false), 3800);
    return () => {
      clearTimeout(a);
      clearTimeout(b);
    };
  }, [c.phase]);

  // Leaving the screen ends a live check-in or a pending ask.
  useEffect(() => () => {
    setAskedFrom(null);
    const phase = actions.getState().checkIn.phase;
    if (phase === "live" || phase === "asking" || phase === "declined") actions.endCheckIn();
  }, [actions]);

  if (c.phase === "live") {
    return (
      <main className="family-page">
        <TopBar right={<span className="fg-label">Check-in · {elapsed}</span>} />
        <div className="fg-rise relative mt-4 overflow-hidden rounded-[26px] border-[1.5px] border-ink shadow-[0_0_0_5px_#fffdf8,0_0_0_6.5px_rgba(42,38,48,0.14)]">
          {frame ? (
            // eslint-disable-next-line @next/next/no-img-element -- live frames from Miguel's camera
            <img src={frame} alt={`${name}, live through Miguel's camera`} className="block aspect-[3/4] w-full bg-ink object-cover" />
          ) : demo ? (
            <Margaret talking={momTalking} className="block h-auto w-full" />
          ) : (
            <div className="flex aspect-[3/4] w-full items-center justify-center bg-ink px-8 text-center" role="status">
              <span className="fg-label !text-[11px] !text-paper/80">Opening Miguel&rsquo;s camera…</span>
            </div>
          )}
          <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full bg-[#fffaf1]/90 px-3 py-1.5">
            <span className={`h-2 w-2 rounded-full ${frame || demo ? "bg-alarm" : "bg-ink-3"}`} />
            <span className="fg-label !text-ink">{frame || demo ? "Live · via Miguel" : "Connecting"}</span>
          </div>
          <div className="absolute bottom-3 right-3 rotate-[3deg]">
            <FaceBadge expression="happy" width={46} />
          </div>
        </div>
        {(frame || demo) && (
          <p className="fg-label mt-3 text-center !text-[10px] text-ink-3">
            Fig. 3 — {name}, {frame ? "through Miguel's camera" : "in her armchair at home"}
          </p>
        )}
        <div className="fg-rise-2 mt-6 space-y-3">
          {demo && <HoldToTalk who={mom} tone="sky" />}
          <PlainButton tone="paper" onClick={() => actions.endCheckIn()}>
            End check-in
          </PlainButton>
        </div>
        <p className="mt-5 text-center text-[13px] leading-relaxed text-ink-2">
          {demo ? (
            <>{mom} sees you on Miguel&rsquo;s screen. Nothing is recorded.</>
          ) : (
            <>
              You see {mom} through Miguel&rsquo;s camera; she can&rsquo;t see or hear you yet. To tell her something, use
              Ask Miguel on Home. Nothing is recorded.
            </>
          )}
        </p>
      </main>
    );
  }

  if (c.phase === "asking") {
    return (
      <main className="family-page">
        <TopBar />
        <div className="fg-rise -mx-5 mt-2">
          <MiguelStage className="h-[330px]" framing="full" pose={{ mode: "listening", concerned: false, carrying: false }} />
        </div>
        <PageTitle
          label="Check in"
          title={
            <>
              Asking {mom}
              <span className="fg-ellipsis">
                <span>.</span>
                <span>.</span>
                <span>.</span>
              </span>
            </>
          }
        >
          Miguel is saying: <span className="fg-display italic text-ink">“{name}, {s.viewer.name} would like to say hi. Is now a good time?”</span>
        </PageTitle>
        <div className="mt-8 flex justify-center">
          <QuietLink onClick={() => actions.endCheckIn()}>Never mind</QuietLink>
        </div>
      </main>
    );
  }

  if (c.phase === "declined") {
    return (
      <main className="family-page">
        <TopBar />
        <div className="fg-rise -mx-5 mt-2">
          <MiguelStage className="h-[300px]" pose={{ mode: "withMom", concerned: false, carrying: false }} />
        </div>
        <PageTitle label="Not right now" title={<>{mom}&rsquo;s resting at the moment.</>}>
          Miguel told her you stopped by. She can call you back from him whenever she likes.
        </PageTitle>
        <div className="fg-rise-2 mt-8 space-y-3">
          <PlainButton
            onClick={() => {
              actions.endCheckIn();
              router.push("/family/send?item=note");
            }}
          >
            Leave her a note instead
          </PlainButton>
          <PlainButton tone="paper" onClick={() => actions.endCheckIn()}>
            Okay
          </PlainButton>
        </div>
      </main>
    );
  }

  return (
    <main className="family-page">
      <TopBar />
      <PageTitle label="Check in" title={<>See {mom}, face to face.</>}>
        {demo
          ? "Miguel asks her first. If she says yes, you’ll see and hear her through his camera, and she’ll see you on his screen."
          : "Miguel asks her first. If she says yes, you’ll see her through his camera while you’re on this screen."}
      </PageTitle>
      <div className="fg-rise-2 -mx-5 mt-2">
        <MiguelStage className="h-[300px]" pose={{ mode: s.mode, concerned: false, carrying: false }} />
      </div>
      <div className="fg-rise-3 mt-6">
        <StickerButton
          tone="sky"
          glyph="checkIn"
          title={`Ask ${mom}`}
          subtitle="She can always say not now"
          tilt={-0.6}
          onClick={() => {
            setAskedFrom(s.requests.checkIn);
            actions.requestCheckIn();
            if (hasLine("asking")) speak("asking");
          }}
        />
      </div>
      {askError && (
        <p className="mt-5 text-center text-[14px] leading-snug text-alarm" role="status">
          {askError}
        </p>
      )}
      <p className="mt-6 text-center text-[13px] leading-relaxed text-ink-2">Miguel never connects without her yes.</p>
    </main>
  );
}
