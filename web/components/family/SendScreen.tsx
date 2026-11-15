"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useDemoControls, useFamily, useFamilyActions } from "@/lib/family/store";
import type { Delivery, DeliveryStage, ItemKind } from "@/lib/family/types";
import { Glyph, type GlyphName } from "./Glyph";
import { MiguelStage } from "./miguel/MiguelStage";
import { hasLine, speak } from "./miguel/voice";
import { PageTitle, PlainButton, QuietLink, SectionLabel, TopBar } from "./ui";

interface Choice {
  item: ItemKind;
  glyph: GlyphName;
  name: string;
  hint: string;
  tone: string;
  tilt: number;
}

const CHOICES: Choice[] = [
  { item: "water", glyph: "water", name: "Water", hint: "A fresh glass from his station", tone: "#d6e3f4", tilt: -1.2 },
  { item: "medication", glyph: "medication", name: "Medication", hint: "Her next dose, from her pill box", tone: "#f8dccb", tilt: 1 },
  { item: "note", glyph: "note", name: "A note", hint: "Miguel reads it to her", tone: "#fbe6ad", tilt: 0.8 },
  { item: "other", glyph: "parcel", name: "Something else", hint: "Whatever goes on his tray", tone: "#ebe1cf", tilt: -0.9 },
];

const QUICK = ["Love you, Mom", "Drink up!", "Thinking of you", "See you Sunday"];

const STEPS: { stage: DeliveryStage; text: string }[] = [
  { stage: "sent", text: "Miguel heads to his station" },
  { stage: "loading", text: "It goes on his tray" },
  { stage: "onTheWay", text: "Miguel brings it to her" },
  { stage: "delivered", text: "She has it" },
];

function useVoiceNote() {
  const [supported, setSupported] = useState(false);
  const [recording, setRecording] = useState(false);
  const [clip, setClip] = useState<{ url: string; seconds: number } | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const started = useRef(0);

  useEffect(() => {
    const ok = typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
    const id = setTimeout(() => setSupported(ok), 0);
    return () => clearTimeout(id);
  }, []);

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const r = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: r.mimeType });
        setClip({ url: URL.createObjectURL(blob), seconds: Math.max(1, Math.round((performance.now() - started.current) / 1000)) });
      };
      rec.current = r;
      started.current = performance.now();
      r.start();
      setRecording(true);
    } catch {
      setSupported(false);
    }
  };
  const stop = () => {
    rec.current?.stop();
    rec.current = null;
    setRecording(false);
  };
  return { supported, recording, clip, start, stop, clear: () => setClip(null) };
}

/** When a send didn't go through, or a delivery failed: say so plainly, with the reason. */
function SendProblem({
  band,
  title,
  detail,
  mom,
  onRetry,
}: {
  band: string;
  title: ReactNode;
  detail?: string;
  mom: string;
  onRetry: () => void;
}) {
  return (
    <main className="family-page">
      <TopBar />
      <div className="fg-rise -mx-5 mt-2">
        <MiguelStage className="h-[260px]" pose={{ mode: "withMom", concerned: true, carrying: false }} />
      </div>
      <div className="fg-rise mt-4 inline-flex items-center gap-2.5 rounded-full bg-alarm-soft px-3.5 py-2" role="status">
        <span className="h-2.5 w-2.5 rounded-full bg-alarm" aria-hidden />
        <span className="fg-label !text-alarm !tracking-[0.14em]">{band}</span>
      </div>
      <PageTitle title={title}>{detail && <span className="text-ink">{detail}</span>}</PageTitle>
      <div className="fg-rise-2 mt-8">
        <PlainButton onClick={onRetry}>Try again</PlainButton>
      </div>
      <div className="mt-8 flex justify-center">
        <QuietLink href="/family">Back to {mom}&rsquo;s day</QuietLink>
      </div>
    </main>
  );
}

