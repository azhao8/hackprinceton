"use client";

import Link from "next/link";
import { useRef } from "react";
import { clockLabel, partOfDay } from "@/lib/family/format";
import { useFamily, useDemoMinutes } from "@/lib/family/store";
import type { Delivery, FamilyState } from "@/lib/family/types";
import { openDemoPanel } from "./DemoPanel";
import { Glyph } from "./Glyph";
import { EVENT_GLYPH } from "./meta";
import { MiguelStage } from "./miguel/MiguelStage";
import { hasLine, speak, type LineId } from "./miguel/voice";
import { QuietLink, SectionLabel, StatusNote, StickerButton } from "./ui";

function headline(s: FamilyState, minutes: number | null): string {
  const part = minutes === null ? "afternoon" : partOfDay(minutes);
  switch (s.mode) {
    case "delivering":
      return `Miguel's bringing ${s.resident.short} ${s.delivery ? s.delivery.label.toLowerCase() : "something"}.`;
    case "charging":
      return `${s.resident.short}'s resting. Miguel's charging nearby.`;
    case "listening":
      return `${s.resident.short}'s telling Miguel something.`;
    case "nightLight":
      return "Up in the night, with a little light.";
    case "idle":
      return `${s.resident.short}'s out for a bit. Miguel's waiting in her room.`;
    case "offline":
      return "Miguel's lost his connection for a moment.";
    default:
      return part === "night" ? `${s.resident.short}'s sleeping soundly.` : `${s.resident.short}'s having a calm ${part}.`;
  }
}

const STAGES: Delivery["stage"][] = ["sent", "loading", "onTheWay", "delivered"];
const STAGE_TEXT: Record<Delivery["stage"], string> = {
  sent: "Sent to the front desk",
  loading: "Lin is putting it on the tray",
  onTheWay: "Miguel is on his way to her",
  delivered: "Delivered. She has it.",
};

function DeliveryStrip({ delivery, name }: { delivery: Delivery; name: string }) {
  const at = STAGES.indexOf(delivery.stage);
  return (
    <div className="fg-rise mt-6 flex items-center gap-3 rounded-2xl border-[1.5px] border-ink bg-[#fffaf1] px-4 py-3">
      <Glyph name={delivery.item === "water" ? "water" : delivery.item === "medication" ? "medication" : delivery.item === "note" ? "note" : "parcel"} size={30} />
      <div className="min-w-0 flex-1">
        <p className="text-[14.5px] font-semibold leading-tight">
          {delivery.label} for {name}
        </p>
        <p className="mt-0.5 text-[13px] leading-tight text-ink-2">{STAGE_TEXT[delivery.stage]}</p>
      </div>
      <ol className="flex gap-1.5" aria-label={`Step ${at + 1} of 4`}>
        {STAGES.map((s, i) => (
          <li
            key={s}
            className={`h-2 w-2 rounded-full border border-ink ${i <= at ? "bg-ember" : "bg-transparent"}`}
          />
        ))}
      </ol>
    </div>
  );
}

const GREETINGS: LineId[] = ["hello", "hello2"] as LineId[];

export function HomeScreen() {
  const s = useFamily();
  const minutes = useDemoMinutes();
  const greetIndex = useRef(0);
  const recent = [...s.events].sort((a, b) => b.at - a.at).slice(0, 3);

  const greet = () => {
    let id: string;
    if (s.mode === "nightLight") id = "night";
    else if (s.mode === "charging") id = "charging";
    else if (s.mode === "delivering") id = "onIt";
    else if (s.mode === "offline") return;
    else {
      id = GREETINGS[greetIndex.current % GREETINGS.length];
      greetIndex.current += 1;
    }
    if (hasLine(id)) speak(id);
  };

  return (
    <main className="family-page">
      <div className="fg-rise flex items-start justify-between gap-4">
        <StatusNote mode={s.mode} note={s.modeNote} onLongPress={openDemoPanel} />
        <Link
          href="/family/manage"
          aria-label="Care settings and family"
          className="-mr-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-paper-2 active:scale-95"
        >
          <Glyph name="people" size={26} />
        </Link>
      </div>

      <section className="fg-rise-2 mt-8">
        <p className="fg-label">
          {s.dayLabel.split(",")[0]}
          {minutes !== null && <> · {clockLabel(minutes)}</>}
        </p>
        <h1 className="fg-display mt-2 max-w-[18ch] text-[31px] font-[500] leading-[1.06] text-ink">{headline(s, minutes)}</h1>
      </section>

      <figure className="fg-rise-2 -mx-5 mt-1">
        <MiguelStage
          className="h-[clamp(300px,44dvh,392px)]"
          pose={{ mode: s.mode, concerned: s.alert?.status === "active", carrying: s.mode === "delivering" }}
          onTap={greet}
        />
        <figcaption className="fg-label -mt-1 text-center !text-[10px] !tracking-[0.16em] text-ink-3">
          Fig. 1 — Miguel, at home with {s.resident.name}
        </figcaption>
      </figure>

      <div className="fg-rise-3 mt-7 grid grid-cols-2 gap-[18px]">
        <StickerButton href="/family/send" tone="sun" glyph="parcel" title="Send something" subtitle="Water, pills, a note" tilt={-1.4} />
        <StickerButton href="/family/check-in" tone="sky" glyph="checkIn" title="Check in" subtitle="Miguel asks her first" tilt={1.1} />
      </div>

      {s.delivery && <DeliveryStrip delivery={s.delivery} name={s.resident.short} />}

      <section className="fg-rise-4 mt-11">
        <SectionLabel right={<QuietLink href="/family/day">See all</QuietLink>}>{s.resident.short}&rsquo;s day</SectionLabel>
        <ol className="mt-5 space-y-[18px]">
          {recent.map((e) => (
            <li key={e.id} className="flex items-start gap-3.5">
              <span className="mt-[1px]">
                <Glyph name={EVENT_GLYPH[e.kind]} size={30} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[15.5px] font-semibold leading-snug">{e.title}</p>
                {(e.note || e.quote) && (
                  <p className="mt-0.5 truncate text-[13.5px] leading-snug text-ink-2">
                    {e.quote ? <span className="fg-display italic">“{e.quote}”</span> : e.note}
                  </p>
                )}
              </div>
              <time className="fg-label shrink-0 !text-[10.5px] pt-1">{clockLabel(e.at)}</time>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
