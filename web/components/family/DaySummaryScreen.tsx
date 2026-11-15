"use client";

// Miguel's summary of Mom's day: his short read of it (labeled as his read), then the facts
// it came from, grouped into movement, her routine, and what the family sent. No diagnosis.

import { clockLabel } from "@/lib/family/format";
import { useFamily } from "@/lib/family/store";
import { summarize, type PaceDay } from "@/lib/family/summary";
import type { TimelineEvent } from "@/lib/family/types";
import { Glyph } from "./Glyph";
import { EVENT_GLYPH } from "./meta";
import { FaceBadge } from "./miguel/FaceBadge";
import { PageTitle, SectionLabel, TopBar } from "./ui";

const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];

/** Walking pace for the week as bars from zero (so a steady week looks steady), today in yellow. */
function PaceChart({ days, usual }: { days: PaceDay[]; usual: number }) {
  const W = 300;
  const H = 128;
  const top = 18;
  const max = 1;
  const gutter = 28; // axis labels on the right, clear of the bars
  const y = (v: number) => top + (1 - v / max) * (H - top);
  const slot = (W - gutter) / days.length;
  const bar = 22;
  return (
    <svg viewBox={`0 0 ${W} ${H + 24}`} className="block h-auto w-full" role="img" aria-label="Walking pace, last seven days, in metres per second">
      {[0.5, 1].map((v) => (
        <g key={v}>
          <line x1={0} x2={W - gutter + 4} y1={y(v)} y2={y(v)} stroke="#e2d7c4" strokeWidth={1} />
          <text x={W} y={y(v) + 3.5} textAnchor="end" className="fill-ink-3" style={{ font: "500 9.5px var(--font-dm-mono), monospace" }}>
            {v.toFixed(1)}
          </text>
        </g>
      ))}
      {days.map((d, i) => {
        const x = i * slot + (slot - bar) / 2;
        return (
          <g key={i}>
            <rect
              x={x}
              y={y(d.value)}
              width={bar}
              height={H - y(d.value)}
              rx={6}
              fill={d.today ? "#f6c445" : "#dde7f4"}
              stroke="#2a2630"
              strokeWidth={1.5}
            />
            {d.today && (
              <text x={x + bar / 2} y={y(d.value) - 7} textAnchor="middle" className="fill-ink" style={{ font: "600 12px var(--font-figtree), sans-serif" }}>
                {d.value.toFixed(2)}
              </text>
            )}
            <text
              x={x + bar / 2}
              y={H + 17}
              textAnchor="middle"
              className={d.today ? "fill-ink" : "fill-ink-3"}
              style={{ font: `${d.today ? 600 : 500} 10.5px var(--font-dm-mono), monospace` }}
            >
              {d.initial}
            </text>
          </g>
        );
      })}
      <line x1={0} x2={W - gutter + 4} y1={y(usual)} y2={y(usual)} stroke="#2a2630" strokeWidth={1.2} strokeDasharray="4 4" opacity={0.55} />
      <line x1={0} x2={W - gutter + 4} y1={H} y2={H} stroke="#2a2630" strokeWidth={1.5} />
      <text x={W} y={H + 3.5} textAnchor="end" className="fill-ink-3" style={{ font: "500 9.5px var(--font-dm-mono), monospace" }}>
        0
      </text>
    </svg>
  );
}

function Row({ e, quoteBy = true }: { e: TimelineEvent; quoteBy?: boolean }) {
  return (
    <li className="grid grid-cols-[56px_30px_1fr] items-start gap-x-2.5">
      <time className="fg-label pt-[5px] !text-[10.5px] !tracking-[0.08em]">{clockLabel(e.at)}</time>
      <Glyph name={EVENT_GLYPH[e.kind]} size={28} />
      <div className="min-w-0">
        <p className="text-[15px] font-semibold leading-snug">{e.title}</p>
        {e.quote ? (
          <p className="mt-0.5 text-[13.5px] leading-snug">
            <span className="fg-display italic">“{e.quote}”</span>
            {quoteBy && e.quoteBy && <span className="text-ink-2"> — {e.quoteBy}</span>}
          </p>
        ) : (
          e.note && <p className="mt-0.5 text-[13.5px] leading-snug text-ink-2">{e.note}</p>
        )}
      </div>
    </li>
  );
}

export function DaySummaryScreen() {
  const s = useFamily();
  const sum = summarize(s);
  const mom = s.resident.short;
  const steady = sum.paceToday >= sum.paceUsual - 0.03;

  return (
    <main className="family-page">
      <TopBar back="/family/day" />
      <PageTitle label={`${s.dayLabel} · Miguel's summary`} title={<>{mom}&rsquo;s day, in short.</>} />

      <section className="fg-rise-2 mt-5 rounded-[22px] border-[1.5px] border-ink bg-[#fffaf1] px-5 pb-4 pt-5 shadow-[0_0_0_5px_#fffdf8,0_0_0_6.5px_rgba(42,38,48,0.1)]">
        <p className="fg-display text-[19px] leading-[1.42] text-ink">{sum.read}</p>
        <div className="mt-4 flex items-center gap-2.5 border-t border-dashed border-sand pt-3">
          <FaceBadge expression="happy" width={24} />
          <p className="text-[12px] leading-snug text-ink-2">Miguel&rsquo;s read, from what he noted today. Not a medical assessment.</p>
        </div>
      </section>

      <section className="fg-rise-3 mt-10">
        <SectionLabel>Movement</SectionLabel>
        <p className="fg-display mt-4 text-[24px] font-[540] leading-none">
          {WORDS[sum.walks.length] ?? sum.walks.length} walk{sum.walks.length === 1 ? "" : "s"} <span className="text-[15px] text-ink-2">with Miguel</span>
        </p>
        <ol className="mt-4 space-y-3.5">
          {sum.walks.map((e) => (
            <Row key={e.id} e={e} />
          ))}
        </ol>
        <div className="mt-5 rounded-[22px] border-[1.5px] border-sand px-4 pb-3 pt-4">
          <div className="flex items-baseline justify-between">
            <p className="text-[14px] font-semibold">Walking pace</p>
            <p className="fg-label !text-[10px]">m/s · last 7 days</p>
          </div>
          <div className="mt-2">
            <PaceChart days={sum.pace} usual={sum.paceUsual} />
          </div>
          <p className="mt-1 text-[12.5px] leading-snug text-ink-2">
            {steady ? "Steady" : "A little slower"} this week. Dashed line: her usual, {sum.paceUsual.toFixed(2)} m/s.
          </p>
        </div>
      </section>

      <section className="mt-10">
        <SectionLabel>Her routine</SectionLabel>
        <ol className="mt-5 space-y-3.5">
          {sum.routine.map((e) => (
            <Row key={e.id} e={e} />
          ))}
        </ol>
      </section>

      <section className="mt-10">
        <SectionLabel>From the family</SectionLabel>
        <ol className="mt-5 space-y-3.5">
          {sum.family.map((e) => (
            <Row key={e.id} e={e} />
          ))}
        </ol>
      </section>

      <p className="mt-10 text-[12.5px] leading-relaxed text-ink-3">
        Miguel notes what he sees and hears around {mom}. He doesn&rsquo;t diagnose; if something seems off, he&rsquo;ll tell you plainly.
      </p>
    </main>
  );
}
