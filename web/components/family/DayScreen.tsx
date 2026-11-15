"use client";

import { clockLabel, partOfDay } from "@/lib/family/format";
import Link from "next/link";
import { useFamily } from "@/lib/family/store";
import type { FamilyState, TimelineEvent } from "@/lib/family/types";
import { Glyph } from "./Glyph";
import { EVENT_GLYPH } from "./meta";
import { FaceBadge } from "./miguel/FaceBadge";
import { PageTitle, SectionLabel, TopBar } from "./ui";

const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const n = (k: number) => WORDS[k] ?? String(k);

/** One sentence that tells the day so far. */
function storyOf(s: FamilyState): string {
  const wake = s.events.find((e) => e.kind === "wake");
  const walks = s.events.filter((e) => e.kind === "walk").length;
  const water = s.events.filter((e) => e.kind === "water").length;
  const meds = s.events.filter((e) => e.kind === "medication").length;
  const company = s.events.find((e) => e.kind === "company");
  const parts: string[] = [];
  if (walks) parts.push(`${n(walks)} walk${walks === 1 ? "" : "s"} with Miguel`);
  if (water) parts.push(`${n(water)} glass${water === 1 ? "" : "es"} of water from you`);
  if (meds) parts.push(meds === 1 ? "her morning pills" : `${n(meds)} doses of medication`);
  if (company) parts.push(company.title.charAt(0).toLowerCase() + company.title.slice(1));
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0] ?? "a quiet day";
  return `${wake ? `Up at ${clockLabel(wake.at)}. ` : ""}${list.charAt(0).toUpperCase()}${list.slice(1)}.`;
}

const PARTS = ["night", "morning", "afternoon", "evening"] as const;

function Sparkline({ values }: { values: number[] }) {
  const w = 132;
  const h = 34;
  const min = Math.min(...values) - 0.03;
  const max = Math.max(...values) + 0.03;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - ((v - min) / (max - min)) * h] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg width={w + 8} height={h + 8} viewBox={`-4 -4 ${w + 8} ${h + 8}`} aria-hidden>
      <path d={`${d} L${w} ${h} L0 ${h}Z`} fill="#dde7f4" opacity="0.8" />
      <path d={d} fill="none" stroke="#2a2630" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="3.4" fill="#f2b632" stroke="#2a2630" strokeWidth="1.4" />
    </svg>
  );
}

function EventRow({ e, last }: { e: TimelineEvent; last: boolean }) {
  return (
    <li className="relative grid grid-cols-[58px_34px_1fr] gap-x-2">
      <time className="fg-label pt-[7px] !text-[10.5px] !tracking-[0.08em]">{clockLabel(e.at)}</time>
      <div className="relative flex justify-center">
        {!last && <span className="absolute bottom-[-2px] top-[36px] w-0 border-l-[1.5px] border-dashed border-sand" aria-hidden />}
        <span className="relative z-10">
          <Glyph name={EVENT_GLYPH[e.kind]} size={30} />
        </span>
      </div>
      <div className="pb-6 pl-1.5">
        <p className={`text-[16px] font-semibold leading-snug ${e.kind === "alert" ? "text-alarm" : ""}`}>{e.title}</p>
        {e.note && <p className="mt-1 text-[14px] leading-snug text-ink-2">{e.note}</p>}
        {e.quote && (
          <p className="mt-1 text-[14.5px] leading-snug">
            <span className="fg-display italic">“{e.quote}”</span>
            {e.quoteBy && <span className="text-ink-2"> — {e.quoteBy}</span>}
          </p>
        )}
        {e.photo && (
          // eslint-disable-next-line @next/next/no-img-element -- a photo from Miguel's server, not a page asset
          <img src={e.photo} alt={e.title} loading="lazy" className="mt-2.5 max-h-[220px] w-full rounded-xl border-[1.5px] border-ink object-cover" />
        )}
      </div>
    </li>
  );
}

export function DayScreen() {
  const s = useFamily();
  const events = [...s.events].sort((a, b) => a.at - b.at);
  const groups = PARTS.map((p) => ({ part: p, items: events.filter((e) => partOfDay(e.at) === p) })).filter((g) => g.items.length);
  const pace = s.pace;
  const today = pace[pace.length - 1];
  const usual = pace.slice(0, -1).reduce((a, b) => a + b, 0) / (pace.length - 1);
  const trend = today >= usual - 0.03 ? "Steady" : "A little slower";

  return (
    <main className="family-page">
      <TopBar />
      <PageTitle label={s.dayLabel} title={<>{s.resident.short}&rsquo;s day</>}>
        <p className="fg-display text-[19px] leading-[1.4] text-ink">{storyOf(s)}</p>
      </PageTitle>

      <Link
        href="/family/day/summary"
        className="fg-rise-2 mt-5 inline-flex items-center gap-2.5 rounded-full border-[1.5px] border-ink bg-[#fffaf1] py-1.5 pl-1.5 pr-4 text-[14px] font-semibold text-ink transition active:scale-[0.97]"
      >
        <FaceBadge expression="happy" width={24} />
        Miguel&rsquo;s summary
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </Link>

      <div className="fg-rise-2 mt-10 space-y-9">
        {groups.map((g) => (
          <section key={g.part}>
            <SectionLabel>{g.part}</SectionLabel>
            <ol className="mt-5">
              {g.items.map((e, i) => (
                <EventRow key={e.id} e={e} last={i === g.items.length - 1} />
              ))}
            </ol>
          </section>
        ))}
      </div>

      <section className="fg-rise-3 mt-6 rounded-[22px] border-[1.5px] border-sand px-5 py-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="fg-label">Field note</p>
            <p className="mt-1 text-[15px] font-semibold">Walking pace</p>
            <p className="fg-display mt-2 text-[24px] font-[540] leading-none">
              {today.toFixed(2)} <span className="text-[15px] text-ink-2">m/s</span>
            </p>
            <p className="mt-1.5 text-[13px] text-ink-2">
              {trend} this week. Her usual is {usual.toFixed(2)}.
            </p>
          </div>
          <Sparkline values={pace} />
        </div>
        <p className="mt-3 text-[12px] leading-snug text-ink-3">
          Miguel measures it on their walks together. A steady pace is a good sign; he&rsquo;ll tell you if it slips.
        </p>
      </section>
    </main>
  );
}