export function SendScreen() {
  const s = useFamily();
  const actions = useFamilyActions();
  const demo = useDemoControls();
  const [choice, setChoice] = useState<Choice | null>(null);
  const [what, setWhat] = useState("");
  const [message, setMessage] = useState("");
  const [sentId, setSentId] = useState<string | null>(null);
  const [seen, setSeen] = useState<Delivery | null>(null);
  const voice = useVoiceNote();
  const mom = s.resident.short;

  // Pages stay mounted (hidden) after you leave; start fresh next time.
  useEffect(
    () => () => {
      setSentId(null);
      setSeen(null);
      setChoice(null);
      setMessage("");
      setWhat("");
    },
    [],
  );

  // Preselect from ?item= (e.g. "Leave a note instead" on the check-in screen).
  useEffect(() => {
    const item = new URLSearchParams(window.location.search).get("item");
    const c = CHOICES.find((x) => x.item === item);
    if (!c) return;
    const id = setTimeout(() => setChoice(c), 0);
    return () => clearTimeout(id);
  }, []);

  const label = choice ? (choice.item === "other" ? what.trim() || "Something" : choice.item === "note" ? "Your note" : choice.name) : "";
  const canSend = !!choice && (choice.item !== "other" || what.trim().length > 0) && (choice.item !== "note" || message.trim().length > 0 || !!voice.clip);

  const send = () => {
    if (!choice || !canSend) return;
    actions.send({ item: choice.item, label, message: message.trim() || undefined, voiceNote: !!voice.clip });
    if (hasLine("onIt")) speak("onIt");
    setSentId(label);
  };

  // Follow the delivery this send created (its id comes back with the request); keep the last
  // copy seen, since the source may clear `delivery` once it's done or failed.
  const request = s.requests.send;
  const mine = s.delivery && request?.id && s.delivery.id === request.id ? s.delivery : null;
  if (mine && mine !== seen) setSeen(mine);
  const delivery = mine ?? (seen && seen.id === request?.id ? seen : null);

  if (sentId && request?.status === "error") {
    return (
      <SendProblem band="Not sent" title={<>Miguel can&rsquo;t take this one right now.</>} detail={request.message} mom={mom} onRetry={() => setSentId(null)} />
    );
  }

  if (sentId && delivery?.stage === "failed") {
    return (
      <SendProblem
        band="Not delivered"
        title={<>{sentId} didn&rsquo;t reach {mom}.</>}
        detail={delivery.detail || "Miguel couldn't finish this delivery."}
        mom={mom}
        onRetry={() => setSentId(null)}
      />
    );
  }

  if (sentId) {
    // Until the source says where it is, it's at the first step.
    const stageIndex = delivery ? STEPS.findIndex((x) => x.stage === delivery.stage) : 0;
    return (
      <main className="family-page">
        <TopBar />
        <div className="fg-rise -mx-5 mt-2">
          <MiguelStage
            className="h-[300px]"
            pose={{ mode: s.mode, concerned: false, carrying: s.mode === "delivering" }}
            onTap={() => hasLine("onIt") && speak("onIt")}
          />
        </div>
        <PageTitle label="On its way" title={<>{sentId} for {mom}.</>}>
          Miguel will hand it to her{message.trim() ? <> and say, <span className="fg-display italic text-ink">“{message.trim()}”</span></> : null}.
        </PageTitle>
        <ol className="fg-rise-2 mt-7 space-y-3.5">
          {STEPS.map((step, i) => {
            const done = i < stageIndex || (i === stageIndex && step.stage === "delivered");
            const now = i === stageIndex && step.stage !== "delivered";
            return (
              <li key={step.stage} className="flex items-center gap-3">
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full border-[1.5px] border-ink text-[11px] ${
                    done ? "bg-ink text-paper" : now ? "bg-sun" : "bg-transparent"
                  }`}
                  aria-hidden
                >
                  {done ? "✓" : i + 1}
                </span>
                <span className={`text-[15.5px] ${i > stageIndex ? "text-ink-3" : "text-ink"} ${now ? "font-semibold" : ""}`}>
                  {step.text}
                  {now && <span className="fg-ellipsis ml-0.5"><span>.</span><span>.</span><span>.</span></span>}
                </span>
              </li>
            );
          })}
        </ol>
        {delivery?.stage === "delivered" && delivery.photo && (
          <figure className="fg-rise mt-7">
            {/* eslint-disable-next-line @next/next/no-img-element -- a photo from Miguel's server, not a page asset */}
            <img src={delivery.photo} alt={`${mom} with the ${delivery.label.toLowerCase()}`} className="w-full rounded-[22px] border-[1.5px] border-ink object-cover" />
            <figcaption className="fg-label mt-2 text-center !text-[10px] text-ink-3">Taken by Miguel as he handed it over</figcaption>
          </figure>
        )}
        <div className="mt-10 flex justify-center">
          <QuietLink href="/family">Back to {mom}&rsquo;s day</QuietLink>
        </div>
      </main>
    );
  }

  return (
    <main className="family-page">
      <TopBar />
      <PageTitle label="Send something" title={<>What should Miguel bring {mom}?</>} />

      <div className="fg-rise-2 mt-7 grid grid-cols-2 gap-4" role="radiogroup" aria-label="What to send">
        {CHOICES.map((c) => {
          const on = choice?.item === c.item;
          return (
            <button
              key={c.item}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => setChoice(c)}
              className={`relative flex min-h-[148px] flex-col items-start rounded-[20px] border-[1.5px] p-4 text-left transition duration-200 active:scale-[0.97] ${
                on ? "border-ink shadow-[0_0_0_4px_#fffdf8,0_0_0_5.5px_#2a2630]" : "border-sand bg-[#fffaf1]"
              }`}
              style={{ background: on ? c.tone : undefined, transform: on ? `rotate(${c.tilt}deg)` : undefined }}
            >
              <Glyph name={c.glyph} size={54} diecut />
              <span className="fg-display mt-auto pt-3 text-[20px] font-[560] leading-none">{c.name}</span>
              <span className="mt-1.5 text-[12.5px] leading-snug text-ink-2">{c.hint}</span>
            </button>
          );
        })}
      </div>

      {choice && (
        <div className="fg-rise mt-9 space-y-7">
          {choice.item === "other" && (
            <label className="block">
              <span className="fg-label">What is it?</span>
              <input
                value={what}
                onChange={(e) => setWhat(e.target.value)}
                placeholder="Her reading glasses"
                className="mt-2 h-13 w-full rounded-2xl border-[1.5px] border-sand bg-[#fffaf1] px-4 py-3.5 text-[16px] outline-none placeholder:text-ink-3 focus:border-ink"
              />
            </label>
          )}

          <div>
            <SectionLabel>{choice.item === "note" ? "Your note" : "A few words (optional)"}</SectionLabel>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={2}
              placeholder={`Miguel says it as he hands it to ${mom}`}
              className="mt-3 w-full resize-none rounded-2xl border-[1.5px] border-sand bg-[#fffaf1] px-4 py-3.5 text-[16px] leading-snug outline-none placeholder:text-ink-3 focus:border-ink"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              {QUICK.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setMessage(q)}
                  className={`rounded-full border-[1.5px] px-3 py-1.5 text-[13px] transition active:scale-95 ${
                    message === q ? "border-ink bg-sun-soft" : "border-sand bg-transparent text-ink-2"
                  }`}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>

          {/* Voice notes need an upload to the server first (POST /family/media), not wired up yet: demo only. */}
          {voice.supported && demo && (
            <div>
              {voice.clip ? (
                <div className="flex items-center gap-3 rounded-2xl border-[1.5px] border-sand bg-[#fffaf1] px-4 py-3">
                  <Glyph name="message" size={28} />
                  <audio src={voice.clip.url} controls className="h-9 min-w-0 flex-1" />
                  <button type="button" onClick={voice.clear} className="fg-label !text-ink underline underline-offset-4">
                    Remove
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onPointerDown={(e) => {
                    e.currentTarget.setPointerCapture(e.pointerId);
                    voice.start();
                  }}
                  onPointerUp={voice.stop}
                  onPointerCancel={voice.stop}
                  onContextMenu={(e) => e.preventDefault()}
                  style={{ touchAction: "none" }}
                  className={`flex h-12 w-full items-center justify-center gap-2 rounded-2xl border-[1.5px] border-dashed text-[14.5px] transition ${
                    voice.recording ? "border-ember bg-ember-soft text-ink" : "border-sand text-ink-2"
                  }`}
                >
                  <Glyph name="message" size={24} />
                  {voice.recording ? "Recording… let go when you're done" : "Or hold to record a voice note"}
                </button>
              )}
            </div>
          )}

          <p className="text-[14px] leading-relaxed text-ink-2">
            Miguel picks it up from his station, finds {mom} wherever she is at home, and hands it to her. Usually about five minutes.
          </p>

          <PlainButton onClick={send} disabled={!canSend}>
            Send with Miguel
          </PlainButton>
        </div>
      )}
    </main>
  );
}
